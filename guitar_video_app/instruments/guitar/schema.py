from __future__ import annotations

from dataclasses import dataclass


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
