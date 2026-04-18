# /gui/main_window.py

import sys
import cv2
import sounddevice as sd
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QComboBox, QLabel, QFrame, QMessageBox, 
                             QSlider, QSizePolicy) # <-- AGREGADO QSizePolicy
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from pygrabber.dshow_graph import FilterGraph

class StreamerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StreamerSync Minimalist - Panel de Control")
        self.resize(1100, 700)
        self.setMinimumSize(800, 600)
        
        # Estado de los motores
        self.v_engine = None
        self.a_engine = None
        
        # Widget Principal
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.layout = QVBoxLayout(self.main_widget)

        # --- PANEL DE CONFIGURACIÓN (SUPERIOR) ---
        self.config_panel = QHBoxLayout()
        
        self.video_combo = QComboBox()
        self.refresh_video_devices()
        
        self.audio_combo = QComboBox()
        self.refresh_audio_devices()

        self.btn_refresh = QPushButton("🔄")
        self.btn_refresh.setFixedWidth(40)
        self.btn_refresh.clicked.connect(self.refresh_all)

        self.btn_start = QPushButton("Iniciar Stream")
        self.btn_start.setMinimumHeight(35)
        self.btn_start.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; border-radius: 4px;")
        self.btn_start.clicked.connect(self.start_sync)

        self.config_panel.addWidget(QLabel("Video:"))
        self.config_panel.addWidget(self.video_combo, stretch=2)
        self.config_panel.addWidget(QLabel("Audio:"))
        self.config_panel.addWidget(self.audio_combo, stretch=2)
        self.config_panel.addWidget(self.btn_refresh)
        self.config_panel.addWidget(self.btn_start, stretch=1)
        
        self.layout.addLayout(self.config_panel)

        # --- PANEL DE CONTROL DE SYNC ---
        self.sync_panel = QHBoxLayout()
        self.sync_label = QLabel("Retraso Audio: 0ms")
        self.sync_slider = QSlider(Qt.Horizontal)
        self.sync_slider.setRange(0, 500)  # Hasta 500ms de delay
        self.sync_slider.setValue(0)
        self.sync_slider.valueChanged.connect(self.update_delay_label)
        
        self.sync_panel.addWidget(self.sync_label)
        self.sync_panel.addWidget(self.sync_slider)
        self.layout.addLayout(self.sync_panel)

        # --- PANTALLA DE VIDEO ---
        self.video_label = QLabel("Selecciona tus dispositivos y presiona Iniciar")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setFrameStyle(QFrame.NoFrame)
        self.video_label.setStyleSheet("background-color: #000000; color: #555; font-size: 14px;")
        
        # POLÍTICA DE TAMAÑO CORREGIDA:
        # Ignored permite que el widget no "empuje" a la ventana hacia afuera
        self.video_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        
        self.video_label.setMinimumSize(1, 1) 
        self.layout.addWidget(self.video_label, stretch=10)

        # Timer de renderizado (aprox 60 FPS)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)

    def update_delay_label(self, value):
        self.sync_label.setText(f"Retraso Audio: {value}ms")

    def refresh_video_devices(self):
        self.video_combo.clear()
        try:
            graph = FilterGraph()
            devices = graph.get_input_devices()
            if devices: self.video_combo.addItems(devices)
            else: self.video_combo.addItem("No se detectaron cámaras")
        except: self.video_combo.addItems(["ID 0", "ID 1", "ID 2"])

    def refresh_audio_devices(self):
        self.audio_combo.clear()
        devices = sd.query_devices()
        input_names = sorted(list(set([d['name'] for d in devices if d['max_input_channels'] > 0])))
        if input_names: self.audio_combo.addItems(input_names)
        else: self.audio_combo.addItem("No se detectaron micrófonos")

    def refresh_all(self):
        self.refresh_video_devices()
        self.refresh_audio_devices()

    def start_sync(self):
        from core.video_engine import VideoEngine
        from core.audio_engine import AudioEngine
        
        v_idx = self.video_combo.currentIndex()
        a_name = self.audio_combo.currentText()
        
        if "No se detectaron" in a_name:
            QMessageBox.warning(self, "Error", "Conecta un dispositivo de audio válido.")
            return

        try:
            self.v_engine = VideoEngine(device_index=v_idx)
            self.a_engine = AudioEngine(partial_name=a_name)
            
            self.a_engine.start_bridge()
            self.timer.start(16) 
            
            self.btn_start.setEnabled(False)
            self.btn_start.setText("🟢 En Vivo")
            self.btn_start.setStyleSheet("background-color: #27ae60; color: white; border-radius: 4px;")
            self.video_combo.setEnabled(False)
            self.audio_combo.setEnabled(False)
            
        except Exception as e:
            QMessageBox.critical(self, "Error de Hardware", f"Fallo al conectar: {e}")

    def update_frame(self):
        if self.v_engine:
            frame = self.v_engine.get_frame()
            if frame is not None:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = frame.shape
                bytes_per_line = ch * w
                qt_image = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                
                pixmap = QPixmap.fromImage(qt_image)
                # Usamos el tamaño actual del video_label para el escalado
                self.video_label.setPixmap(pixmap.scaled(
                    self.video_label.size(), 
                    Qt.KeepAspectRatio, 
                    Qt.FastTransformation 
                ))

    def closeEvent(self, event):
        if self.v_engine: self.v_engine.release()
        if self.a_engine: self.a_engine.stop()
        event.accept()