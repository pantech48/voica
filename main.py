import sys
import traceback
from PyQt6.QtWidgets import QApplication
from src.gui import AudioRecorderGUI

def exception_hook(exctype, value, tb):
    print(f"Uncaught exception: {exctype.__name__}: {value}")
    print("Traceback:")
    traceback.print_tb(tb)
    sys.__excepthook__(exctype, value, tb)

def main():
    sys.excepthook = exception_hook
    app = QApplication(sys.argv)
    window = AudioRecorderGUI()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
