"""Beats, tempo maps and time signatures; beats are the timing authority, seconds follow from tempo."""
from bisect import bisect_right
from fractions import Fraction


def beat(value):
    if isinstance(value, bool):
        raise ValueError('A beat must be a number or rational string.')
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError('Invalid beat value') from exc


def measure_beats(signature):
    """Quarter-note beats in one measure of a [numerator, denominator] signature."""
    return Fraction(signature[0] * 4, signature[1])


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
