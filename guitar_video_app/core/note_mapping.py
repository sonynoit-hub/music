from __future__ import annotations

from guitar_video_app.core.schema import GuitarPosition


STANDARD_TUNING = {
    6: 40,  # E2
    5: 45,  # A2
    4: 50,  # D3
    3: 55,  # G3
    2: 59,  # B3
    1: 64,  # E4
}

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def midi_note_name(pitch: int) -> str:
    octave = pitch // 12 - 1
    return f"{NOTE_NAMES[pitch % 12]}{octave}"


def possible_positions(pitch: int, max_fret: int = 20) -> list[GuitarPosition]:
    positions: list[GuitarPosition] = []
    for string, open_pitch in STANDARD_TUNING.items():
        fret = pitch - open_pitch
        if 0 <= fret <= max_fret:
            positions.append(GuitarPosition(string=string, fret=fret))
    return sorted(positions, key=lambda pos: (pos.fret, -pos.string))
