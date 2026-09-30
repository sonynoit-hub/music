"""88-key piano: which hand plays each note, and the piano view Blender draws."""
from __future__ import annotations

from guitar_video_app.instruments.base import Instrument
from guitar_video_app.instruments.piano.hands import plan_hands
from guitar_video_app.instruments.piano.keyboard import playable
from guitar_video_app.instruments.piano.rules import PianoRules
from guitar_video_app.instruments.piano.view import new_part, piano_view, prepare

PIANO_PROGRAM = 0  # General MIDI acoustic grand piano


def kept_hands(part: dict) -> dict[str, str]:
    """Hands chosen in the dashboard or read from MIDI tracks, which planning keeps."""
    return {identity: entry['hand'] for identity, entry in part.get('notes', {}).items() if entry.get('by')}


class Piano(Instrument):
    name = 'piano'
    midi_program = PIANO_PROGRAM

    def new_part(self):
        return new_part()

    def rules(self, part):
        return PianoRules(part)

    def playable(self, pitch):
        return playable(pitch)

    def assign(self, lesson, part, keep=None):
        """Plan the hands again; notes in keep (default: hands chosen by the user or from MIDI
        tracks, plus notes not in the planning) keep theirs. Returns how many notes changed hand."""
        music = lesson['music']
        entries = part.setdefault('notes', {})
        fixed = kept_hands(part) if keep is None else {i: entries[i]['hand'] for i in keep if i in entries}
        unplayable = [n['id'] for n in music['notes'] if not playable(n['pitch'])]
        if unplayable:
            raise ValueError(f'{len(unplayable)} notes are outside the piano range.')
        planned = plan_hands(music, fixed)
        changed = 0
        for note in music['notes']:
            identity = note['id']
            if identity in fixed:
                continue
            before = entries.get(identity, {}).get('hand')
            changed += before != planned[identity]
            entries[identity] = dict(hand=planned[identity])
        return changed

    def check(self, lesson, name):
        prepare(piano_view(lesson, name))

    def sync(self, lesson, name):
        part = lesson['parts'][name]
        entries = part.get('notes', {})
        part['notes'] = {n['id']: entries[n['id']] for n in lesson['music']['notes'] if n['id'] in entries}

    def view(self, lesson, name):
        return piano_view(lesson, name)

    def midi_tracks(self, part, title):
        hand = lambda wanted: (lambda note: part['notes'].get(note['id'], {}).get('hand') == wanted)
        return ((f'{title} right hand', 0, hand('right')), (f'{title} left hand', 0, hand('left')))


PIANO = Piano()
