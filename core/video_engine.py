# /core/video_engine.py
import cv2

class VideoEngine:
    def __init__(self, device_index=None):
        # Si no le pasamos un ID, intentamos buscar uno automáticamente
        if device_index is None:
            self.device_index = self._find_last_device()
        else:
            self.device_index = device_index
            
        self.cap = cv2.VideoCapture(self.device_index)
        
        # Ajustes de ingeniería para latencia cero
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap.set(cv2.CAP_PROP_FPS, 60)
        # Forzar resolución estándar de capturadora
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    def _find_last_device(self):
        last_found = 0
        for i in range(5):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                cap.release()
                last_found = i
        return last_found

    def get_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            return None
        return frame

    def release(self):
        if self.cap.isOpened():
            self.cap.release()