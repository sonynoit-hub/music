"""What an instrument adds to a lesson.

A lesson's music layer (guitar_video_app.music.lesson) says which pitches sound when. A part,
lesson['parts'][name], says how one instrument plays them: for the guitar, the string and fret of
every note; a piano part would say which hand plays each note. The instrument turns its part into
the rules music operations consult (music.rules) and into the view its renderer draws.
"""
from __future__ import annotations

from guitar_video_app.music.rules import PitchRules


class Instrument:
    name = ''
    midi_program = 0

    def new_part(self) -> dict:
        """A part that plays no notes yet."""
        return dict(instrument=self.name)

    def rules(self, part: dict) -> PitchRules:
        """The part's answers to the questions music operations ask; changes made through them
        (copied, added or placed notes) are written to the part."""
        return PitchRules()

    def playable(self, pitch: int) -> bool:
        return True

    def assign(self, lesson: dict, part: dict, **options) -> int:
        """Choose again how the part plays every note, in place; returns how many changed."""
        return 0

    def check(self, lesson: dict, name: str) -> None:
        """Raise ValueError when the part does not play the lesson's music."""

    def sync(self, lesson: dict, name: str) -> None:
        """Drop what the part stores for notes the music no longer has."""

    def view(self, lesson: dict, name: str) -> dict:
        """What this instrument's renderer and editor draw."""
        raise NotImplementedError

    def midi_tracks(self, part: dict, title: str) -> tuple:
        """MIDI export tracks as (name, channel, select) for music.midi_export.music_midi."""
        return ((title, 0, None),)
