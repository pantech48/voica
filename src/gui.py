import sys
import traceback
import sounddevice as sd
import warnings
import whisper
import pyperclip
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QLabel, QTextEdit, QComboBox, QHBoxLayout
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QKeyEvent
from src.recorder import AudioRecorder

class AudioRecorderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        print("MainWindow.__init__ started")
        self.setWindowTitle("Audio Recorder and Transcriber")
        self.setGeometry(100, 100, 500, 400)  # Increased window size

        # Initialize log_buffer at the beginning of __init__
        self.log_buffer = []

        # Load the default "base" model at app launch
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=FutureWarning)
                model = whisper.load_model("base", device="cpu")
            self.log_message("Whisper 'base' model loaded.")
        except Exception as e:
            error_msg = f"Error loading Whisper model: {str(e)}\n{traceback.format_exc()}"
            self.log_message(error_msg)
            print(error_msg)
            model = None

        self.recorder = AudioRecorder(model)
        self.recorder.recording_finished.connect(self.on_recording_finished)
        self.recorder.log_message.connect(self.log_message)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Create a horizontal layout for the combo boxes
        combo_layout = QHBoxLayout()

        # Device selection
        device_layout = QVBoxLayout()
        device_label = QLabel("Input Device:")
        self.device_combo = QComboBox(self)
        self.device_combo.setMinimumWidth(200)  # Set minimum width
        device_layout.addWidget(device_label)
        device_layout.addWidget(self.device_combo)
        combo_layout.addLayout(device_layout)

        # Model selection
        model_layout = QVBoxLayout()
        model_label = QLabel("Whisper Model:")
        self.model_combo = QComboBox(self)
        self.model_combo.setMinimumWidth(100)  # Set minimum width
        model_layout.addWidget(model_label)
        model_layout.addWidget(self.model_combo)
        combo_layout.addLayout(model_layout)

        # Hotkey selection
        hotkey_layout = QVBoxLayout()
        self.hotkey_label = QLabel("Hotkey:")
        self.hotkey_combo = QComboBox(self)
        self.hotkey_combo.setMinimumWidth(100)  # Set minimum width
        hotkey_layout.addWidget(self.hotkey_label)
        hotkey_layout.addWidget(self.hotkey_combo)
        combo_layout.addLayout(hotkey_layout)

        main_layout.addLayout(combo_layout)

        # Create all widgets
        self.status_label = QLabel("Ready to record (Press Caps Lock to start/stop)", self)
        self.record_button = QPushButton("Start Recording (Caps Lock)", self)
        self.log_text = QTextEdit(self)

        # Update hotkey selection
        self.hotkey_combo.addItems(["Caps Lock", "F1", "F2", "F3", "F4", "F5"])

        self.key_map = {
            "Caps Lock": Qt.Key.Key_CapsLock,
            "F1": Qt.Key.Key_F1,
            "F2": Qt.Key.Key_F2,
            "F3": Qt.Key.Key_F3,
            "F4": Qt.Key.Key_F4,
            "F5": Qt.Key.Key_F5,
        }

        self.hotkey = Qt.Key.Key_CapsLock  # Default hotkey

        self.hotkey_combo.setCurrentText("Caps Lock")
        self.hotkey_combo.currentIndexChanged.connect(self.on_hotkey_changed)

        # Set up widgets
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.log_text.setReadOnly(True)
        self.log_text.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)

        # Populate model combo box
        self.model_combo.addItems(["tiny", "base", "small", "medium", "large"])
        self.model_combo.setCurrentText("base")

        # Add widgets to main layout
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self.record_button)
        main_layout.addWidget(self.log_text)

        # Connect signals
        self.device_combo.currentIndexChanged.connect(self.on_device_changed)
        self.model_combo.currentIndexChanged.connect(self.on_model_changed)
        self.record_button.clicked.connect(self.toggle_recording)

        # Populate device list
        self.populate_device_list()

        # Set up log timer
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.flush_log)
        self.log_timer.start(100)  # Update log every 100 ms

        self.log_message("Checking audio devices...")
        self.print_audio_devices()

        # Set fonts
        font = QFont()
        font.setPointSize(10)
        self.setFont(font)

        print("MainWindow.__init__ completed")

    def populate_device_list(self):
        devices = sd.query_devices()
        first_input_device = None
        for i, device in enumerate(devices):
            if device['max_input_channels'] > 0:
                self.device_combo.addItem(f"{device['name']} (ID: {i})", i)
                if first_input_device is None:
                    first_input_device = i

        if first_input_device is not None:
            self.device_combo.setCurrentIndex(0)
            self.on_device_changed(0)

    def print_audio_devices(self):
        devices = sd.query_devices()
        self.log_message("\nAvailable audio devices:")
        for i, device in enumerate(devices):
            self.log_message(f"{i}: {device['name']}")
            self.log_message(f"   Input channels: {device['max_input_channels']}")
            self.log_message(f"   Output channels: {device['max_output_channels']}")
            self.log_message(f"   Default samplerate: {device['default_samplerate']}")
        self.log_message(f"\nDefault input device: {sd.default.device[0]}")
        self.log_message(f"Default output device: {sd.default.device[1]}")

    def on_device_changed(self, index):
        device_id = self.device_combo.itemData(index)
        self.recorder.device_id = device_id
        self.recorder.device_info = sd.query_devices(device_id)
        self.log_message(f"Selected device: {self.device_combo.itemText(index)}")
        self.log_message(f"Input channels: {self.recorder.device_info['max_input_channels']}")
        self.log_message(f"Default samplerate: {self.recorder.device_info['default_samplerate']}")

    def toggle_recording(self):
        if not self.recorder.is_recording:
            self.status_label.setText("Loading Whisper model...")
            QApplication.processEvents()  # Force GUI update
            self.recorder.start_recording()
            if self.recorder.is_recording:
                self.record_button.setText("Stop Recording (Caps Lock)")
                self.status_label.setText("Recording... (Press Caps Lock to stop)")
        else:
            self.recorder.stop_recording()
            self.record_button.setText("Start Recording (Caps Lock)")
            self.status_label.setText("Ready to record (Press Caps Lock to start)")

    def on_recording_finished(self, text):
        self.status_label.setText("Transcription completed")
        self.log_message(text)
        pyperclip.copy(text)
        self.log_message("Transcribed text copied to clipboard")

    def log_message(self, message):
        self.log_buffer.append(message)

    def flush_log(self):
        if self.log_buffer:
            self.log_text.append("\n".join(self.log_buffer))
            self.log_buffer.clear()
            self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def update_input_level(self):
        if self.recorder.is_recording:
            level = self.recorder.get_input_level()
            self.status_label.setText(f"Recording... Input level: {level:.2f}")

    def closeEvent(self, event):
        # Clean up resources
        self.recorder.cleanup()
        super().closeEvent(event)

    def on_model_changed(self, index):
        model_name = self.model_combo.currentText()
        self.log_message(f"Selected model: {model_name}")
        try:
            self.recorder.model = whisper.load_model(model_name, device="cpu")
            self.log_message(f"Loaded model: {model_name}")
        except Exception as e:
            error_msg = f"Error loading Whisper model: {str(e)}\n{traceback.format_exc()}"
            self.log_message(error_msg)
            print(error_msg)

    def on_hotkey_changed(self):
        key_name = self.hotkey_combo.currentText()
        self.hotkey = self.key_map.get(key_name, Qt.Key.Key_CapsLock)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == self.hotkey:
            self.toggle_recording()
        else:
            super().keyPressEvent(event)
