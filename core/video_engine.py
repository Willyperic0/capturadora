# /core/video_engine.py
import cv2
import time
from PySide6.QtCore import QThread, Signal

class VideoEngine(QThread):
    # Definimos señales para comunicar con la GUI
    new_frame_signal = Signal(object)
    error_signal = Signal(str)
    started_signal = Signal()
    video_ready_signal = Signal()  # Señal cuando el primer frame está listo

    def __init__(self, device_index=0):
        super().__init__()
        self.device_index = device_index
        self.cap = None
        self.running = False
        self.first_frame_sent = False
        
    def run(self):
        """Inicialización y loop en hilo separado para evitar bloqueo de UI"""
        try:
            self.cap = cv2.VideoCapture(self.device_index)
            if not self.cap.isOpened():
                self.error_signal.emit("No se pudo abrir la capturadora de video")
                return
            
            # Optimizaciones de hardware
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_FPS, 60)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            
            self.running = True
            self.started_signal.emit()
            
            # Para el futuro Auto-Sync
            self.last_change_timestamp = 0
            
            while self.running:
                ret, frame = self.cap.read()
                if ret:
                    if not self.first_frame_sent:
                        self.video_ready_signal.emit()
                        self.first_frame_sent = True
                    self.last_change_timestamp = time.time()
                    # Enviamos el frame a la GUI
                    self.new_frame_signal.emit(frame)
                else:
                    time.sleep(0.01)
        except Exception as e:
            self.error_signal.emit(f"Error en VideoEngine: {str(e)}")
        finally:
            self._cleanup()

    def stop(self):
        self.running = False
        self.wait()  # Esperamos a que el hilo termine limpiamente
        self.first_frame_sent = False

    def _cleanup(self):
        if self.cap and self.cap.isOpened():
            self.cap.release()
            self.cap = None