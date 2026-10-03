"""Fretted instruments as data: what differs between the guitar and the bass is a Fretted spec.

Strings are numbered from the highest-sounding one (string 1). A part stores its instrument name and
tuning (open MIDI pitches of strings 1..n); spec_of finds the spec that draws it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from guitar_video_app.instruments.guitar.schema import GuitarPosition


@dataclass(frozen=True)
class Fretted:
    name: str
    tuning: tuple[int, ...]  # open MIDI pitch of string 1 (highest) .. string n (lowest)
    max_fret: int
    hand_frets: int  # frets the fretting hand covers without moving, one finger per fret
    program: int  # General MIDI program
    numbering: str  # V2 "string_numbering"
    all_bass: bool = False  # every note counts as bass (music.rules.is_bass)

    @property
    def strings(self) -> int:
        return len(self.tuning)

    @property
    def open_strings(self) -> dict[int, int]:
        return {string: pitch for string, pitch in enumerate(self.tuning, start=1)}

    def pitch_of(self, string: int, fret: int) -> int:
        return self.tuning[string - 1] + fret

    def positions(self, pitch: int, max_fret: int | None = None) -> list[GuitarPosition]:
        """Every string and fret that plays pitch, lowest fret first (higher string on ties)."""
        from guitar_video_app.instruments.guitar.schema import GuitarPosition

        top = self.max_fret if max_fret is None else max_fret
        found = [GuitarPosition(string=string, fret=pitch - open_pitch)
                 for string, open_pitch in self.open_strings.items() if 0 <= pitch - open_pitch <= top]
        return sorted(found, key=lambda pos: (pos.fret, -pos.string))


GUITAR_SPEC = Fretted('guitar', (64, 59, 55, 50, 45, 40), 20, 4, 24, '1=high E, 6=low E')
BASS_SPEC = Fretted('bass', (43, 38, 33, 28), 20, 4, 33, '1=high G, 4=low E', all_bass=True)
SPECS = {spec.name: spec for spec in (GUITAR_SPEC, BASS_SPEC)}


def spec_of(part: dict | None) -> Fretted:
    """The spec of a fretted part (a part without an instrument is a guitar part)."""
    name = (part or {}).get('instrument', GUITAR_SPEC.name)
    try:
        return SPECS[name]
    except KeyError:
        raise ValueError(f'{name!r} is not a fretted instrument.') from None


def spec_for_numbering(numbering: str | None) -> Fretted | None:
    return next((spec for spec in SPECS.values() if spec.numbering == numbering), None)
