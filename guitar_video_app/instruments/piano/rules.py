"""A piano part's answers to the questions music operations ask (see music.rules).

Every pitch has one key, so the pitch stays the slot: pressing a key again cuts its previous note
off. The part stores which hand plays each note; the left hand's notes are the bass voice.
"""
from __future__ import annotations

import copy
from statistics import median

from guitar_video_app.music.rules import PitchRules
from guitar_video_app.music.tempo import beat
from guitar_video_app.instruments.piano.keyboard import MIDDLE_C, playable

HAND_BEATS = 2


class PianoRules(PitchRules):
    def __init__(self, part: dict | None = None):
        from guitar_video_app.instruments.piano.view import new_part

        self.part = part if part is not None else new_part()
        self.hands = self.part.setdefault('notes', {})

    def hand(self, note: dict) -> str | None:
        entry = self.hands.get(note['id'])
        return entry.get('hand') if entry else None

    def is_bass(self, note, notes, measure):
        """The left hand's notes; a note with no hand yet falls back to the pitch rule."""
        hand = self.hand(note)
        return super().is_bass(note, notes, measure) if hand is None else hand == 'left'

    def copy(self, source, note, rules=None):
        hand = rules.hand(source) if isinstance(rules, PianoRules) else self.hand(source) if rules is None else None
        if hand is None:
            return self.default(note)
        if not playable(note['pitch']):
            return False
        self.hands[note['id']] = dict(hand=hand)
        return True

    def default(self, note):
        """Left hand below middle C, right hand from it."""
        if not playable(note['pitch']):
            return False
        self.hands[note['id']] = dict(hand='left' if note['pitch'] < MIDDLE_C else 'right')
        return True

    def place(self, note, notes, reference):
        """The hand whose notes within HAND_BEATS are nearest in pitch (the median of each hand)."""
        if not playable(note['pitch']):
            return False
        start = beat(note['start_beat'])
        near = {'left': [], 'right': []}
        for other in notes:
            hand = self.hand(other)
            if hand and abs(beat(other['start_beat']) - start) <= HAND_BEATS:
                near[hand].append(other['pitch'])
        distance = {hand: abs(median(pitches) - note['pitch']) for hand, pitches in near.items() if pitches}
        if not distance:
            return self.default(note)
        self.hands[note['id']] = dict(hand=min(distance, key=lambda hand: (distance[hand], hand)))
        return True

    def clone(self):
        return PianoRules(copy.deepcopy(self.part))

    def empty(self):
        return PianoRules()
