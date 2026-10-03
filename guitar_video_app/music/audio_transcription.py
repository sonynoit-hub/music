from __future__ import annotations

import json
from pathlib import Path
import subprocess

from guitar_video_app.music import basic_pitch_runner


class TranscriptionUnavailable(RuntimeError):
    pass


# Tuned on a fingerstyle guitar recording against its published tab: stricter onsets and
# no melodia note extension roughly halve the false notes while keeping about 90% of real notes.
SETTINGS = dict(onset_threshold=0.6, frame_threshold=0.4, melodia_trick=False)


def midi_hz(pitch: float) -> float:
    return 440.0 * 2 ** ((pitch - 69) / 12)


def band_settings(low: int | None = None, high: int | None = None, onset_threshold: float | None = None,
                  frame_threshold: float | None = None) -> dict:
    """SETTINGS limited to MIDI pitches low..high (a quarter tone of margin each side), with the
    given thresholds instead of the defaults."""
    settings = dict(SETTINGS)
    if low is not None:
        settings['minimum_frequency'] = round(midi_hz(low - 0.5), 2)
    if high is not None:
        settings['maximum_frequency'] = round(midi_hz(high + 0.5), 2)
    if onset_threshold is not None:
        settings['onset_threshold'] = onset_threshold
    if frame_threshold is not None:
        settings['frame_threshold'] = frame_threshold
    return settings


def settings_path(midi_path: str | Path) -> Path:
    """Where the Basic Pitch settings a MIDI file was made with are recorded."""
    return Path(midi_path).with_suffix('.settings.json')


def made_with(midi_path: str | Path, settings: dict) -> bool:
    """True when midi_path was transcribed with these settings."""
    path = settings_path(midi_path)
    return path.exists() and json.loads(path.read_text(encoding='utf-8')) == settings


def transcribe_wav_to_midi(wav_path: str | Path, output_dir: str | Path, low: int | None = None,
                           high: int | None = None, onset_threshold: float | None = None,
                           frame_threshold: float | None = None) -> Path:
    """Write Basic Pitch MIDI (and a .onsets.json of onset peaks and a .settings.json beside it);
    return the MIDI path. low and high (MIDI pitches) limit what Basic Pitch listens for, e.g. a
    bass's range in a full mix; the thresholds replace the defaults (band_settings)."""
    wav = Path(wav_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    settings = band_settings(low, high, onset_threshold, frame_threshold)

    try:
        import basic_pitch  # noqa: F401
    except Exception as exc:
        midi_path = _transcribe_with_external_python(wav, out, exc, settings)
    else:
        midi_path = basic_pitch_runner.run(str(wav), str(out), settings)
    settings_path(midi_path).write_text(json.dumps(settings), encoding='utf-8')
    return midi_path


def _transcription_python() -> Path | None:
    root = Path(__file__).resolve().parents[2]
    candidate = root / ".venv-transcribe" / "bin" / "python"
    return candidate if candidate.exists() else None


def _transcribe_with_external_python(
    wav_path: Path, output_dir: Path, import_error: Exception, settings: dict = SETTINGS
) -> Path:
    python = _transcription_python()
    if not python:
        raise TranscriptionUnavailable(
            "Basic Pitch is not installed. Install it locally with "
            "`uv venv --python /opt/homebrew/bin/python3.11 .venv-transcribe` "
            "then `uv pip install --python .venv-transcribe/bin/python basic-pitch`, "
            "then try again."
        ) from import_error

    result = subprocess.run(
        [str(python), basic_pitch_runner.__file__, str(wav_path), str(output_dir), json.dumps(settings)],
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    if result.returncode:
        details = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Basic Pitch failed: {details}")
    midi_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    midi_path = Path(midi_line)
    if not midi_path.exists():
        raise RuntimeError("Basic Pitch finished without creating a MIDI file.")
    return midi_path
