import io
import numpy as np
import sounddevice as sd
import tracemalloc
import torch
import traceback
from PyQt6.QtCore import QObject, pyqtSignal

from src.transcription import TranscriptionThread

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
