"""A guitar (or bass) part's answers to the questions music operations ask (see music.rules).

The part stores positions: {note id: {"string": 1-6, "fret": 0-20}}, strings numbered from the
highest (the high E on a guitar, 1-4 from the G on a bass). A string sounds one note at a time,
so the string is the slot. The part's instrument picks its Fretted spec (instruments.fretted).
"""
from __future__ import annotations

import copy

from guitar_video_app.music.rules import PitchRules, _lower_sounding
from guitar_video_app.music.tempo import beat
from guitar_video_app.instruments.fretted import spec_of

TAB_STRING_BEATS = 8
HAND_BEATS = 2


class GuitarRules(PitchRules):
    slot_name = 'string'

    def __init__(self, part: dict | None = None):
        from guitar_video_app.instruments.guitar.view import new_part

        self.part = part if part is not None else new_part()
        self.spec = spec_of(self.part)
        self.positions = self.part.setdefault('positions', {})

    def position(self, note: dict) -> dict:
        try:
            return self.positions[note['id']]
        except KeyError:
            raise ValueError(f"Note {note['id']} has no string and fret.") from None

    def slot(self, note):
        return self.position(note)['string']

    def order(self, note):
        return self.position(note)['string']

    def is_bass(self, note, notes, measure):
        """Every note of a bass (spec.all_bass). On the guitar: strings 5-6, or a string-4 note that
        is held at least a beat or starts a measure, with no lower note from the same measure still
        sounding. The dashboard notation uses the same rule."""
        if self.spec.all_bass:
            return True
        string = self.slot(note)
        if string >= 5:
            return True
        if string < 4 or (note['end'] - note['start'] < 1 and note['start'] % measure):
            return False
        return not _lower_sounding(note, notes, measure)

    def copy(self, source, note, rules=None):
        position = (rules or self).positions.get(source['id'])
        if position is None:
            return False
        self.positions[note['id']] = dict(position)
        return True

    def default(self, note):
        """The lowest fret that plays the pitch, on the highest such string."""
        options = self.spec.positions(note['pitch'])
        if not options:
            return False
        self.positions[note['id']] = dict(string=options[0].string, fret=options[0].fret)
        return True

    def place(self, note, notes, reference):
        """A free string at that beat: the string reference uses for that pitch within
        TAB_STRING_BEATS, else the fret nearest the hand (the median fret played within HAND_BEATS),
        keeping guitar bass pitches (up to the open D) on strings 4-6."""
        start, pitch = beat(note['start_beat']), note['pitch']
        busy = {self.slot(n) for n in notes if beat(n['start_beat']) == start}
        options = [p for p in self.spec.positions(pitch) if p.string not in busy]
        if not options:
            return False
        same = sorted((abs(beat(n['start_beat']) - start), self.slot(n)) for n in reference if n['pitch'] == pitch)
        like = [p for distance, string in same if distance <= TAB_STRING_BEATS for p in options if p.string == string]
        frets = sorted(self.position(n)['fret'] for n in notes
                       if self.position(n)['fret'] and abs(beat(n['start_beat']) - start) <= HAND_BEATS)
        hand = frets[len(frets) // 2] if frets else 0
        low = self.spec.strings - 2
        bass = pitch <= self.spec.open_strings[low]
        side = (lambda p: 0) if self.spec.all_bass else (lambda p: 2 * (bass != (p.string >= low)))
        chosen = like[0] if like else min(options, key=lambda p: abs((p.fret or hand) - hand) + side(p))
        self.positions[note['id']] = dict(string=chosen.string, fret=chosen.fret)
        return True

    def clone(self):
        return GuitarRules(copy.deepcopy(self.part))

    def empty(self):
        from guitar_video_app.instruments.guitar.view import new_part

        return GuitarRules(new_part(self.spec))
