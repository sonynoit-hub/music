"""Piano lessons from normalized song JSON (music.analyzer output; no guitar mapping needed)."""
from __future__ import annotations

from typing import Any

from guitar_video_app.instruments.piano.hands import hands_from_tracks, plan_hands
from guitar_video_app.instruments.piano.keyboard import playable
from guitar_video_app.instruments.piano.view import PART, new_part
from guitar_video_app.music.normalized import normalized_to_lesson, note_id


def lesson_from_normalized(normalized: dict[str, Any], *, fps: int = 60, name: str | None = None) -> dict[str, Any]:
    """A V3 lesson with a piano part. Notes outside the 88 keys are left out. Hands come from the
    MIDI tracks when they look like a left and a right hand (part "hands_from": "midi_tracks"),
    otherwise from plan_hands ("planned")."""
    lesson = normalized_to_lesson(normalized, fps=fps, name=name, keep=lambda note: playable(int(note['pitch'])))
    notes = normalized.get('notes', [])
    kept = [(index, note) for index, note in enumerate(notes) if playable(int(note['pitch']))]
    source_by_id = {note_id(note, index + 1): note for index, note in kept}
    for note in lesson['music']['notes']:
        source = source_by_id[note['id']]
        note.update({key: source[key] for key in ('velocity', 'channel', 'track_id') if key in source})
    from_tracks = hands_from_tracks([note for _, note in kept], normalized.get('tracks'))
    part = new_part()
    if from_tracks is not None:
        for position, (index, note) in enumerate(kept):
            part['notes'][note_id(note, index + 1)] = dict(hand=from_tracks[position], by='midi')
        part['hands_from'] = 'midi_tracks'
    else:
        for identity, hand in plan_hands(lesson['music']).items():
            part['notes'][identity] = dict(hand=hand)
        part['hands_from'] = 'planned'
    lesson['parts'][PART] = part
    return lesson
