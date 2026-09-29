"""Beat-based lesson validation and deterministic playback, independent of Blender."""
from bisect import bisect_right
from fractions import Fraction
import math


def beat(value):
    if isinstance(value, bool):
        raise ValueError('A beat must be a number or rational string.')
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError('Invalid beat value') from exc


def tempo_map(data):
    """[(beat, seconds, bpm)] from tempo_bpm at beat 0 plus the optional tempo_changes."""
    points = [(Fraction(0), beat(data['tempo_bpm']))]
    for change in data.get('tempo_changes') or []:
        points.append((beat(change['beat']), beat(change['bpm'])))
    if any(bpm <= 0 for _, bpm in points) or any(b <= a for (a, _), (b, _) in zip(points, points[1:])):
        raise ValueError('Tempos must be positive and tempo changes must follow each other after beat 0.')
    segments, seconds = [], Fraction(0)
    for index, (position, bpm) in enumerate(points):
        if index:
            previous, previous_bpm = points[index - 1]
            seconds += (position - previous) * 60 / previous_bpm
        segments.append((position, seconds, bpm))
    return segments


def seconds_at(segments, position):
    start, seconds, bpm = segments[max(0, bisect_right(segments, position, key=lambda s: s[0]) - 1)]
    return seconds + (position - start) * 60 / bpm


def beat_at(segments, seconds):
    start, offset, bpm = segments[max(0, bisect_right(segments, seconds, key=lambda s: s[1]) - 1)]
    return start + (seconds - offset) * bpm / 60


def tempo_at(segments, position):
    return segments[max(0, bisect_right(segments, position, key=lambda s: s[0]) - 1)][2]


def prepare(data):
    if data.get('version') != 2 or data.get('string_numbering') != '1=high E, 6=low E':
        raise ValueError('Expected version 2 with standard guitar string numbering.')
    tempos = tempo_map(data)
    fps = data['fps']
    signature = data['time_signature']
    if type(fps) is not int or not 1 <= fps <= 240:
        raise ValueError('FPS must be an integer from 1 to 240.')
    if (len(signature) != 2 or any(type(v) is not int for v in signature)
            or signature[0] <= 0 or signature[1] not in (1, 2, 4, 8, 16)):
        raise ValueError('Invalid time signature.')
    measure = Fraction(signature[0] * 4, signature[1])
    notes, ids, starts = [], set(), set()
    for item in data['notes']:
        identity = item['id']
        string, fret = item['string'], item['fret']
        start, duration = beat(item['start_beat']), beat(item['duration_beats'])
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError('Note IDs must be nonempty and unique.')
        if type(string) is not int or not 1 <= string <= 6 or type(fret) is not int or not 0 <= fret <= 20:
            raise ValueError('String must be 1-6 and fret must be 0-20.')
        if start < 0 or duration <= 0 or (seconds_at(tempos, start + duration) - seconds_at(tempos, start)) * fps < 1:
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
    return dict(notes=notes, measure=measure, page_beats=measure * 2, tempo_map=tempos,
                end=end, fps=fps, frame_end=math.ceil(seconds_at(tempos, end) * fps))


def seconds_between(lesson, start, end):
    return float(seconds_at(lesson['tempo_map'], end) - seconds_at(lesson['tempo_map'], start))


def state(lesson, frame):
    position = beat_at(lesson['tempo_map'], beat(frame) / lesson['fps'])
    final_page = max(0, math.ceil(lesson['end'] / lesson['page_beats']) - 1)
    page = min(final_page, max(0, int(position // lesson['page_beats'])))
    active = [n for n in lesson['notes'] if n['start'] <= position < n['end']]
    return position, page, active
