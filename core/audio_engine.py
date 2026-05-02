# /core/audio_engine.py
import sounddevice as sd
import numpy as np
import time
import os
import platform
import threading
from PySide6.QtCore import QThread, Signal as qtSignal, QMutex  # pylint: disable=no-name-in-module
import core.logger  # Importar para configurar el logger
import logging

logger = logging.getLogger(__name__)

class AudioEngine(QThread):
    error_signal = qtSignal(str)
    started_signal = qtSignal()
    audio_callback_interval_signal = qtSignal(float)
    audio_jitter_signal = qtSignal(float)
    buffer_level_signal = qtSignal(float)

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
        self.priority_status = "Estándar"
        self._telemetry_last_log_time = time.time()
        self.current_audio_time_ms = 0.0
        self._audio_time_mutex = QMutex()
        self._audio_clock_log_last_time = time.time()

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

    def reset_audio_time(self):
        """Reset del contador de tiempo de audio para sincronización"""
        self._audio_time_mutex.lock()
        try:
            self.current_audio_time_ms = 0.0
            logger.debug("Audio time reset to 0.0ms")
        finally:
            self._audio_time_mutex.unlock()

    def get_current_audio_time_ms(self):
        """Retorna el tiempo actual de audio en ms de forma thread-safe"""
        self._audio_time_mutex.lock()
        try:
            return float(self.current_audio_time_ms)
        finally:
            self._audio_time_mutex.unlock()

    def run(self):
        """Inicialización y ejecución en hilo separado"""
        self.priority_status = self._apply_high_priority()
        logger.info("AudioEngine prioridad: %s", self.priority_status)
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
            delta_audio_ms = (frames / self.sample_rate) * 1000.0
            self._audio_time_mutex.lock()
            try:
                self.current_audio_time_ms += delta_audio_ms
                # Log de verificación de reloj cada 2 segundos
                if now - self._audio_clock_log_last_time >= 2.0:
                    logger.debug("Audio clock updated: current=%.2f ms", self.current_audio_time_ms)
                    self._audio_clock_log_last_time = now
            finally:
                self._audio_time_mutex.unlock()

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
                    logger.warning("Audio Jitter CRITICO (SPIKE): %.2fms (Evento #%d)", jitter_ms, self._jitter_spike_count)
                if now - self._telemetry_last_log_time >= 10.0:
                    logger.debug("Audio Telemetría: Máximo jitter=%.2fms, Spikes=%d, Intervalo actual=%.2fms", self._max_jitter, self._jitter_spike_count, interval_ms)
                    self._telemetry_last_log_time = now
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

    def _apply_high_priority(self):
        """Aplicar prioridad alta según plataforma usando wrappers dinámicos."""
        system = platform.system()

        if system == "Windows":
            try:
                import win32process
                import win32con
                proc = win32process.GetCurrentProcess()
                win32process.SetPriorityClass(proc, win32con.HIGH_PRIORITY_CLASS)
                logger.info("Prioridad de proceso Windows elevada a HIGH_PRIORITY_CLASS")
                return "Alta (Win32)"
            except ImportError as exc:
                logger.warning("pywin32 no disponible; intentando ctypes para elevar prioridad en Windows: %s", exc)
                priority_error = "ImportError"
            except Exception as exc:
                logger.warning("No se pudo elevar prioridad en Windows: %s", exc)
                return f"Estándar (Windows error: {exc})"

            try:
                import ctypes
                hthread = ctypes.windll.kernel32.GetCurrentThread()
                THREAD_PRIORITY_HIGHEST = 2
                if not ctypes.windll.kernel32.SetThreadPriority(hthread, THREAD_PRIORITY_HIGHEST):
                    raise OSError("SetThreadPriority falló")
                logger.info("Prioridad de hilo elevada en Windows mediante ctypes")
                return "Alta (ctypes)"
            except Exception as exc:
                logger.warning("No se pudo elevar prioridad de hilo en Windows mediante ctypes: %s", exc)
                return f"Estándar (Windows ctypes error: {exc})"

        elif system in ("Linux", "Darwin"):
            setpriority = getattr(os, "setpriority", None)
            prio_process = getattr(os, "PRIO_PROCESS", None)
            if callable(setpriority) and prio_process is not None:
                try:
                    pid = os.getpid()
                    setpriority(prio_process, pid, -10)
                    logger.info("Prioridad de proceso elevada en %s (nice=-10)", system)
                    return "Alta (Unix)"
                except PermissionError as exc:
                    logger.warning("Sin permisos para establecer prioridad alta en %s: %s", system, exc)
                    return "Estándar (PermissionError)"
                except Exception as exc:
                    logger.warning("No se pudo elevar prioridad en %s: %s", system, exc)
                    return f"Estándar ({system} error: {exc})"
            logger.warning("setpriority no disponible en esta plataforma %s", system)
            return "Estándar (no disponible)"
        else:
            logger.info("Gestión de prioridad no soportada en plataforma %s", system)
            return "Estándar (no soportado)"

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