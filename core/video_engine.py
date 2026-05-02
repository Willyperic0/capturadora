# /core/video_engine.py
import cv2
import time
from PySide6.QtCore import QThread, Signal
import core.logger  # Importar para configurar el logger
import logging

logger = logging.getLogger(__name__)

class VideoEngine(QThread):
    # Definimos señales para comunicar con la GUI
    new_frame_signal = Signal(object)
    error_signal = Signal(str)
    started_signal = Signal()
    video_ready_signal = Signal()
    capture_fps_signal = Signal(float)
    frame_timestamp_signal = Signal(float)

    def __init__(self, device_index=0):
        super().__init__()
        self.device_index = device_index
        self.cap = None
        self.running = False
        self.first_frame_sent = False
        self.last_change_timestamp = 0
        self._frame_count = 0
        self._fps_timer = time.time()

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
            self.started_signal.emit()
            logger.info(f"VideoEngine iniciado: Dispositivo index={self.device_index}")

            while self.running:
                ret, frame = self.cap.read()
                if ret:
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

    def _emit_frame(self, frame):
        now = time.time()
        self.frame_timestamp_signal.emit(now)
        self._frame_count += 1
        elapsed = now - self._fps_timer
        if elapsed >= 1.0:
            fps = self._frame_count / elapsed
            logger.debug(f"capture_fps_signal emitido: {fps:.2f} FPS")
            self.capture_fps_signal.emit(fps)
            self._frame_count = 0
            self._fps_timer = now
        self.new_frame_signal.emit(frame)

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