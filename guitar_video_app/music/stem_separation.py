"""The bass of a full-band recording, separated by Demucs, with its pitch tracked by pYIN (stem_runner)."""
from __future__ import annotations

from pathlib import Path
import subprocess

from guitar_video_app.music import stem_runner
from guitar_video_app.music.audio_transcription import TranscriptionUnavailable, _transcription_python

SEPARATION_TIMEOUT_SECONDS = 1800


def bass_stem_paths(wav_path: str | Path, output_dir: str | Path) -> tuple[Path, Path]:
    """Where the bass stem of wav_path and its pitch track are kept in output_dir."""
    stem = Path(output_dir) / f'{Path(wav_path).stem}_bass.wav'
    return stem, stem.with_suffix('.pitch.json')


def separated_bass(wav_path: str | Path, output_dir: str | Path, low: int, high: int) -> tuple[Path, Path]:
    """The bass stem WAV and its pitch track (pitches searched within low..high), separating the first
    time; later calls reuse the files."""
    stem, track = bass_stem_paths(wav_path, output_dir)
    if stem.exists() and track.exists():
        return stem, track
    python = _transcription_python()
    install = ('Install it locally with `uv pip install --python .venv-transcribe/bin/python demucs librosa` '
               'and try again.')
    if not python:
        raise TranscriptionUnavailable(f'Extracting the bass needs the .venv-transcribe environment. {install}')
    stem.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(python), stem_runner.__file__, str(wav_path), str(stem), str(low), str(high)],
        text=True, capture_output=True, check=False, timeout=SEPARATION_TIMEOUT_SECONDS,
    )
    if result.returncode == stem_runner.MISSING_PACKAGE:
        raise TranscriptionUnavailable(f'Extracting the bass needs Demucs and librosa. {install}')
    if result.returncode or not (stem.exists() and track.exists()):
        details = (result.stderr or result.stdout).strip().splitlines()[-1:] or ['no output']
        raise RuntimeError(f'Bass separation failed: {details[0]}')
    return stem, track
