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


def transcribe_wav_to_midi(wav_path: str | Path, output_dir: str | Path) -> Path:
    """Write Basic Pitch MIDI (and a .onsets.json of onset peaks beside it); return the MIDI path."""
    wav = Path(wav_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    try:
        import basic_pitch  # noqa: F401
    except Exception as exc:
        return _transcribe_with_external_python(wav, out, exc)
    return basic_pitch_runner.run(str(wav), str(out), SETTINGS)


def _transcription_python() -> Path | None:
    root = Path(__file__).resolve().parents[2]
    candidate = root / ".venv-transcribe" / "bin" / "python"
    return candidate if candidate.exists() else None


def _transcribe_with_external_python(
    wav_path: Path, output_dir: Path, import_error: Exception
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
        [str(python), basic_pitch_runner.__file__, str(wav_path), str(output_dir), json.dumps(SETTINGS)],
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
