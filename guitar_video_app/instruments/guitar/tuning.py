from __future__ import annotations

from guitar_video_app.instruments.fretted import GUITAR_SPEC, Fretted
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


def pitch_of(string: int, fret: int, spec: Fretted | None = None) -> int:
    return spec.pitch_of(string, fret) if spec else OPEN_STRING_MIDI[string] + fret


def possible_positions(pitch: int, max_fret: int = MAX_FRET, spec: Fretted | None = None) -> list[GuitarPosition]:
    """Where pitch is played on spec's strings (default the guitar's)."""
    return (spec or GUITAR_SPEC).positions(pitch, max_fret)
