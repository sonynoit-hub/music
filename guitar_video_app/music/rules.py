"""The questions music operations ask about how notes are played, answered by pitch alone.

Retiming, tidying, fitting and reviewing never read instrument fields. When a decision depends on
the instrument (which notes cut each other off, which notes are bass, how an added note is played)
they ask a rules object. PitchRules answers for music with no instrument; an instrument part
subclasses it (instruments.guitar.rules answers from strings and frets). Notes are music notes:
id, pitch, start_beat and duration_beats; operations that need them add start and end in beats.
"""
from __future__ import annotations

import copy

BASS_PITCH = 50
LOW_PITCH = 55


class PitchRules:
    slot_name = 'pitch'

    def slot(self, note: dict):
        """Notes in one slot sound one at a time: a new note there cuts the previous one off,
        and two notes cannot start together in it."""
        return note['pitch']

    def order(self, note: dict):
        """Sort key of notes that start together: highest first."""
        return -note['pitch']

    def is_bass(self, note: dict, notes: list[dict], measure) -> bool:
        """Below BASS_PITCH (D3), or below LOW_PITCH (G3) when held at least a beat or starting a
        measure with no lower note from the same measure still sounding. Notes need 'start' and
        'end' in beats."""
        if note['pitch'] < BASS_PITCH:
            return True
        if note['pitch'] >= LOW_PITCH or (note['end'] - note['start'] < 1 and note['start'] % measure):
            return False
        return not _lower_sounding(note, notes, measure)

    def copy(self, source: dict, note: dict, rules: PitchRules | None = None) -> bool:
        """Play note the way source (a note of rules, default these rules) is played; False when
        it cannot be."""
        return True

    def default(self, note: dict) -> bool:
        """Play note the instrument's usual way; False when it cannot be played."""
        return True

    def place(self, note: dict, notes: list[dict], reference: list[dict]) -> bool:
        """Choose how to play a note added among notes (every note placed so far), preferring how
        reference (the part being followed) plays its pitch; False when it cannot be played."""
        return True

    def clone(self) -> PitchRules:
        return copy.deepcopy(self)

    def empty(self) -> PitchRules:
        """Rules of the same kind that play no notes yet."""
        return type(self)()


def _lower_sounding(note: dict, notes: list[dict], measure) -> bool:
    bar = note['start'] // measure
    return any(other['pitch'] < note['pitch'] and other['start'] // measure == bar
               and other['start'] <= note['start'] < other['end']
               for other in notes if other is not note)
