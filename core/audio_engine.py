# /core/audio_engine.py
import sounddevice as sd
import numpy as np
import time
import os
import threading
from PySide6.QtCore import QThread, Signal, QMutex
import core.logger  # Importar para configurar el logger
import logging

logger = logging.getLogger(__name__)

class AudioEngine(QThread):
    error_signal = Signal(str)
    started_signal = Signal()
    audio_callback_interval_signal = Signal(float)
    audio_jitter_signal = Signal(float)
    buffer_level_signal = Signal(float)

    def __init__(self, device_index, delay_ms=0):
        super().__init__()
        self.device_index = device_index
        self.delay_ms = delay_ms
        self.last_device_index = None
        self.sample_rate = 44100
        self.stream = None
        self.channels = 1  # Forzar mono para compatibilidad
        self.running = False
        self.is_video_ready = False  # Para sincronización con video
        self.mutex = QMutex()  # Mutex para acceso thread-safe al buffer
        self._last_callback_time = None
        self.delay_samples = int((self.delay_ms / 1000) * self.sample_rate)
        self.buffer_size = self.sample_rate * 2
        self.write_ptr = self.delay_samples % self.buffer_size
        self.read_ptr = 0
        self.ring_buffer = np.zeros((self.buffer_size, self.channels), dtype='float32')
        self._max_jitter = 0.0
        self._jitter_spike_count = 0

    def set_video_ready(self):
        """Señal para indicar que el video está listo y el audio puede empezar"""
        self.is_video_ready = True

    def reset_buffer(self):
        """Reset atómico del buffer de audio para evitar audio residual"""
        self.mutex.lock()
        try:
            if hasattr(self, 'ring_buffer'):
                self.ring_buffer.fill(0)
                self.write_ptr = self.delay_samples % self.buffer_size
                self.read_ptr = 0
            self.is_video_ready = False
        finally:
            self.mutex.unlock()

    def run(self):
        """Inicialización y ejecución en hilo separado"""
        self._set_thread_priority()
        try:
            devices = sd.query_devices()
            if self.device_index < 0 or self.device_index >= len(devices) or devices[self.device_index]['max_input_channels'] == 0:
                logger.debug(f"Índice {self.device_index} inválido, usando fallback")
                self.device_index, _ = self._find_device_smart("")

            device_name = devices[self.device_index]['name']
            self.delay_samples = int((self.delay_ms / 1000) * self.sample_rate)
            self.buffer_size = self.sample_rate * 2
            self.channels = 1
            self.ring_buffer = np.zeros((self.buffer_size, self.channels), dtype='float32')
            self.write_ptr = self.delay_samples % self.buffer_size
            self.read_ptr = 0

            self.reset_buffer()
            self._start_stream()

            self.running = True
            logger.info(f"AudioEngine iniciado: Dispositivo={device_name}, ID={self.device_index}, Canales={self.channels}")
            self.started_signal.emit()
            self.last_device_index = self.device_index

            while self.running and self.stream and self.stream.active:
                self.msleep(100)
            
            if self._jitter_spike_count > 0:
                logger.warning(f"Resumen: Detectados {self._jitter_spike_count} picos de jitter critico (>30ms) durante la sesion")
            if self._max_jitter > 0.0:
                logger.info(f"Resumen: Máximo jitter registrado = {self._max_jitter:.2f}ms")

        except Exception as e:
            error_msg = f"Error en AudioEngine: {str(e)}"
            logger.error(error_msg)
            self.error_signal.emit(error_msg)
        finally:
            self._cleanup()

    def _start_stream(self):
        """Inicia el puente de audio con procesamiento vectorizado."""
        try:
            in_info = sd.query_devices(self.device_index, 'input')
            self.channels = min(2, in_info['max_input_channels'])
            host_api_index = in_info['hostapi']
            host_api_info = sd.query_hostapis(host_api_index)
            out_device_index = host_api_info['default_output_device']

            logger.info(f"Audio handshake: HostAPI={host_api_info['name']}, InDevice={self.device_index}, OutDevice={out_device_index}, Canales={self.channels}")
        except Exception as e:
            logger.warning(f"Error de negociación de audio: {e}")
            out_device_index = None

        def callback(indata, outdata, frames, time_info, status):
            if status:
                logger.debug(f"Audio Status: {status}")

            now = time.time()
            if self._last_callback_time is not None:
                interval_ms = (now - self._last_callback_time) * 1000.0
                expected_ms = (frames / self.sample_rate) * 1000.0
                jitter_ms = abs(interval_ms - expected_ms)
                self.audio_callback_interval_signal.emit(interval_ms)
                self.audio_jitter_signal.emit(jitter_ms)
                if jitter_ms > self._max_jitter:
                    self._max_jitter = jitter_ms
                # Detección de picos de jitter críticos (>30ms)
                if jitter_ms > 30.0:
                    self._jitter_spike_count += 1
                    logger.warning(f"Audio Jitter CRITICO (SPIKE): {jitter_ms:.2f}ms (Evento #{self._jitter_spike_count})")
            self._last_callback_time = now

            self.mutex.lock()
            try:
                end_write = self.write_ptr + frames
                if end_write <= self.buffer_size:
                    self.ring_buffer[self.write_ptr:end_write] = indata
                else:
                    first_part = self.buffer_size - self.write_ptr
                    self.ring_buffer[self.write_ptr:] = indata[:first_part]
                    self.ring_buffer[:frames - first_part] = indata[first_part:]

                self.write_ptr = (self.write_ptr + frames) % self.buffer_size

                end_read = self.read_ptr + frames
                if end_read <= self.buffer_size:
                    outdata[:] = self.ring_buffer[self.read_ptr:end_read]
                else:
                    first_part = self.buffer_size - self.read_ptr
                    outdata[:first_part] = self.ring_buffer[self.read_ptr:]
                    outdata[first_part:] = self.ring_buffer[:frames - first_part]

                self.read_ptr = (self.read_ptr + frames) % self.buffer_size

                buffer_fill = (self.write_ptr - self.read_ptr) % self.buffer_size
                self.buffer_level_signal.emit((buffer_fill / self.buffer_size) * 100.0)

                if not self.is_video_ready:
                    outdata.fill(0)
                    return
            finally:
                self.mutex.unlock()

        try:
            self.stream = sd.Stream(
                device=(self.device_index, out_device_index),
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=callback,
                blocksize=2048,
                dtype='float32'
            )
            logger.info(f"Stream de audio configurado: blocksize=2048 (46.44ms de periodo esperado)")
            self.stream.start()
        except Exception as e:
            logger.error(f"Error crítico en stream: {e}")
            raise e

    def set_delay(self, ms):
        if not self.running:
            return
        self.mutex.lock()
        try:
            new_delay = int((ms / 1000) * self.sample_rate)
            self.delay_samples = new_delay
            self.write_ptr = (self.read_ptr + new_delay) % self.buffer_size
        finally:
            self.mutex.unlock()

    def stop(self):
        logger.debug("Cerrando stream y liberando recursos...")
        self.running = False
        if self.stream:
            try:
                sd.stop()
                self.stream.abort()
                self.stream.close()
                time.sleep(0.1)
            except Exception:
                pass

        self.quit()
        if not self.wait(1000):
            self.terminate()
            self.wait(500)

        self.stream = None
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
        logger.info("AudioEngine detenido")

    def _cleanup(self):
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    def _set_thread_priority(self):
        """Elevar la prioridad del hilo de audio para reducir latencia."""
        try:
            if os.name == 'nt':  # Windows
                try:
                    import ctypes
                    thread_id = threading.current_thread().ident
                    logger.debug(f"Elevando prioridad del hilo de audio (Windows, thread_id={thread_id})")
                    # En Windows, intentar establecer HIGH_PRIORITY_CLASS
                    try:
                        # SetThreadPriority: -2 = current thread, 4 = THREAD_PRIORITY_HIGHEST
                        ctypes.windll.kernel32.SetThreadPriority(-2, 4)
                        logger.info("Prioridad de hilo de audio elevada a THREAD_PRIORITY_HIGHEST (Windows)")
                    except:
                        logger.debug("No se pudo establecer prioridad HIGH en Windows")
                except Exception as e:
                    logger.debug(f"No se puede elevar prioridad en Windows: {e}")
            else:  # Linux/macOS
                try:
                    pid = os.getpid()
                    # Establecer nice = -10 (requiere permisos)
                    os.setpriority(os.PRIO_PROCESS, pid, -10)
                    logger.info("Prioridad de proceso de audio elevada (Linux/macOS, nice=-10)")
                except PermissionError:
                    logger.warning("Sin permisos de administrador para establecer prioridad de audio. Continuando sin elevacion.")
                except Exception as e:
                    logger.debug(f"No se puede elevar prioridad: {e}")
        except Exception as e:
            logger.debug(f"Error al intentar elevar prioridad de audio: {e}")

    def _find_device_smart(self, name):
        devices = sd.query_devices()
        logger.debug(f"Buscando dispositivo con nombre parcial: '{name}'")
        logger.debug(f"Dispositivos disponibles:")
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                print(f"  {i}: {dev['name']}")

        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                return i, dev['name']
        return 0, "Default Device"