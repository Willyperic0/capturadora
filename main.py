# /main.py

import sys
from PySide6.QtWidgets import QApplication
from gui.main_window import StreamerWindow

def main():
    app = QApplication(sys.argv)
    window = StreamerWindow()
    window.show()
    window.refresh_all()  # Llamar después de show para que las señales funcionen
    sys.exit(app.exec())

if __name__ == "__main__":
    main()