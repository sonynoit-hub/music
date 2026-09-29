"""Beat-based lesson validation and deterministic playback, independent of Blender."""
from fractions import Fraction
import math


def beat(value):
    if isinstance(value, bool):
        raise ValueError('A beat must be a number or rational string.')
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError('Invalid beat value') from exc


def prepare(data):
    if data.get('version') != 2 or data.get('string_numbering') != '1=high E, 6=low E':
        raise ValueError('Expected version 2 with standard guitar string numbering.')
    tempo = beat(data['tempo_bpm'])
    fps = data['fps']
    signature = data['time_signature']
    if tempo <= 0 or type(fps) is not int or not 1 <= fps <= 240:
        raise ValueError('Tempo and FPS must be positive; FPS must be an integer up to 240.')
    if (len(signature) != 2 or any(type(v) is not int for v in signature)
            or signature[0] <= 0 or signature[1] not in (1, 2, 4, 8, 16)):
        raise ValueError('Invalid time signature.')
    measure = Fraction(signature[0] * 4, signature[1])
    frames_per_beat = Fraction(fps * 60, 1) / tempo
    notes, ids, starts = [], set(), set()
    for item in data['notes']:
        identity = item['id']
        string, fret = item['string'], item['fret']
        start, duration = beat(item['start_beat']), beat(item['duration_beats'])
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError('Note IDs must be nonempty and unique.')
        if type(string) is not int or not 1 <= string <= 6 or type(fret) is not int or not 0 <= fret <= 20:
            raise ValueError('String must be 1-6 and fret must be 0-20.')
        if start < 0 or duration <= 0 or duration * frames_per_beat < 1:
            raise ValueError('Invalid start/duration or duration shorter than one frame.')
        if (string, start) in starts:
            raise ValueError('Two simultaneous notes on one string are ambiguous.')
        ids.add(identity)
        starts.add((string, start))
        notes.append(dict(item, start=start, end=start + duration))
    notes.sort(key=lambda n: (n['start'], n['string']))
    # A retrigger permanently cuts the previous note, even after the new note ends.
    latest = {}
    for note in notes:
        previous = latest.get(note['string'])
        if previous:
            previous['end'] = min(previous['end'], note['start'])
        latest[note['string']] = note
    end = beat(data.get('end_beat', max((n['end'] for n in notes), default=measure)))
    if end <= 0 or end < max((n['end'] for n in notes), default=0):
        raise ValueError('Lesson end precedes a note ending.')
    return dict(notes=notes, measure=measure, page_beats=measure * 2,
                frames_per_beat=frames_per_beat, end=end, fps=fps,
                frame_end=math.ceil(end * frames_per_beat))


def state(lesson, frame):
    position = beat(frame) / lesson['frames_per_beat']
    final_page = max(0, math.ceil(lesson['end'] / lesson['page_beats']) - 1)
    page = min(final_page, max(0, int(position // lesson['page_beats'])))
    active = [n for n in lesson['notes'] if n['start'] <= position < n['end']]
    return position, page, active
