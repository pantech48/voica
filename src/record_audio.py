import sys
import threading
import sounddevice as sd
import soundfile as sf
import numpy as np
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QLabel, QTextEdit, QComboBox
from PyQt6.QtCore import QObject, pyqtSignal, Qt, QTimer, QThread, QEventLoop
from PyQt6.QtGui import QShortcut, QKeySequence, QKeyEvent
import speech_recognition as sr
import pyperclip
import io
import whisper
import torch
import traceback
from contextlib import contextmanager
import warnings
import tracemalloc
import objc
from Foundation import NSObject
from AppKit import NSEvent, NSKeyDownMask
from PyObjCTools.AppHelper import callAfter

class HotkeyListener(NSObject):
    def initWithKeyCode_(self, key_code):
        self = objc.super(HotkeyListener, self).init()
        if self is None:
            return None
        self.is_listening = True
        self.callback = None
        self.key_code = key_code
        self.event_monitor = None
        self.local_event_monitor = None
        return self

    def start_listening(self):
        def setup_monitors():
            mask = NSKeyDownMask
            self.event_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, self.handleEvent_)
            self.local_event_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, self.handleEvent_)

        callAfter(setup_monitors)

    def handleEvent_(self, event):
        if not self.is_listening:
            return event
        if event.keyCode() == self.key_code:
            if self.callback:
                callAfter(self.callback)
        return event

    def stop_listening(self):
        self.is_listening = False
        if self.event_monitor:
            NSEvent.removeMonitor_(self.event_monitor)
        if self.local_event_monitor:
            NSEvent.removeMonitor_(self.local_event_monitor)

    def set_callback(self, callback):
        self.callback = callback

    def update_key_code(self, key_code):
        self.key_code = key_code

class TranscriptionThread(QThread):
    transcription_completed = pyqtSignal(str)
    log_message = pyqtSignal(str)

    def __init__(self, audio_data, model):
        super().__init__()
        self.audio_data = audio_data
        self.model = model

    def run(self):
        try:
            result = self.model.transcribe(self.audio_data, fp16=False)
            transcribed_text = result['text']
            self.transcription_completed.emit(transcribed_text)
        except Exception as e:
            error_msg = f"Error in transcription thread: {str(e)}\n{traceback.format_exc()}"
            self.log_message.emit(error_msg)
            print(error_msg)

class AudioRecorder(QObject):
    recording_finished = pyqtSignal(str)
    log_message = pyqtSignal(str)

    def __init__(self, model):
        super().__init__()
        tracemalloc.start()
        self.is_recording = False
        self.audio_buffer = io.BytesIO()
        self.device_id = None
        self.device_info = None
        self.model = model
        
        current, peak = tracemalloc.get_traced_memory()
        self.log_message.emit(f"Current memory usage: {current / 10**6}MB; Peak: {peak / 10**6}MB")

    def start_recording(self):
        if self.device_id is None or self.device_info is None:
            self.log_message.emit("Please select an input device.")
            return

        self.is_recording = True
        self.audio_buffer = io.BytesIO()

        channels = 1  # Use mono channel
        samplerate = 16000  # Use 16kHz sample rate

        def callback(indata, frames, time, status):
            if status:
                self.log_message.emit(str(status))
            # Write raw audio data to buffer
            self.audio_buffer.write(indata.tobytes())

        try:
            self.stream = sd.InputStream(device=self.device_id, channels=channels, samplerate=samplerate, callback=callback)
            self.stream.start()
            self.log_message.emit(f"Recording started with {channels} channel(s) at {samplerate} Hz...")
        except Exception as e:
            self.log_message.emit(f"Error starting recording: {str(e)}")
            self.is_recording = False

    def stop_recording(self):
        if hasattr(self, 'stream'):
            self.stream.stop()
            self.stream.close()
        
        self.is_recording = False
        self.log_message.emit("Recording stopped.")
        
        self.transcribe_audio()

    def transcribe_audio(self):
        if self.audio_buffer.getbuffer().nbytes > 0:
            try:
                self.audio_buffer.seek(0)
                audio_bytes = self.audio_buffer.read()
                audio_data = np.frombuffer(audio_bytes, dtype=np.float32)

                max_value = np.max(np.abs(audio_data))
                if max_value > 0:
                    audio_data = audio_data / max_value
                else:
                    self.log_message.emit("Audio data is silent.")
                    return  # Stop processing since there's no audible data

                # Start transcription in a new thread
                self.transcription_thread = TranscriptionThread(audio_data, self.model)
                self.transcription_thread.transcription_completed.connect(self.recording_finished.emit)
                self.transcription_thread.log_message.connect(self.log_message.emit)
                self.transcription_thread.start()

                current, peak = tracemalloc.get_traced_memory()
                self.log_message.emit(f"Current memory usage: {current / 10**6}MB; Peak: {peak / 10**6}MB")

            except Exception as e:
                error_msg = f"Error preparing audio for transcription: {str(e)}\n{traceback.format_exc()}"
                self.log_message.emit(error_msg)
                print(error_msg)
        else:
            self.log_message.emit("No audio data to transcribe.")

    def get_input_level(self):
        if self.audio_buffer.getbuffer().nbytes > 0:
            self.audio_buffer.seek(-4000, 2)  # Move to last 1000 samples (assuming float32)
            latest_data = np.frombuffer(self.audio_buffer.read(), dtype=np.float32)
            return np.abs(latest_data).mean()
        return 0

    def cleanup(self):
        del self.model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        tracemalloc.stop()

class AudioRecorderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        print("MainWindow.__init__ started")
        self.setWindowTitle("Audio Recorder and Transcriber")
        self.setGeometry(100, 100, 400, 300)

        # Initialize log_buffer at the beginning of __init__
        self.log_buffer = []

        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=FutureWarning)
                model = whisper.load_model("tiny", device="cpu")
            self.log_message("Whisper model loaded.")
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
        layout = QVBoxLayout(central_widget)

        # Create all widgets
        self.device_combo = QComboBox(self)
        self.model_combo = QComboBox(self)
        self.status_label = QLabel("Ready to record (Press Caps Lock to start/stop)", self)
        self.record_button = QPushButton("Start Recording (Caps Lock)", self)
        self.log_text = QTextEdit(self)

        # Set up widgets
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.log_text.setReadOnly(True)
        self.log_text.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)

        # Populate model combo box
        self.model_combo.addItems(["tiny", "base", "small", "medium", "large"])

        # Add widgets to layout
        layout.addWidget(self.device_combo)
        layout.addWidget(self.model_combo)
        layout.addWidget(self.status_label)
        layout.addWidget(self.record_button)
        layout.addWidget(self.log_text)

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

        # Set up global hotkey listener
        self.hotkey_listener = HotkeyListener.alloc().initWithKeyCode_(57)  # 57 is the key code for Caps Lock
        self.hotkey_listener.set_callback(self.hotkey_callback)
        self.hotkey_listener.start_listening()
        print("MainWindow.__init__ completed")

    def hotkey_callback(self):
        # This method will be called when Caps Lock is pressed
        self.toggle_recording()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_CapsLock:
            self.toggle_recording()
        else:
            super().keyPressEvent(event)

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
        self.hotkey_listener.stop_listening()
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

def on_f5_pressed():
    print("F5 key pressed!")
    # Add your action here

listener = HotkeyListener.alloc().initWithKeyCode_(96)  # 96 is the key code for F5
listener.set_callback(on_f5_pressed)
listener.start_listening()

# Your main program logic here
# When you're done, call listener.stop_listening()

if __name__ == "__main__":
    print("Application starting")
    app = QApplication(sys.argv)
    main_window = AudioRecorderGUI()
    print("MainWindow instance created")
    main_window.show()
    print("MainWindow shown")

    # Create a timer to process PyObjC events
    objc_timer = QTimer()
    objc_timer.timeout.connect(lambda: None)
    objc_timer.start(100)  # Process PyObjC events every 100ms

    sys.exit(app.exec())