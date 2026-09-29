from __future__ import annotations

from itertools import product

from guitar_video_app.core.note_mapping import possible_positions
from guitar_video_app.core.schema import GuitarPosition, RawNote


def choose_positions(
    notes: list[RawNote],
    previous: list[GuitarPosition] | None = None,
    max_fret_span: int = 5,
    max_fret: int = 20,
) -> list[GuitarPosition]:
    candidates = [possible_positions(note.pitch, max_fret=max_fret) for note in notes]
    if any(not item for item in candidates):
        missing = [note.pitch for note, item in zip(notes, candidates) if not item]
        raise ValueError(f"Unplayable note(s) for standard guitar tuning: {missing}")

    best: tuple[float, tuple[GuitarPosition, ...]] | None = None
    for combo in product(*candidates):
        strings = [pos.string for pos in combo]
        if len(strings) != len(set(strings)):
            continue
        fretted = [pos.fret for pos in combo if pos.fret > 0]
        if fretted and max(fretted) - min(fretted) > max_fret_span:
            continue
        score = _score_combo(combo, previous)
        if best is None or score < best[0]:
            best = (score, combo)

    if best is None:
        raise ValueError("No playable fingering found within span/string constraints")
    return list(best[1])


def _score_combo(combo: tuple[GuitarPosition, ...], previous: list[GuitarPosition] | None) -> float:
    frets = [pos.fret for pos in combo]
    open_strings = sum(1 for fret in frets if fret == 0)
    high_fret_cost = sum(frets) * 0.8
    span_cost = (max(frets) - min(frets)) * 2.0 if len(frets) > 1 else 0.0
    open_string_cost = open_strings * 0.25

    movement_cost = 0.0
    if previous:
        prev_fretted = [pos.fret for pos in previous if pos.fret > 0]
        curr_fretted = [pos.fret for pos in combo if pos.fret > 0]
        if prev_fretted and curr_fretted:
            movement_cost = abs(_center(prev_fretted) - _center(curr_fretted)) * 3.0

    return high_fret_cost + span_cost + open_string_cost + movement_cost


def _center(values: list[int]) -> float:
    return sum(values) / len(values)
