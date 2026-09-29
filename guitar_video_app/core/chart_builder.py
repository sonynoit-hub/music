from __future__ import annotations

import json
from pathlib import Path

from guitar_video_app.core.fingering_solver import choose_positions
from guitar_video_app.core.note_mapping import midi_note_name
from guitar_video_app.core.schema import ChartEvent, ChartNote, RawNote, dataclass_to_json
from guitar_video_app.core.timing import seconds_to_frame


def group_notes(notes: list[RawNote], tolerance_seconds: float = 0.03) -> list[list[RawNote]]:
    ordered = sorted(notes, key=lambda note: (note.start_time, note.pitch))
    groups: list[list[RawNote]] = []
    for note in ordered:
        if not groups or abs(note.start_time - groups[-1][0].start_time) > tolerance_seconds:
            groups.append([note])
        else:
            groups[-1].append(note)
    return groups


def build_chart(
    notes: list[RawNote],
    fps: float = 30.0,
    start_frame: int = 0,
    tolerance_seconds: float = 0.03,
) -> list[ChartEvent]:
    events: list[ChartEvent] = []
    previous_positions = None
    for group in group_notes(notes, tolerance_seconds=tolerance_seconds):
        positions = choose_positions(group, previous=previous_positions)
        chart_notes = [
            ChartNote(
                pitch=note.pitch,
                name=midi_note_name(note.pitch),
                string=position.string,
                fret=position.fret,
                velocity=note.velocity,
            )
            for note, position in zip(group, positions)
        ]
        start_time = min(note.start_time for note in group)
        end_time = max(note.end_time for note in group)
        start = seconds_to_frame(start_time, fps, start_frame)
        end = max(start + 1, seconds_to_frame(end_time, fps, start_frame))
        events.append(ChartEvent(start_time, end_time, start, end, chart_notes))
        previous_positions = positions
    return events


def write_chart(path: str | Path, events: list[ChartEvent], bpm: float, fps: float) -> None:
    payload = {
        "version": 1,
        "bpm": bpm,
        "fps": fps,
        "tuning": "EADGBE",
        "events": dataclass_to_json(events),
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
