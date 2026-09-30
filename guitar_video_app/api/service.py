from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from guitar_video_app.instruments.guitar.chart_builder import build_chart, write_chart
from guitar_video_app.music.midi_to_json import midi_to_raw_song, write_raw_json
from guitar_video_app.music.schema import RawNote


@dataclass(frozen=True)
class BuildResult:
    raw_song_path: Path
    chart_path: Path
    event_count: int
    bpm: float
    fps: float


def build_from_midi(
    midi_path: str | Path,
    output_dir: str | Path,
    fps: float = 30.0,
    raw_name: str = "raw_song.json",
    chart_name: str = "guitar_chart.json",
) -> BuildResult:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    raw_path = output / raw_name
    chart_path = output / chart_name

    song = midi_to_raw_song(midi_path)
    write_raw_json(midi_path, raw_path)
    events = build_chart(song.notes, fps=fps)
    write_chart(chart_path, events, bpm=song.bpm, fps=fps)

    return BuildResult(raw_path, chart_path, len(events), song.bpm, fps)


def build_chart_from_raw_json(
    raw_json_path: str | Path,
    output_path: str | Path,
    fps: float = 30.0,
) -> BuildResult:
    raw_path = Path(raw_json_path)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    notes = [RawNote(**note) for note in payload["notes"]]
    events = build_chart(notes, fps=fps)
    write_chart(output_path, events, bpm=float(payload.get("bpm", 120)), fps=fps)
    return BuildResult(raw_path, Path(output_path), len(events), float(payload.get("bpm", 120)), fps)

