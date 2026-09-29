from __future__ import annotations

from fractions import Fraction
import json
from pathlib import Path
from typing import Any


STRING_NUMBERING = "1=high E, 6=low E"


def load_normalized_song(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalized_to_lesson_v2(
    normalized: dict[str, Any],
    *,
    fps: int = 60,
    name: str | None = None,
    skip_unmapped: bool = False,
) -> dict[str, Any]:
    if normalized.get("schema_version") != "1.0":
        raise ValueError("Expected normalized song schema_version 1.0.")
    if type(fps) is not int or not 1 <= fps <= 240:
        raise ValueError("FPS must be an integer from 1 to 240.")

    timing = normalized["timing"]
    ppq = int(timing["ppq"])
    tempo = _single_effective_tempo(timing.get("tempo_changes", []))
    signature = _single_effective_time_signature(timing.get("time_signature_changes", []))
    lesson_notes = []
    for index, note in enumerate(normalized["notes"], start=1):
        string = note.get("string")
        fret = note.get("fret")
        if string is None or fret is None:
            if skip_unmapped:
                continue
            raise ValueError(f"Normalized note {note.get('id', index)} is missing guitar mapping.")
        duration_ticks = int(note["duration_ticks"])
        lesson_notes.append(
            {
                "id": str(note.get("id") or f"n{index:04d}"),
                "string": int(string),
                "fret": int(fret),
                "start_beat": _fraction_string(Fraction(int(note["start_tick"]), ppq)),
                "duration_beats": _fraction_string(Fraction(duration_ticks, ppq)),
            }
        )

    end_tick = max((int(note["end_tick"]) for note in normalized["notes"]), default=0)
    measure_end_tick = max((int(measure["end_tick"]) for measure in normalized.get("measures", [])), default=0)
    end_beat = Fraction(max(end_tick, measure_end_tick), ppq)

    return {
        "version": 2,
        "name": name or normalized.get("song", {}).get("title") or "Normalized MIDI import",
        "tempo_bpm": _clean_number(float(tempo["bpm"])),
        "fps": fps,
        "time_signature": [int(signature["numerator"]), int(signature["denominator"])],
        "string_numbering": STRING_NUMBERING,
        "end_beat": _fraction_string(end_beat),
        "source": {
            "normalized_schema_version": normalized["schema_version"],
            "source_midi": normalized.get("song", {}).get("source_midi"),
            "source_wav": normalized.get("song", {}).get("source_wav"),
            "audio_offset": normalized.get("audio", {}).get("audio_offset", 0.0),
        },
        "notes": lesson_notes,
    }


def convert_normalized_file_to_lesson_v2(
    input_path: str | Path,
    output_path: str | Path,
    *,
    fps: int = 60,
    name: str | None = None,
) -> dict[str, Any]:
    lesson = normalized_to_lesson_v2(load_normalized_song(input_path), fps=fps, name=name)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lesson, indent=2) + "\n", encoding="utf-8")
    return lesson


def _fraction_string(value: Fraction) -> int | str:
    return value.numerator if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _clean_number(value: float) -> int | float:
    rounded = round(value)
    return rounded if abs(value - rounded) < 0.0001 else value


def _single_effective_tempo(tempo_changes: list[dict[str, Any]]) -> dict[str, Any]:
    if not tempo_changes:
        raise ValueError("Normalized JSON is missing tempo data.")
    tempos = {
        int(change.get("microseconds_per_quarter", round(60_000_000 / float(change["bpm"]))))
        for change in tempo_changes
    }
    if len(tempos) != 1:
        raise ValueError(
            "This MIDI has real tempo changes. The current Blender renderer uses V2 JSON, "
            "which supports one tempo; keep this song as normalized JSON until direct "
            "normalized Blender import is added."
        )
    tempo_us = tempos.pop()
    first = dict(tempo_changes[0])
    first["microseconds_per_quarter"] = tempo_us
    first["bpm"] = 60_000_000 / tempo_us
    return first


def _single_effective_time_signature(
    time_signature_changes: list[dict[str, Any]]
) -> dict[str, Any]:
    if not time_signature_changes:
        raise ValueError("Normalized JSON is missing time-signature data.")
    signatures = {
        (int(change["numerator"]), int(change["denominator"]))
        for change in time_signature_changes
    }
    if len(signatures) != 1:
        raise ValueError(
            "This MIDI has time-signature changes. The current Blender renderer uses V2 JSON, "
            "which supports one time signature; keep this song as normalized JSON until direct "
            "normalized Blender import is added."
        )
    numerator, denominator = signatures.pop()
    first = dict(time_signature_changes[0])
    first["numerator"] = numerator
    first["denominator"] = denominator
    return first
