"""Six-string guitar in standard tuning: positions, fingering, tabs and the V2 view Blender draws."""
from __future__ import annotations

from guitar_video_app.instruments.base import Instrument
from guitar_video_app.instruments.fretted import GUITAR_SPEC
from guitar_video_app.instruments.guitar.rules import GuitarRules
from guitar_video_app.instruments.guitar.view import guitar_view, new_part, prepare

GUITAR_PROGRAM = GUITAR_SPEC.program  # General MIDI acoustic guitar (nylon)


class Guitar(Instrument):
    """A fretted instrument drawn from its Fretted spec; Bass reuses it with the bass spec."""
    name = 'guitar'
    spec = GUITAR_SPEC
    midi_program = GUITAR_PROGRAM

    def new_part(self):
        return new_part(self.spec)

    def rules(self, part):
        return GuitarRules(part)

    def playable(self, pitch):
        return bool(self.spec.positions(pitch))

    def assign(self, lesson, part, position=None, keep=frozenset()):
        """Plan strings and frets again; notes with no position yet start at the lowest fret."""
        from guitar_video_app.instruments.guitar.refinger import refinger_part

        rules = GuitarRules(part)
        for note in lesson['music']['notes']:
            if note['id'] not in rules.positions and not rules.default(note):
                raise ValueError(f"Note {note['id']} cannot be played on the {self.name}.")
        return refinger_part(lesson['music'], part, position, keep)

    def check(self, lesson, name):
        prepare(guitar_view(lesson, name))

    def sync(self, lesson, name):
        part = lesson['parts'][name]
        positions = part.get('positions', {})
        part['positions'] = {n['id']: positions[n['id']] for n in lesson['music']['notes'] if n['id'] in positions}

    def view(self, lesson, name):
        return guitar_view(lesson, name)


GUITAR = Guitar()
