"""Separate the bass of one recording with Demucs and track its pitch with pYIN.

Standalone (only Demucs and librosa imports) so it can run inside a separate Python environment:
python stem_runner.py WAV STEM_WAV LOW HIGH
Writes STEM_WAV and, beside it, a .pitch.json: frame times (seconds) and pitches (fractional MIDI,
null where no pitch is heard) searched between the MIDI pitches LOW and HIGH. Exits with
MISSING_PACKAGE when Demucs or librosa is not installed.
"""
from pathlib import Path
import json
import shutil
import sys
import tempfile

MODEL = 'htdemucs_ft'
SAMPLE_RATE = 22050
FRAME_LENGTH = 4096
HOP_LENGTH = 256
MISSING_PACKAGE = 3


def separate(wav: str, stem: str) -> None:
    import demucs.separate

    with tempfile.TemporaryDirectory() as scratch:
        demucs.separate.main(['-n', MODEL, '--two-stems', 'bass', '-o', scratch, wav])
        shutil.move(str(Path(scratch) / MODEL / Path(wav).stem / 'bass.wav'), stem)


def track_pitch(stem: str, low: int, high: int) -> Path:
    import librosa
    import numpy as np

    audio, rate = librosa.load(stem, sr=SAMPLE_RATE, mono=True)
    f0, voiced, _ = librosa.pyin(audio, fmin=librosa.midi_to_hz(low - 1), fmax=librosa.midi_to_hz(high + 1),
                                 sr=rate, frame_length=FRAME_LENGTH, hop_length=HOP_LENGTH)
    times = librosa.times_like(f0, sr=rate, hop_length=HOP_LENGTH)
    midi = [round(float(librosa.hz_to_midi(f)), 2) if v and np.isfinite(f) else None for f, v in zip(f0, voiced)]
    path = Path(stem).with_suffix('.pitch.json')
    path.write_text(json.dumps(dict(times=[round(float(t), 4) for t in times], midi=midi)), encoding='utf-8')
    return path


if __name__ == '__main__':
    try:
        import demucs  # noqa: F401
        import librosa  # noqa: F401
    except ImportError as exc:
        print(f'{exc.name} is not installed', file=sys.stderr)
        sys.exit(MISSING_PACKAGE)
    wav, stem, low, high = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    separate(wav, stem)
    print(track_pitch(stem, low, high))
