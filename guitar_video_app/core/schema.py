from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RawNote:
    pitch: int
    start_time: float
    end_time: float
    velocity: int = 64
    channel: int | None = None
    track: int | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)


@dataclass(frozen=True)
class TempoEvent:
    time: float
    beat: float
    bpm: float


@dataclass(frozen=True)
class RawSong:
    source: str
    bpm: float
    ticks_per_beat: int
    notes: list[RawNote]
    tempo_events: list[TempoEvent] = field(default_factory=list)
    time_signature: tuple[int, int] | None = None


@dataclass(frozen=True)
class GuitarPosition:
    string: int
    fret: int


@dataclass(frozen=True)
class ChartNote:
    pitch: int
    name: str
    string: int
    fret: int
    velocity: int = 64


@dataclass(frozen=True)
class ChartEvent:
    start_time: float
    end_time: float
    start_frame: int
    end_frame: int
    notes: list[ChartNote]


def dataclass_to_json(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: dataclass_to_json(getattr(value, key)) for key in value.__dataclass_fields__}
    if isinstance(value, (list, tuple)):
        return [dataclass_to_json(item) for item in value]
    return value

