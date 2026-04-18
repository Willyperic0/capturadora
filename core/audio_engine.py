# /core/audio_engine.py
import sounddevice as sd
import numpy as np
import time
from PySide6.QtCore import QThread, Signal, QMutex

class AudioEngine(QThread):
    error_signal = Signal(str)
    started_signal = Signal()
    
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
        try:
            # Verificar si el device_index es válido
            devices = sd.query_devices()
            if self.device_index < 0 or self.device_index >= len(devices) or devices[self.device_index]['max_input_channels'] == 0:
                print(f"DEBUG: [AUDIO] Índice {self.device_index} inválido, usando fallback")
                self.device_index, _ = self._find_device_smart("")
            
            device_name = devices[self.device_index]['name']
            
            # Reset atómico del buffer antes de inicializar
            self.reset_buffer()
            
            # Buffer circular usando NumPy (mucho más rápido que deque)
            self.delay_samples = int((self.delay_ms / 1000) * self.sample_rate)
            # Reservamos espacio para 2 segundos de buffer para evitar overflows
            self.buffer_size = self.sample_rate * 2 
            self.ring_buffer = np.zeros((self.buffer_size, self.channels), dtype='float32')
            
            self.write_ptr = self.delay_samples % self.buffer_size
            self.read_ptr = 0
            
            self._start_stream()
            self.running = True
            print(f"AUDIO_START: Dispositivo={device_name}, ID={self.device_index}, Canales={self.channels}")
            self.started_signal.emit()
            self.last_device_index = self.device_index  # Actualizar solo si exitoso
            
            # Mantener el hilo vivo mientras el stream corre
            while self.running and self.stream and self.stream.active:
                self.msleep(100)  # Pequeño sleep para no consumir CPU
                
        except Exception as e:
            self.error_signal.emit(f"Error en AudioEngine: {str(e)}")
        finally:
            self._cleanup()
    
    def _start_stream(self):
        """Inicia el puente de audio con procesamiento vectorizado."""
        try:
            in_info = sd.query_devices(self.device_index, 'input')
            self.channels = min(2, in_info['max_input_channels'])  # Usar hasta 2 canales según el dispositivo
            
            host_api_index = in_info['hostapi']
            host_api_info = sd.query_hostapis(host_api_index)
            out_device_index = host_api_info['default_output_device']
            
            print(f"AUDIO: Usando {host_api_info['name']} | In: {self.device_index} -> Out: {out_device_index}")

        except Exception as e:
            print(f"WARN: Error de negociación: {e}")
            out_device_index = None 

        def callback(indata, outdata, frames, time, status):
            if status:
                print(f"Audio Status: {status}")
            # Quitar spam de callback
            
            self.mutex.lock()
            try:
                # --- LÓGICA DE BUFFER CIRCULAR VECTORIZADA ---
                # 1. Escribir datos de entrada en el buffer
                end_write = self.write_ptr + frames
                if end_write <= self.buffer_size:
                    self.ring_buffer[self.write_ptr:end_write] = indata
                else:
                    # Wrap around (cuando llega al final del arreglo)
                    first_part = self.buffer_size - self.write_ptr
                    self.ring_buffer[self.write_ptr:] = indata[:first_part]
                    self.ring_buffer[:frames - first_part] = indata[first_part:]
                
                self.write_ptr = (self.write_ptr + frames) % self.buffer_size

                # 2. Leer datos con el delay aplicado
                end_read = self.read_ptr + frames
                if end_read <= self.buffer_size:
                    outdata[:] = self.ring_buffer[self.read_ptr:end_read]
                else:
                    first_part = self.buffer_size - self.read_ptr
                    outdata[:first_part] = self.ring_buffer[self.read_ptr:]
                    outdata[first_part:] = self.ring_buffer[:frames - first_part]
                
                self.read_ptr = (self.read_ptr + frames) % self.buffer_size

                # Audio siempre activo, no espera video
                # if not self.is_video_ready:
                #     outdata.fill(0)
            finally:
                self.mutex.unlock()

        try:
            # blocksize=1024 para estabilizar capturadoras baratas
            self.stream = sd.Stream(
                device=(self.device_index, out_device_index),
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=callback,
                blocksize=1024, 
                dtype='float32'
            )
            self.stream.start()
        except Exception as e:
            print(f"CRITICAL: {e}")
            raise e

    def set_delay(self, ms):
        """Actualiza el delay en tiempo real moviendo el puntero de escritura."""
        if not self.running:
            return
        self.mutex.lock()
        try:
            new_delay = int((ms / 1000) * self.sample_rate)
            self.delay_samples = new_delay
            # Reposicionamos el puntero de escritura relativo al de lectura
            self.write_ptr = (self.read_ptr + new_delay) % self.buffer_size
        finally:
            self.mutex.unlock()

    def stop(self):
        print("DEBUG: [AUDIO] Cerrando stream y liberando recursos...")
        self.running = False
        # Asegurar que el stream se cierre completamente
        if self.stream:
            try:
                sd.stop()
                self.stream.abort()
                self.stream.close()
                # Esperar un poco para que se libere
                time.sleep(0.1)
            except:
                pass
        self.wait()
            self.stream = None
        sd.stop()  # Parada global de emergencia
        # Forzar liberación de drivers USB
        try:
            sd._terminate()
            sd._initialize()
        except:
            pass

    def _cleanup(self):
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except:
                pass
            self.stream = None

    def _find_device_smart(self, name):
        """Busca el dispositivo como fallback simple, sin prioridades hardcodeadas."""
        devices = sd.query_devices()
        print(f"DEBUG: [AUDIO] Buscando dispositivo con nombre parcial: '{name}'")
        devices = sd.query_devices()
        print(f"DEBUG: [AUDIO] Dispositivos disponibles:")
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                print(f"  {i}: {dev['name']}")
        
        # Sin prioridades, devolver el primer dispositivo disponible
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                return i, dev['name']
        return 0, "Default Device"