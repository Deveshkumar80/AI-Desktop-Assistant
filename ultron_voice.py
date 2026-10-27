
import os
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from piper import PiperVoice
from pedalboard import (
    Pedalboard,
    PitchShift,
    HighpassFilter,
    LowpassFilter,
    Compressor,
    Distortion,
    Reverb,
    Limiter,
)

BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "models" / "en_US-ryan-medium.onnx"

PITCH_SEMITONES = -2.0
SPEECH_RATE = 0.92

_voice = None
_lock = threading.Lock()


def load_voice():
    global _voice

    if _voice is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"Voice model missing: {MODEL_PATH}")

        _voice = PiperVoice.load(str(MODEL_PATH))

    return _voice


def speak(text):
    if not isinstance(text, str) or not text.strip():
        return

    with _lock:
        voice = load_voice()
        wav_path = None

        try:
            fd, filename = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            wav_path = Path(filename)

            with wave.open(str(wav_path), "wb") as wav_file:
                voice.synthesize_wav(text.strip(), wav_file)

            audio, sample_rate = sf.read(
                str(wav_path),
                dtype="float32",
                always_2d=True,
            )

            if audio.size == 0:
                return

            # Slow playback slightly while lowering the pitch.
            target_rate = max(1, int(sample_rate * SPEECH_RATE))
            effects = Pedalboard([
                PitchShift(semitones=PITCH_SEMITONES),
                HighpassFilter(cutoff_frequency_hz=65.0),
                LowpassFilter(cutoff_frequency_hz=8500.0),
                Compressor(threshold_db=-18, ratio=2.5),
                Distortion(drive_db=1.0),
                Reverb(
                    room_size=0.18,
                    damping=0.6,
                    wet_level=0.08,
                    dry_level=0.92,
                ),
                Limiter(threshold_db=-1.0),
            ])

            processed = effects(audio.T, sample_rate).T

            peak = np.max(np.abs(processed))
            if peak > 0.98:
                processed *= 0.98 / peak

            sd.play(
                processed.astype(np.float32),
                samplerate=target_rate,
                blocking=True,
            )

        finally:
            if wav_path is not None:
                wav_path.unlink(missing_ok=True)


if __name__ == "__main__":
    print("Loading ULTRON-inspired voice...")

    speak(
        "System online. All systems operational. "
        "I am your personal artificial intelligence assistant. "
        "Awaiting your command."
    )

    print("Voice test completed.")
