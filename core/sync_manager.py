# /core/sync_manager.py
import time
from PySide6.QtCore import QObject, Signal
from core.video_engine import VideoEngine
from core.audio_engine import AudioEngine
from core.audio_sync import find_audio_by_hw_id
import core.logger  # Importar para configurar el logger
import logging

logger = logging.getLogger(__name__)

class SyncManager(QObject):
    session_state_signal = Signal(str)
    error_signal = Signal(str)
    new_frame_signal = Signal(object)
    capture_fps_signal = Signal(float)
    audio_jitter_signal = Signal(float)
    buffer_level_signal = Signal(float)
    audio_callback_interval_signal = Signal(float)
    video_ready_signal = Signal()
    audio_ready_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.video_engine = None
        self.audio_engine = None
        self._video_ready = False
        self._audio_started = False
        self._session_start_time = None
        self._total_frames = 0
        self._max_jitter = 0.0
        self._telemetry_timer = time.time()

    def start_session(self, video_index, delay_ms):
        self.stop_session()
        self._video_ready = False
        self._audio_started = False
        self._session_start_time = time.time()
        self._total_frames = 0
        self._max_jitter = 0.0
        self._emit_state("waiting_video")

        audio_index = find_audio_by_hw_id(video_index)
        logger.info(f"Inicio de sesión: Video index={video_index}, Audio index={audio_index}, Delay={delay_ms}ms")

        self.video_engine = VideoEngine(device_index=video_index)
        self.video_engine.video_ready_signal.connect(self._on_video_ready)
        self.video_engine.new_frame_signal.connect(self._on_new_frame)
        self.video_engine.started_signal.connect(lambda: self._emit_state("video_started"))
        self.video_engine.error_signal.connect(self._on_error)
        self.video_engine.capture_fps_signal.connect(self._on_capture_fps)

        self.audio_engine = AudioEngine(device_index=audio_index, delay_ms=delay_ms)
        self.video_engine.set_audio_engine(self.audio_engine)
        self.audio_engine.started_signal.connect(self._on_audio_started)
        self.audio_engine.error_signal.connect(self._on_error)
        self.audio_engine.audio_jitter_signal.connect(self._on_audio_jitter)
        self.audio_engine.buffer_level_signal.connect(self._on_buffer_level)
        self.audio_engine.audio_callback_interval_signal.connect(self._on_audio_callback_interval)

        self.video_engine.start()
        self.audio_engine.start()

    def stop_session(self):
        if self._session_start_time:
            duration = time.time() - self._session_start_time
            avg_fps = self._total_frames / duration if duration > 0 else 0
            priority_state = "Estándar"
            if self.audio_engine is not None:
                priority_state = getattr(self.audio_engine, "priority_status", "Estándar")
            logger.info("Resumen de Auditoría: Duración total=%.2fs, FPS promedio de captura=%.2f, Máximo jitter registrado=%.2fms, Prioridad de audio=%s", duration, avg_fps, self._max_jitter, priority_state)
            self._session_start_time = None

        if self.video_engine:
            logger.debug("Deteniendo VideoEngine primero para cierre sincronizado")
            self.video_engine.stop()
            self.video_engine = None
        if self.audio_engine:
            logger.debug("Deteniendo AudioEngine después de VideoEngine")
            self.audio_engine.stop()
            self.audio_engine = None
        self._emit_state("stopped")
        logger.info("Cierre de sesión completado")

    def _on_video_ready(self):
        self._video_ready = True
        self._emit_state("synchronizing")
        if self.audio_engine:
            self.audio_engine.set_video_ready()
        self.video_ready_signal.emit()
        self._maybe_ready()
        logger.info("Handshake completado: Video listo, habilitando audio")

    def _on_audio_started(self):
        self._audio_started = True
        self._emit_state("audio_started")
        self._maybe_ready()

    def _maybe_ready(self):
        if self._video_ready and self._audio_started:
            self._emit_state("ready")
            self.audio_ready_signal.emit()
            logger.info("Sesión lista: Video y audio sincronizados")

    def _on_new_frame(self, frame):
        self.new_frame_signal.emit(frame)
        self._total_frames += 1
        now = time.time()
        if now - self._telemetry_timer >= 5.0:
            logger.debug(f"Telemetría: Frames totales={self._total_frames}, Jitter máximo={self._max_jitter:.2f}ms")
            self._telemetry_timer = now

    def _on_error(self, message):
        logger.error(f"Error de sincronización: {message}")
        self.error_signal.emit(message)
        self.stop_session()

    def _on_capture_fps(self, fps):
        self.capture_fps_signal.emit(fps)
        if fps < 50:
            logger.warning(f"Degradación de captura: FPS={fps:.1f} < 50")

    def _on_audio_jitter(self, jitter_ms):
        self.audio_jitter_signal.emit(jitter_ms)
        if jitter_ms > self._max_jitter:
            self._max_jitter = jitter_ms
        if jitter_ms > 20.0:
            logger.warning(f"Degradación de audio: Jitter={jitter_ms:.2f}ms > 20ms")

    def _on_buffer_level(self, percent):
        self.buffer_level_signal.emit(percent)

    def _on_audio_callback_interval(self, interval_ms):
        self.audio_callback_interval_signal.emit(interval_ms)

    def _emit_state(self, state):
        self.session_state_signal.emit(state)
