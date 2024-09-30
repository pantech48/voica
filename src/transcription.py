import traceback
from PyQt6.QtCore import QThread, pyqtSignal

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
