# /gui/main_window.py
import cv2
import time
import numpy as np
import sounddevice as sd
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QComboBox, QLabel, QFrame, QMessageBox, 
                             QSlider)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QPoint, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap, QColor
from pygrabber.dshow_graph import FilterGraph

from core.config_manager import save_device_config, load_all_config
from core.sync_manager import SyncManager
import core.logger  # Importar para configurar el logger
import logging

logger = logging.getLogger(__name__)

class StreamerWindow(QMainWindow):
    render_fps_signal = Signal(float)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StreamerSync Pro")
        self.resize(1280, 720)
        self.setStyleSheet("background-color: #000;")
        
        self.sync_manager = SyncManager(self)
        self.is_fullscreen = False
        self.last_target_size = None
        self.cached_canvas = None
        self._render_frame_count = 0
        self._render_fps_timer = time.time()
        
        # --- CAPA DE VIDEO ---
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.video_display = QLabel("")
        self.video_display.setAlignment(Qt.AlignCenter)
        self.video_display.setStyleSheet("color: #333;")
        self.layout.addWidget(self.video_display)

        # --- OVERLAY DE CARGA NEÓN (Optimizado con Animación de Opacidad) ---
        self.loader_panel = QFrame(self.central_widget)
        self.loader_panel.setGeometry(0, 0, 1280, 720)
        self.loader_panel.setStyleSheet("background-color: rgba(0, 0, 0, 200);")
        self.loader_panel.hide()
        
        l_layout = QVBoxLayout(self.loader_panel)
        self.loader_text = QLabel("Cargando...")
        self.loader_text.setStyleSheet("color: #aaa; font-size: 18px; font-weight: normal;")
        self.loader_text.setAlignment(Qt.AlignCenter)
        l_layout.addWidget(self.loader_text)
        
        self.glow = QPropertyAnimation(self.loader_text, b"windowOpacity")
        self.glow.setDuration(1500)
        self.glow.setStartValue(0.5)
        self.glow.setEndValue(1.0)
        self.glow.setLoopCount(-1)
        self.glow.setEasingCurve(QEasingCurve.InOutQuad)

        # --- BARRA DE CONTROL FLOTANTE (ESTILO "HUD") ---
        self.controls = QFrame(self.central_widget)
        self.controls.setFixedHeight(50)
        self.controls.setFixedWidth(700)
        self.controls.setStyleSheet("""
            QFrame {
                background-color: rgba(20, 20, 20, 180);
                border: none;
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
            }
            QLabel { color: #ccc; font-size: 9px; border: none; }
            QComboBox { background: #2a2a2a; color: #ddd; border: 1px solid #444; border-radius: 3px; }
            QPushButton { background: #555; color: #fff; font-weight: normal; border-radius: 3px; }
            QPushButton:hover { background: #666; }
        """)
        
        c_layout = QHBoxLayout(self.controls)
        self.video_combo = QComboBox()
        self.video_combo.setFixedWidth(200)
        
        self.btn_start = QPushButton("STREAM")
        self.btn_start.setFixedSize(100, 32)
        self.btn_start.clicked.connect(self.start_sync)

        self.sync_slider = QSlider(Qt.Horizontal)
        self.sync_slider.setRange(0, 500)
        self.sync_slider.setFixedWidth(150)
        self.sync_slider.valueChanged.connect(self.update_delay_logic)

        c_layout.addWidget(QLabel("SOURCE:"))
        c_layout.addWidget(self.video_combo)
        c_layout.addStretch()
        c_layout.addWidget(QLabel("DELAY:"))
        c_layout.addWidget(self.sync_slider)
        c_layout.addSpacing(10)
        c_layout.addWidget(self.btn_start)

        self.bar_anim = QPropertyAnimation(self.controls, b"pos")
        self.bar_anim.setDuration(300)
        self.bar_anim.setEasingCurve(QEasingCurve.OutCubic)

        self.hide_timer = QTimer()
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide_bar)

        self.setMouseTracking(True)
        self.central_widget.setMouseTracking(True)
        self.video_display.setMouseTracking(True)

        self.audio_combo = QComboBox()
        self.audio_combo.setVisible(False)
        
        self.sync_manager.new_frame_signal.connect(self.process_frame)
        self.sync_manager.session_state_signal.connect(self.on_session_state_changed)
        self.sync_manager.error_signal.connect(self.on_sync_error)
        self.sync_manager.capture_fps_signal.connect(self.on_capture_fps)
        self.sync_manager.audio_jitter_signal.connect(self.on_audio_jitter)
        self.sync_manager.buffer_level_signal.connect(self.on_buffer_level)
        self.sync_manager.audio_callback_interval_signal.connect(self.on_audio_callback_interval)

        QTimer.singleShot(100, self.reposition_ui)

    def reposition_ui(self):
        self.controls.move((self.width() - self.controls.width()) // 2, 0)
        self.loader_panel.resize(self.size())

    def start_sync(self):
        self.stop_session()
        sd._terminate(); sd._initialize()

        try:
            video_index = self.video_combo.currentIndex()
            self.sync_manager.start_session(video_index, self.sync_slider.value())
            self.loader_panel.show()
            self.glow.start()
            self.hide_bar()
            logger.info(f"Sesión iniciada: Video index={video_index}, Delay={self.sync_slider.value()}ms")
        except Exception as e:
            logger.error(f"Error al iniciar sesión: {str(e)}")
            QMessageBox.critical(self, "Error", str(e))

    def on_session_state_changed(self, state):
        if state == "waiting_video":
            self.loader_text.setText("Iniciando captura de video...")
            self.loader_panel.show()
            self.glow.start()
        elif state == "synchronizing":
            self.loader_text.setText("Sincronizando audio con video...")
            self.loader_panel.show()
            self.glow.start()
        elif state == "ready":
            self.glow.stop()
            self.loader_panel.hide()
        elif state == "stopped":
            self.loader_panel.hide()
        elif state == "audio_started":
            self.loader_text.setText("Audio iniciado, esperando video estable...")
        elif state == "video_started":
            self.loader_text.setText("Video iniciado, esperando primer frame...")

    def on_sync_error(self, message):
        self.stop_session()
        QMessageBox.critical(self, "Error de sincronización", message)

    def on_capture_fps(self, fps):
        logger.debug(f"Capture FPS={fps:.1f}")

    def on_audio_jitter(self, jitter_ms):
        logger.debug(f"Audio jitter={jitter_ms:.2f}ms")

    def on_buffer_level(self, percent):
        print(f"DEBUG: Buffer level={percent:.1f}%")

    def on_audio_callback_interval(self, interval_ms):
        print(f"DEBUG: Audio callback interval={interval_ms:.2f}ms")

    def process_frame(self, frame):
        """Procesamiento ultra-optimizado"""
        if frame is None:
            return
        w, h = self.video_display.width(), self.video_display.height()
        if w <= 0 or h <= 0:
            return

        if self.last_target_size != (w, h):
            self.last_target_size = (w, h)
            self.cached_canvas = np.zeros((h, w, 3), dtype=np.uint8)

        canvas = self.cached_canvas.copy()
        f_h, f_w = frame.shape[:2]
        aspect = f_w / f_h
        nw, nh = (int(h * aspect), h) if w / h > aspect else (w, int(w / aspect))

        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

        xo, yo = (w - nw) // 2, (h - nh) // 2
        canvas[yo:yo+nh, xo:xo+nw] = rgb

        qimg = QImage(canvas.data, w, h, w * 3, QImage.Format_RGB888)
        self.video_display.setPixmap(QPixmap.fromImage(qimg))

        now = time.time()
        self._render_frame_count += 1
        elapsed = now - self._render_fps_timer
        if elapsed >= 1.0:
            fps = self._render_frame_count / elapsed
            self.render_fps_signal.emit(fps)
            self._render_frame_count = 0
            self._render_fps_timer = now

    def stop_session(self):
        self.sync_manager.stop_session()
        self.loader_panel.hide()
        self.video_display.setPixmap(QPixmap())
        self.show_bar()
        logger.info("Sesión detenida desde GUI")

    # --- HUD GHOST LOGIC ---
    def mouseMoveEvent(self, event):
        if event.position().y() < 80:
            self.show_bar()
        super().mouseMoveEvent(event)

    def show_bar(self):
        self.bar_anim.stop()
        self.bar_anim.setEndValue(QPoint(self.controls.x(), 0))
        self.bar_anim.start()
        self.hide_timer.start(3000)

    def hide_bar(self):
        self.bar_anim.stop()
        self.bar_anim.setEndValue(QPoint(self.controls.x(), -65))
        self.bar_anim.start()

    def mouseDoubleClickEvent(self, event):
        if self.is_fullscreen:
            self.showNormal()
        else:
            self.showFullScreen()
        self.is_fullscreen = not self.is_fullscreen
        QTimer.singleShot(100, self.reposition_ui)

    def refresh_all(self):
        self.video_combo.clear()
        devs = FilterGraph().get_input_devices()
        self.video_combo.addItems(devs if devs else ["Sin Dispositivo"])

    def update_delay_logic(self, val):
        self.sync_manager.audio_engine.set_delay(val) if self.sync_manager.audio_engine else None

    def resizeEvent(self, event):
        self.reposition_ui()
        super().resizeEvent(event)

    def closeEvent(self, event):
        self.stop_session()
        event.accept()