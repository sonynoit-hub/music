from __future__ import annotations

from guitar_video_app.instruments.guitar.schema import GuitarPosition
from guitar_video_app.music.pitch import NOTE_NAMES, midi_note_name  # noqa: F401


STANDARD_TUNING = {
    6: 40,  # E2
    5: 45,  # A2
    4: 50,  # D3
    3: 55,  # G3
    2: 59,  # B3
    1: 64,  # E4
}
OPEN_STRING_MIDI = {string: STANDARD_TUNING[string] for string in range(1, 7)}
TUNING = [OPEN_STRING_MIDI[string] for string in range(1, 7)]
MAX_FRET = 20


def pitch_of(string: int, fret: int) -> int:
    return OPEN_STRING_MIDI[string] + fret


def possible_positions(pitch: int, max_fret: int = MAX_FRET) -> list[GuitarPosition]:
    positions: list[GuitarPosition] = []
    for string, open_pitch in STANDARD_TUNING.items():
        fret = pitch - open_pitch
        if 0 <= fret <= max_fret:
            positions.append(GuitarPosition(string=string, fret=fret))
    return sorted(positions, key=lambda pos: (pos.fret, -pos.string))
