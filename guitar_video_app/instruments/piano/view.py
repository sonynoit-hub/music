"""A piano part and the piano view that Blender and the dashboard piano roll draw.

The part is {"instrument": "piano", "range": [21, 108], "notes": {note id: {"hand": "left" | "right"}}}.
A note entry may carry "by": "user" (the hand was chosen in the dashboard) or "midi" (it came from
the MIDI file's left- and right-hand tracks); planning hands again keeps those.

The view is {"version": 1, "instrument": "piano", tempo and signature fields, "keyboard": geometry,
"notes": [{id, pitch, key, black, x_mm, hand, start_beat, duration_beats}]}; key is 0-87 from A0 and
x_mm the key's center from the left edge of the keyboard (instruments.piano.keyboard).
"""
from __future__ import annotations

from guitar_video_app.music.lesson import check_timing, playback, timed_notes
from guitar_video_app.music.tempo import tempo_map
from guitar_video_app.instruments.piano.keyboard import HIGH, LOW, geometry, is_black, key_x_mm, playable

PART = 'piano'
HANDS = ('left', 'right')
VIEW_VERSION = 1


def new_part() -> dict:
    return dict(instrument='piano', range=[LOW, HIGH], notes={})


def hand_of(part: dict, note: dict) -> str:
    entry = part.get('notes', {}).get(note['id'])
    if entry is None or entry.get('hand') not in HANDS:
        raise ValueError(f"Note {note['id']} has no hand.")
    return entry['hand']


def piano_view(lesson: dict, name: str = PART) -> dict:
    """The view of a V3 lesson's music played by its piano part name."""
    music, part = lesson['music'], lesson['parts'][name]
    notes = []
    for note in music['notes']:
        if not playable(note['pitch']):
            raise ValueError(f"Note {note['id']}: MIDI pitch {note['pitch']} is outside the piano ({LOW}-{HIGH}).")
        extra = {k: v for k, v in note.items() if k not in ('id', 'pitch', 'start_beat', 'duration_beats')}
        notes.append(dict(id=note['id'], pitch=note['pitch'], key=note['pitch'] - LOW, black=is_black(note['pitch']),
                          x_mm=round(key_x_mm(note['pitch']), 3), hand=hand_of(part, note),
                          start_beat=note['start_beat'], duration_beats=note['duration_beats'], **extra))
    fields = {k: v for k, v in lesson.items() if k not in ('version', 'music', 'parts')}
    fields.update((k, v) for k, v in music.items() if k != 'notes')
    order = ('name', 'tempo_bpm', 'tempo_changes', 'fps', 'time_signature', 'end_beat', 'source')
    view = dict(version=VIEW_VERSION, instrument='piano', **{k: fields.pop(k) for k in order if k in fields})
    if 'pedal_events' in music:
        view['pedal_events'] = music['pedal_events']
    return dict(view, **fields, keyboard=geometry(), notes=notes)


def _check_note(item):
    if not playable(item.get('pitch')):
        raise ValueError(f'Pitch must be a MIDI note number from {LOW} to {HIGH}.')
    if item.get('hand') not in HANDS:
        raise ValueError('Hand must be left or right.')


def prepare(data: dict) -> dict:
    """Validated playback data of a piano view (see music.lesson.prepare); notes keep pitch, hand and x_mm."""
    if data.get('version') != VIEW_VERSION or data.get('instrument') != 'piano':
        raise ValueError('Expected a version 1 piano view.')
    tempos = tempo_map(data)
    fps = data['fps']
    measure = check_timing(fps, data['time_signature'])
    pitch = lambda note: note['pitch']
    notes = timed_notes(data['notes'], tempos, fps, pitch, _check_note, 'key')
    return playback(notes, tempos, fps, measure, data.get('end_beat'), pitch, lambda note: -note['pitch'])


def set_hand(lesson: dict, note: dict, hand: str, by: str | None = 'user', name: str = PART) -> None:
    if hand not in HANDS:
        raise ValueError('Hand must be left or right.')
    entry = dict(hand=hand)
    if by:
        entry['by'] = by
    lesson['parts'][name].setdefault('notes', {})[note['id']] = entry
