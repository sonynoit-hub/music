"""Normalized song JSON (MIDI facts in ticks and seconds) to a lesson's music layer."""
from __future__ import annotations

from fractions import Fraction
import json
from pathlib import Path
from typing import Any, Callable

from guitar_video_app.music.lesson import VERSION


def load_normalized_song(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def note_id(note: dict[str, Any], index: int) -> str:
    """The lesson id of the normalized note at 1-based index."""
    return str(note.get("id") or f"n{index:04d}")


def normalized_to_lesson(
    normalized: dict[str, Any],
    *,
    fps: int = 60,
    name: str | None = None,
    keep: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """A V3 lesson with no instrument part from a normalized song; keep(note) leaves notes out."""
    if normalized.get("schema_version") != "1.0":
        raise ValueError("Expected normalized song schema_version 1.0.")
    if type(fps) is not int or not 1 <= fps <= 240:
        raise ValueError("FPS must be an integer from 1 to 240.")

    timing = normalized["timing"]
    ppq = int(timing["ppq"])
    tempos = _tempo_points(timing.get("tempo_changes", []), ppq)
    signature = _single_effective_time_signature(timing.get("time_signature_changes", []))
    notes = []
    for index, note in enumerate(normalized["notes"], start=1):
        if keep and not keep(note):
            continue
        duration_ticks = int(note["duration_ticks"])
        notes.append(
            {
                "id": note_id(note, index),
                "pitch": int(note["pitch"]),
                "start_beat": _fraction_string(Fraction(int(note["start_tick"]), ppq)),
                "duration_beats": _fraction_string(Fraction(duration_ticks, ppq)),
            }
        )

    end_tick = max((int(note["end_tick"]) for note in normalized["notes"]), default=0)
    measure_end_tick = max((int(measure["end_tick"]) for measure in normalized.get("measures", [])), default=0)
    end_beat = Fraction(max(end_tick, measure_end_tick), ppq)

    music = {
        "tempo_bpm": _clean_number(float(tempos[0][1])),
        "time_signature": [int(signature["numerator"]), int(signature["denominator"])],
        "end_beat": _fraction_string(end_beat),
        "source": {
            "normalized_schema_version": normalized["schema_version"],
            "source_midi": normalized.get("song", {}).get("source_midi"),
            "source_wav": normalized.get("song", {}).get("source_wav"),
            "audio_offset": normalized.get("audio", {}).get("audio_offset", 0.0),
        },
        "notes": notes,
    }
    if normalized.get("pedal_events"):
        music["pedal_events"] = [
            {
                "id": event.get("id", f"p{index:04d}"),
                "type": event.get("type", "sustain"),
                "start_beat": _fraction_string(Fraction(int(event["start_tick"]), ppq)),
                "duration_beats": _fraction_string(
                    Fraction(int(event["duration_ticks"]), ppq)
                    if "duration_ticks" in event
                    else Fraction(int(event["end_tick"]) - int(event["start_tick"]), ppq)
                ),
                "value": int(event.get("value", 127)),
                **{key: event[key] for key in ("channel", "track_id") if key in event},
            }
            for index, event in enumerate(normalized["pedal_events"], start=1)
        ]
    if len(tempos) > 1:
        music["tempo_changes"] = [dict(beat=_fraction_string(position), bpm=_clean_number(float(bpm)))
                                  for position, bpm in tempos[1:]]
    return {
        "version": VERSION,
        "name": name or normalized.get("song", {}).get("title") or "Normalized MIDI import",
        "fps": fps,
        "music": music,
        "parts": {},
    }


def _fraction_string(value: Fraction) -> int | str:
    return value.numerator if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _clean_number(value: float) -> int | float:
    rounded = round(value)
    return rounded if abs(value - rounded) < 0.0001 else value


def _tempo_points(tempo_changes: list[dict[str, Any]], ppq: int) -> list[tuple[Fraction, Fraction]]:
    """(beat, bpm) for each real tempo change; MIDI plays 120 BPM before the first one."""
    if not tempo_changes:
        raise ValueError("Normalized JSON is missing tempo data.")
    points: list[tuple[Fraction, Fraction]] = [(Fraction(0), Fraction(120))]
    for change in sorted(tempo_changes, key=lambda c: int(c.get("tick", 0))):
        tempo_us = int(change["microseconds_per_quarter"] if "microseconds_per_quarter" in change
                       else round(60_000_000 / float(change["bpm"])))
        position, bpm = Fraction(int(change.get("tick", 0)), ppq), Fraction(60_000_000, tempo_us)
        if points[-1][0] == position:
            points[-1] = (position, bpm)
        elif points[-1][1] != bpm:
            points.append((position, bpm))
    return [point for index, point in enumerate(points) if not index or point[1] != points[index - 1][1]]


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
            "This MIDI has time-signature changes. Lessons support one time signature; keep this "
            "song as normalized JSON until time-signature changes are supported."
        )
    numerator, denominator = signatures.pop()
    first = dict(time_signature_changes[0])
    first["numerator"] = numerator
    first["denominator"] = denominator
    return first
