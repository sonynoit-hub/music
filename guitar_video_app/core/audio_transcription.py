from __future__ import annotations

from pathlib import Path
import subprocess


class TranscriptionUnavailable(RuntimeError):
    pass


def transcribe_wav_to_midi(wav_path: str | Path, output_dir: str | Path) -> Path:
    wav = Path(wav_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    try:
        from basic_pitch.inference import ICASSP_2022_MODEL_PATH, predict_and_save
    except Exception as exc:
        return _transcribe_with_external_python(wav, out, exc)

    predict_and_save(
        [str(wav)],
        str(out),
        save_midi=True,
        sonify_midi=False,
        save_model_outputs=False,
        save_notes=False,
        model_or_model_path=ICASSP_2022_MODEL_PATH,
    )
    midi_path = out / f"{wav.stem}_basic_pitch.mid"
    if not midi_path.exists():
        candidates = sorted(out.glob("*.mid"))
        if not candidates:
            raise RuntimeError("Basic Pitch finished without creating a MIDI file.")
        midi_path = candidates[-1]
    return midi_path


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

    code = """
from pathlib import Path
import sys
from basic_pitch.inference import ICASSP_2022_MODEL_PATH, predict_and_save

wav = Path(sys.argv[1])
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
predict_and_save(
    [str(wav)],
    str(out),
    save_midi=True,
    sonify_midi=False,
    save_model_outputs=False,
    save_notes=False,
    model_or_model_path=ICASSP_2022_MODEL_PATH,
)
midi = out / f"{wav.stem}_basic_pitch.mid"
if not midi.exists():
    candidates = sorted(out.glob("*.mid"))
    if not candidates:
        raise RuntimeError("Basic Pitch finished without creating a MIDI file.")
    midi = candidates[-1]
print(midi)
"""
    result = subprocess.run(
        [str(python), "-c", code, str(wav_path), str(output_dir)],
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
