# /gui/main_window.py
import cv2
import numpy as np
import sounddevice as sd
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QComboBox, QLabel, QFrame, QMessageBox, 
                             QSlider)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QPoint, QTimer
from PySide6.QtGui import QImage, QPixmap, QColor
from pygrabber.dshow_graph import FilterGraph

from core.config_manager import save_device_config, load_all_config

class StreamerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StreamerSync Pro")
        self.resize(1280, 720)
        self.setStyleSheet("background-color: #000;")
        
        self.v_engine = None
        self.a_engine = None
        self.is_fullscreen = False
        self.last_target_size = None
        self.cached_canvas = None
        
        # --- CAPA DE VIDEO ---
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.video_display = QLabel("HAGA DOBLE CLIC PARA FULLSCREEN")
        self.video_display.setAlignment(Qt.AlignCenter)
        self.video_display.setStyleSheet("color: #111;") # Texto casi invisible sobre negro
        self.layout.addWidget(self.video_display)

        # --- OVERLAY DE CARGA NEÓN (Optimizado con Animación de Opacidad) ---
        self.loader_panel = QFrame(self.central_widget)
        self.loader_panel.setGeometry(0, 0, 1280, 720)
        self.loader_panel.setStyleSheet("""
            background: qradialgradient(cx:0.5, cy:0.5, radius:0.5,
                stop:0 rgba(0, 0, 0, 240),
                stop:1 rgba(0, 20, 40, 200));
            border: 2px solid #00d4ff;
            border-radius: 10px;
        """)
        self.loader_panel.hide()
        
        l_layout = QVBoxLayout(self.loader_panel)
        self.loader_text = QLabel("⏳ Cargando video...")
        self.loader_text.setStyleSheet("""
            color: #00d4ff; 
            font-size: 26px; 
            font-weight: bold;
        """)
        self.loader_text.setAlignment(Qt.AlignCenter)
        l_layout.addWidget(self.loader_text)
        
        # Spinner para loading
        self.spinner_timer = QTimer()
        self.spinner_timer.timeout.connect(self.animate_spinner)
        self.spinner_dots = 0

        # --- BARRA DE CONTROL FLOTANTE (ESTILO "HUD") ---
        self.controls = QFrame(self.central_widget)
        self.controls.setFixedHeight(60)
        self.controls.setFixedWidth(850)
        self.controls.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(10, 10, 10, 220),
                    stop:1 rgba(20, 20, 20, 240));
                border: 1px solid #00d4ff;
                border-top: none;
                border-bottom-left-radius: 15px;
                border-bottom-right-radius: 15px;
            }
            QLabel { color: #ccc; font-size: 11px; font-weight: bold; border: none; }
            QComboBox { 
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2a2a2a, stop:1 #1a1a1a);
                color: white; 
                border: 1px solid #444; 
                border-radius: 4px;
                padding: 2px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox::down-arrow { image: url(down_arrow.png); }
            QPushButton { 
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #00d4ff, stop:1 #0099cc);
                color: black; 
                font-weight: bold; 
                border-radius: 6px;
                border: 1px solid #00aaff;
            }
            QPushButton:hover { background: #00aaff; }
            QSlider::groove:horizontal {
                background: #333;
                height: 4px;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #00d4ff;
                width: 12px;
                height: 12px;
                border-radius: 6px;
                margin: -4px 0;
            }
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

        # Animación de la barra
        self.bar_anim = QPropertyAnimation(self.controls, b"pos")
        self.bar_anim.setDuration(300)
        self.bar_anim.setEasingCurve(QEasingCurve.OutCubic)

        # Timer para auto-ocultar
        self.hide_timer = QTimer()
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide_bar)

        self.setMouseTracking(True)
        self.central_widget.setMouseTracking(True)
        self.video_display.setMouseTracking(True)

        # Audio oculto
        self.audio_combo = QComboBox()
        self.audio_combo.setVisible(False)
        
        QTimer.singleShot(100, self.reposition_ui)

    def reposition_ui(self):
        self.controls.move((self.width() - self.controls.width()) // 2, 0)
        self.loader_panel.resize(self.size())

    def animate_spinner(self):
        self.spinner_dots = (self.spinner_dots + 1) % 4
        dots = "." * self.spinner_dots
        self.loader_text.setText(f"⏳ Cargando video{dots}")
        self.loader_text.update()

    def start_sync(self):
        self.stop_session()  # Ya incluye wait
        # Reset de audio para evitar el "delay acumulado" de PortAudio
        sd._terminate(); sd._initialize()
        
        from core.video_engine import VideoEngine
        from core.audio_engine import AudioEngine
        
        try:
            v_idx = self.video_combo.currentIndex()
            # Lógica de audio automática simplificada
            a_idx = 0 
            for i, d in enumerate(sd.query_devices()):
                if d['max_input_channels'] > 0 and ("USB" in d['name'].upper() or "DIGITAL" in d['name'].upper()):
                    a_idx = i
                    break

            self.v_engine = VideoEngine(device_index=v_idx)
            self.v_engine.video_ready_signal.connect(self.on_hardware_ready)
            self.v_engine.new_frame_signal.connect(self.process_frame)
            
            self.a_engine = AudioEngine(device_index=a_idx, delay_ms=self.sync_slider.value())
            
            self.v_engine.start()
            self.a_engine.start()
            
            self.loader_panel.show()
            self.spinner_timer.start(500)  # Animar cada 500ms
            self.hide_bar()

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def on_hardware_ready(self):
        self.spinner_timer.stop()
        self.loader_panel.hide()
        if self.a_engine: self.a_engine.set_video_ready()

    def process_frame(self, frame):
        """Procesamiento ultra-optimizado"""
        if frame is None: return
        w, h = self.video_display.width(), self.video_display.height()
        if w <= 0 or h <= 0: return

        # Evitar reconstruir el canvas si el tamaño es el mismo
        if self.last_target_size != (w, h):
            self.last_target_size = (w, h)
            self.cached_canvas = np.zeros((h, w, 3), dtype=np.uint8)
        
        canvas = self.cached_canvas.copy()
        f_h, f_w = frame.shape[:2]
        aspect = f_w / f_h
        
        nw, nh = (int(h * aspect), h) if w / h > aspect else (w, int(w / aspect))
        
        # Redimensionado de alto rendimiento
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        
        xo, yo = (w - nw) // 2, (h - nh) // 2
        canvas[yo:yo+nh, xo:xo+nw] = rgb

        qimg = QImage(canvas.data, w, h, w * 3, QImage.Format_RGB888)
        self.video_display.setPixmap(QPixmap.fromImage(qimg))

    def stop_session(self):
        if self.v_engine: 
            self.v_engine.stop()
            self.v_engine.wait(2000)
            self.v_engine = None
        if self.a_engine: 
            self.a_engine.stop()
            self.a_engine.wait(2000)
            self.a_engine = None
        self.loader_panel.hide()
        self.spinner_timer.stop()
        self.video_display.setPixmap(QPixmap())
        self.show_bar()

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
        if self.v_engine and self.v_engine.isRunning():
            self.bar_anim.stop()
            self.bar_anim.setEndValue(QPoint(self.controls.x(), -65))
            self.bar_anim.start()

    def mouseDoubleClickEvent(self, event):
        if self.is_fullscreen: self.showNormal()
        else: self.showFullScreen()
        self.is_fullscreen = not self.is_fullscreen
        QTimer.singleShot(100, self.reposition_ui)

    def refresh_all(self):
        self.video_combo.clear()
        devs = FilterGraph().get_input_devices()
        self.video_combo.addItems(devs if devs else ["Sin Dispositivo"])

    def update_delay_logic(self, val):
        if self.a_engine: self.a_engine.set_delay(val)

    def resizeEvent(self, event):
        self.reposition_ui()
        super().resizeEvent(event)