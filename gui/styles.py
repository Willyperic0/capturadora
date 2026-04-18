# /gui/styles.py

MAIN_STYLE = """
QMainWindow {
    background-color: #1e1e1e;
}

QWidget {
    color: #e0e0e0;
    font-family: 'Segoe UI', Arial;
}

QComboBox {
    background-color: #333333;
    border: 1px solid #444444;
    border-radius: 4px;
    padding: 5px;
    min-width: 200px;
}

QPushButton#btn_start {
    background-color: #2ecc71;
    color: white;
    font-weight: bold;
    font-size: 14px;
    border-radius: 6px;
}

QPushButton#btn_start:hover {
    background-color: #27ae60;
}

QSlider::handle:horizontal {
    background: #3498db;
    border: 1px solid #2980b9;
    width: 18px;
    height: 18px;
    margin: -5px 0;
    border-radius: 9px;
}

QSlider::groove:horizontal {
    border: 1px solid #444444;
    height: 8px;
    background: #333333;
    margin: 2px 0;
    border-radius: 4px;
}
"""