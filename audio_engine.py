# amg_app/audio_engine.py
import sounddevice as sd
import numpy as np
from scipy.io.wavfile import write

sd.default.latency = 'low'
sd.default.blocksize = 512

def play(audio, fs):
    audio_float32 = audio.astype(np.float32)
    sd.play(audio_float32, fs)

def get_default_sample_rate():
    try:
        device_info = sd.query_devices(kind='output')
        return int(device_info.get('default_samplerate') or 44100)
    except Exception:
        return 44100

def stop():
    sd.stop()

def save_wav(audio, fs, filepath):
    audio_int16 = np.int16(audio * 32767)
    write(filepath, fs, audio_int16)
