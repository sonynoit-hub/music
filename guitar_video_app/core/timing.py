from __future__ import annotations


def seconds_to_frame(seconds: float, fps: float, start_frame: int = 0) -> int:
    return int(round(start_frame + seconds * fps))


def beat_to_seconds(beat: float, bpm: float) -> float:
    return beat * 60.0 / bpm


def beat_to_frame(beat: float, bpm: float, fps: float, start_frame: int = 0) -> int:
    return seconds_to_frame(beat_to_seconds(beat, bpm), fps, start_frame)

