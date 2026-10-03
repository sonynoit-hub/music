"""The music layer of a version 3 lesson, and deterministic playback independent of Blender.

A V3 lesson is {"version": 3, "name", "fps", "music": {...}, "parts": {name: part}}. music holds
tempo_bpm, the optional tempo_changes, time_signature, end_beat, the optional source and sections,
and notes of id, pitch (MIDI), start_beat and duration_beats. Each part says how one instrument
plays those notes (see guitar_video_app.instruments).
"""
from __future__ import annotations

from fractions import Fraction
import math

from guitar_video_app.music.rules import PitchRules
from guitar_video_app.music.tempo import beat, beat_at, measure_beats, seconds_at, tempo_map

VERSION = 3
MUSIC_KEYS = ('tempo_bpm', 'tempo_changes', 'time_signature', 'end_beat', 'sections', 'source', 'audio_start')


def check_timing(fps, signature) -> Fraction:
    """Validate the frame rate and time signature; returns the measure length in beats."""
    if type(fps) is not int or not 1 <= fps <= 240:
        raise ValueError('FPS must be an integer from 1 to 240.')
    return check_signature(signature)


def check_signature(signature) -> Fraction:
    """Validate a [numerator, denominator] time signature; returns the measure length in beats."""
    if (len(signature) != 2 or any(type(v) is not int for v in signature)
            or signature[0] <= 0 or signature[1] not in (1, 2, 4, 8, 16)):
        raise ValueError('Invalid time signature.')
    return measure_beats(signature)


def set_time_signature(music: dict, signature) -> None:
    """Re-bar the music layer in a new time signature: notes, tempo changes and every time in seconds
    stay put; only the bar lines move. The end moves to the bar line after the last note, or to the
    last whole new bar within the old end when that is later, so switching back and forth keeps it."""
    measure = check_signature(list(signature))
    last = max((beat(n['start_beat']) + beat(n['duration_beats']) for n in music['notes']), default=Fraction(0))
    old_end = beat(music['end_beat']) if music.get('end_beat') is not None else last
    bars = max(1, math.ceil(last / measure), math.floor(old_end / measure))
    music['time_signature'] = list(signature)
    music['end_beat'] = str(bars * measure)


def timed_notes(items, tempos, fps, slot, check=None, slot_name='pitch') -> list[dict]:
    """Copies of the notes with start and end in beats, after checking ids, lengths and that no
    two notes start together in one slot; check(item) validates the instrument fields."""
    notes, ids, starts = [], set(), set()
    for item in items:
        identity = item['id']
        start, duration = beat(item['start_beat']), beat(item['duration_beats'])
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError('Note IDs must be nonempty and unique.')
        if check:
            check(item)
        if start < 0 or duration <= 0 or (seconds_at(tempos, start + duration) - seconds_at(tempos, start)) * fps < 1:
            raise ValueError('Invalid start/duration or duration shorter than one frame.')
        if (slot(item), start) in starts:
            raise ValueError(f'Two simultaneous notes on one {slot_name} are ambiguous.')
        ids.add(identity)
        starts.add((slot(item), start))
        notes.append(dict(item, start=start, end=start + duration))
    return notes


def playback(notes, tempos, fps, measure, end_beat, slot, order) -> dict:
    """Sort timed notes, cut each note off at the next note in its slot, and find the end."""
    notes.sort(key=lambda n: (n['start'], order(n)))
    # A retrigger permanently cuts the previous note, even after the new note ends.
    latest = {}
    for note in notes:
        previous = latest.get(slot(note))
        if previous:
            previous['end'] = min(previous['end'], note['start'])
        latest[slot(note)] = note
    end = beat(end_beat if end_beat is not None else max((n['end'] for n in notes), default=measure))
    if end <= 0 or end < max((n['end'] for n in notes), default=0):
        raise ValueError('Lesson end precedes a note ending.')
    return dict(notes=notes, measure=measure, page_beats=measure * 2, tempo_map=tempos,
                end=end, fps=fps, frame_end=math.ceil(seconds_at(tempos, end) * fps))


def _check_pitch(item):
    if type(item['pitch']) is not int or not 0 <= item['pitch'] <= 127:
        raise ValueError('Pitch must be a MIDI note number from 0 to 127.')


def prepare(music: dict, fps: int, rules: PitchRules | None = None) -> dict:
    """Validated playback data of a music layer: notes with start and end beats (a note ends at
    the latest where the next note in its slot starts), measure, tempo map, end and last frame."""
    rules = rules or PitchRules()
    tempos = tempo_map(music)
    measure = check_timing(fps, music['time_signature'])
    notes = timed_notes(music['notes'], tempos, fps, rules.slot, _check_pitch, rules.slot_name)
    return playback(notes, tempos, fps, measure, music.get('end_beat'), rules.slot, rules.order)


def seconds_between(lesson, start, end):
    return float(seconds_at(lesson['tempo_map'], end) - seconds_at(lesson['tempo_map'], start))


def state(lesson, frame):
    position = beat_at(lesson['tempo_map'], beat(frame) / lesson['fps'])
    final_page = max(0, math.ceil(lesson['end'] / lesson['page_beats']) - 1)
    page = min(final_page, max(0, int(position // lesson['page_beats'])))
    active = [n for n in lesson['notes'] if n['start'] <= position < n['end']]
    return position, page, active


def new_note_id(notes, prefix: str) -> str:
    """The first of prefix001, prefix002, ... no note uses."""
    ids = {str(n.get('id')) for n in notes}
    number = 1
    while f'{prefix}{number:03d}' in ids:
        number += 1
    return f'{prefix}{number:03d}'


def extend_to_bar(music: dict) -> None:
    """Move the end to the bar line after the last note when a note now ends past it."""
    measure = measure_beats(music['time_signature'])
    last = max(beat(n['start_beat']) + beat(n['duration_beats']) for n in music['notes'])
    if last > beat(music.get('end_beat', 0)):
        music['end_beat'] = str(math.ceil(last / measure) * measure)


def trim_to_last_measure(music: dict) -> None:
    """End at the bar line after the last note, dropping empty trailing measures."""
    measure = measure_beats(music['time_signature'])
    last = max(beat(n['start_beat']) + beat(n['duration_beats']) for n in music['notes'])
    music['end_beat'] = str(math.ceil(last / measure) * measure)
