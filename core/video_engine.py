# /core/video_engine.py
import cv2
import time
from PySide6.QtCore import QThread, Signal as qtSignal  # pylint: disable=no-name-in-module
import core.logger  # Importar para configurar el logger
import logging

logger = logging.getLogger(__name__)

class VideoEngine(QThread):
    # Definimos señales para comunicar con la GUI
    new_frame_signal = qtSignal(object)
    error_signal = qtSignal(str)
    started_signal = qtSignal()
    video_ready_signal = qtSignal()
    capture_fps_signal = qtSignal(float)
    frame_timestamp_signal = qtSignal(float)

    def __init__(self, device_index=0):
        super().__init__()
        self.device_index = device_index
        self.cap = None
        self.running = False
        self.first_frame_sent = False
        self.last_change_timestamp = 0
        self._frame_count = 0
        self._fps_timer = time.time()
        self.frame_index = 0
        self.audio_engine = None
        self._drift_telemetry_last_log_time = time.time()
        self.start_system_time = 0.0
        self.audio_offset = 0.0
        self._clock_log_last_time = time.time()
        self.audio_offset = 0.0
        self._clock_log_last_time = time.time()

    def run(self):
        """Inicialización y loop en hilo separado para evitar bloqueo de UI"""
        try:
            self.cap = cv2.VideoCapture(self.device_index)
            if not self.cap.isOpened():
                error_msg = "No se pudo abrir la capturadora de video"
                logger.error(error_msg)
                self.error_signal.emit(error_msg)
                return

            # Optimizaciones de hardware
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_FPS, 60)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            target_fps = self.cap.get(cv2.CAP_PROP_FPS)
            fourcc_int = int(self.cap.get(cv2.CAP_PROP_FOURCC))
            fourcc = ''.join([chr((fourcc_int >> 8 * i) & 0xFF) for i in range(4)]) if fourcc_int != 0 else 'UNKNOWN'
            logger.info(f"Video handshake: Dispositivo={self.device_index}, Resolucion={width}x{height}, FPS objetivo={target_fps:.1f}, FOURCC={fourcc}")

            self.running = True
            self.start_system_time = time.time() * 1000.0
            # Reset audio clock para sincronización perfecta
            if self.audio_engine is not None and hasattr(self.audio_engine, 'reset_audio_time'):
                self.audio_engine.reset_audio_time()
            self.audio_offset = 0.0  # Ya no necesario con reset, pero mantener por compatibilidad
            self.started_signal.emit()
            logger.info(f"VideoEngine iniciado: Dispositivo index={self.device_index}")

            while self.running:
                ret, frame = self.cap.read()
                if ret:
                    logger.debug("Frame captured, index=%d", self.frame_index + 1)
                    if not self.first_frame_sent:
                        self.video_ready_signal.emit()
                        self.first_frame_sent = True
                    self.last_change_timestamp = time.time()
                    self._emit_frame(frame)
                else:
                    time.sleep(0.01)
        except Exception as e:
            error_msg = f"Error en VideoEngine: {str(e)}"
            logger.error(error_msg)
            self.error_signal.emit(error_msg)
        finally:
            self._cleanup()

    def set_audio_engine(self, audio_engine):
        self.audio_engine = audio_engine

    def _emit_frame(self, frame):
        now = time.time()
        timestamp_system = now * 1000.0
        timestamp_audio_ref = 0.0
        if self.audio_engine is not None and hasattr(self.audio_engine, 'get_current_audio_time_ms'):
            timestamp_audio_ref = self.audio_engine.get_current_audio_time_ms()

        self.frame_index += 1
        video_elapsed_time = timestamp_system - self.start_system_time
        audio_elapsed_time = timestamp_audio_ref - self.audio_offset
        drift_ms = video_elapsed_time - audio_elapsed_time

        # Log de verificación de reloj cada 2 segundos
        if now - self._clock_log_last_time >= 2.0:
            logger.debug("Lectura de reloj: audio=%.2f, sistema_relativo=%.2f", timestamp_audio_ref, video_elapsed_time)
            self._clock_log_last_time = now

        # Modo warm-up: primeros 5 segundos (aprox. 300 frames @60fps), no descartar frames
        if self.frame_index < 300:
            # Emitir señal sí o sí durante warm-up para recuperar imagen inmediata
            pass  # Skip drift logic
        else:
            # Compensación de deriva básica
            if timestamp_audio_ref > 0.0:
                if drift_ms > 16.0:
                    sleep_time = min((drift_ms - 8.0) / 1000.0, 0.030)
                    logger.debug("Video adelantado: drift=%.2fms, durmiendo %.3fs para sincronizar", drift_ms, sleep_time)
                    time.sleep(sleep_time)
                    now = time.time()
                    timestamp_system = now * 1000.0
                    video_elapsed_time = timestamp_system - self.start_system_time
                    audio_elapsed_time = timestamp_audio_ref - self.audio_offset
                    drift_ms = video_elapsed_time - audio_elapsed_time
                elif drift_ms < -32.0:
                    logger.debug("Video atrasado: drift=%.2fms, descartando frame_index=%d para recuperar tiempo", drift_ms, self.frame_index)
                    if now - self._drift_telemetry_last_log_time >= 5.0:
                        logger.debug("Video Drift: %.2fms, audio_ref=%.2fms, frame_index=%d", drift_ms, timestamp_audio_ref, self.frame_index)
                        self._drift_telemetry_last_log_time = now
                    return

        print(f"DEBUG INTERNO: Instancia audio detectada: {self.audio_engine is not None}, Valor obtenido: {self.audio_engine.get_current_audio_time_ms() if self.audio_engine else 'N/A'}")

        frame_payload = {
            'frame_data': frame,
            'timestamp_system': timestamp_system,
            'timestamp_audio_ref': timestamp_audio_ref,
            'frame_index': self.frame_index,
        }

        if now - self._drift_telemetry_last_log_time >= 5.0:
            logger.debug("Video Drift: %.2fms, audio_ref=%.2fms, frame_index=%d", drift_ms, timestamp_audio_ref, self.frame_index)
            self._drift_telemetry_last_log_time = now

        self.frame_timestamp_signal.emit(now)
        self._frame_count += 1
        elapsed = now - self._fps_timer
        if elapsed >= 1.0:
            fps = self._frame_count / elapsed
            logger.debug("capture_fps_signal emitido: %.2f FPS", fps)
            self.capture_fps_signal.emit(fps)
            self._frame_count = 0
            self._fps_timer = now
        self.new_frame_signal.emit(frame_payload)

    def stop(self):
        self.running = False
        if self.cap and self.cap.isOpened():
            try:
                self.cap.release()
            except Exception:
                pass

        self.quit()
        if not self.wait(1000):
            self.terminate()
            self.wait(500)
        self.first_frame_sent = False
        logger.info("VideoEngine detenido")

    def _cleanup(self):
        if self.cap and self.cap.isOpened():
            self.cap.release()
            self.cap = None