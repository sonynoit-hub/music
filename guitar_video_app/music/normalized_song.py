from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class TempoChange:
    tick: int
    seconds: float
    bpm: float
    microseconds_per_quarter: int


@dataclass(frozen=True)
class TimeSignatureChange:
    tick: int
    seconds: float
    numerator: int
    denominator: int


@dataclass(frozen=True)
class NormalizedTrack:
    id: int
    name: str
    channel: int | None = None
    instrument: int | None = None


@dataclass(frozen=True)
class NormalizedNote:
    id: str
    track_id: int
    pitch: int
    start_tick: int
    end_tick: int
    duration_ticks: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    start_beat: float
    end_beat: float
    measure: int
    velocity: int
    channel: int | None
    string: int | None
    fret: int | None


@dataclass(frozen=True)
class NormalizedMeasure:
    number: int
    start_tick: int
    end_tick: int
    start_seconds: float
    end_seconds: float
    time_signature: str


@dataclass(frozen=True)
class NormalizedBeat:
    index: int
    measure: int
    beat_in_measure: int
    tick: int
    seconds: float


@dataclass(frozen=True)
class NormalizedSong:
    schema_version: str
    song: dict[str, Any]
    timing: dict[str, Any]
    tracks: list[NormalizedTrack]
    notes: list[NormalizedNote]
    measures: list[NormalizedMeasure]
    beats: list[NormalizedBeat]
    audio: dict[str, Any]
    pedal_events: list[dict[str, Any]] = field(default_factory=list)
    guitar: dict[str, Any] = field(default_factory=dict)


def normalized_song_to_dict(song: NormalizedSong) -> dict[str, Any]:
    return asdict(song)


def write_normalized_song(song: NormalizedSong, path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(normalized_song_to_dict(song), indent=2) + "\n",
        encoding="utf-8",
    )
