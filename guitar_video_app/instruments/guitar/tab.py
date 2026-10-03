"""Guitar tabs: read a tab file, fit it to a recording, or review a lesson against it.

The timing work (fitting, following the playing, merging with the lesson) is music logic in
music.alignment and music.review; this module adds what the tab says about strings and frets.
Lessons and tabs here are V3 lessons whose first part is a guitar (or bass) part; a tab file
with "instrument": "bass" holds bass strings 1-4.
"""
from __future__ import annotations

from fractions import Fraction
import math

from guitar_video_app.instruments.fretted import SPECS, spec_of
from guitar_video_app.instruments.guitar.fingering_solver import plan_positions
from guitar_video_app.instruments.guitar.refinger import HAND_POSITIONS, refinger_part
from guitar_video_app.instruments.guitar.rules import GuitarRules
from guitar_video_app.instruments.guitar.view import from_v2, guitar_view, prepare
from guitar_video_app.music.alignment import counted_beat, import_to_audio, scale_beats
from guitar_video_app.music.lesson import VERSION
from guitar_video_app.music.review import merge_reference, review_report
from guitar_video_app.music.schema import RawNote
from guitar_video_app.music.tempo import beat, measure_beats, seconds_at, tempo_map

POSITION_MARGIN = 0.25


def read_tab(data: dict) -> dict:
    """A V3 lesson from a tab file: notes with string, fret, start_beat and duration_beats,
    the written tempo_bpm and time_signature; ids, fps and end_beat are filled in. Optional:
    title, artist, and audio_start (rough audio second of beat 0) when the tab is a later
    section of the recording; instrument ("guitar", the default, or "bass"); per note "muted": true
    for a dead note ("x"), whose fret may be left out (0)."""
    if not isinstance(data, dict) or not data.get('notes'):
        raise ValueError('A tab file needs a list of notes.')
    spec = SPECS.get(data.get('instrument', 'guitar'))
    if spec is None:
        raise ValueError(f"A tab is for one of: {', '.join(SPECS)}.")
    if 'tempo_bpm' not in data:
        raise ValueError('Give the written tempo (tempo_bpm), even if it is approximate.')
    notes = []
    for index, note in enumerate(data['notes'], start=1):
        try:
            muted = note.get('muted') is True
            notes.append(dict(id=str(note.get('id') or f't{index:04d}'), string=int(note['string']),
                              fret=int(note.get('fret', 0) if muted else note['fret']),
                              start_beat=str(beat(note['start_beat'])),
                              duration_beats=str(beat(note['duration_beats'])), **({'muted': True} if muted else {})))
        except (KeyError, TypeError) as exc:
            raise ValueError(f'Tab note {index} needs string, fret, start_beat and duration_beats.') from exc
    signature = [int(v) for v in data.get('time_signature', [4, 4])]
    last = max(beat(n['start_beat']) + beat(n['duration_beats']) for n in notes)
    tab = dict(version=2, name=str(data.get('title') or data.get('name') or 'Imported tab'),
               tempo_bpm=data['tempo_bpm'], fps=int(data.get('fps', 60)), time_signature=signature,
               string_numbering=spec.numbering,
               end_beat=str(beat(data['end_beat']) if 'end_beat' in data
                            else math.ceil(last / measure_beats(signature)) * measure_beats(signature)),
               notes=notes)
    if data.get('audio_start') is not None:
        tab['audio_start'] = float(data['audio_start'])
    lesson = from_v2(tab)
    for key in ('title', 'artist'):
        if data.get(key):
            lesson[key] = str(data[key])
    return lesson


def _name(lesson: dict) -> str:
    return next(iter(lesson['parts']))


def _lesson(like: dict, music: dict, part: dict, drop=()) -> dict:
    top = {k: v for k, v in like.items() if k not in ('version', 'music', 'parts', *drop)}
    name = part.get('instrument', 'guitar')
    lesson = dict(version=VERSION, **top, music=music, parts={name: part})
    prepare(guitar_view(lesson, name))
    return lesson


def import_tab_to_audio(tab: dict, onsets: list, played: list) -> tuple[dict, dict]:
    """The tab fitted to the recording and made to follow what it plays (music.alignment); added
    notes take the string the tab uses for their pitch nearby (GuitarRules.place)."""
    tab_part = tab['parts'][_name(tab)]
    rules = GuitarRules(dict(tab_part, positions=dict(tab_part['positions'])))
    music, stats = import_to_audio(tab['music'], onsets, played, rules)
    return _lesson(tab, music, rules.part, drop=('title', 'artist')), stats


def review_with_tab(lesson: dict, offset: float, tab: dict, onsets: list, played: list) -> tuple[dict, float, dict]:
    """Return the reviewed lesson, its dashboard offset and a report of what changed.

    The tab's bars replace the lesson's wherever the recording plays them (music.review); the
    lesson's other notes stay, re-fingered the way the tab plays around the tab's own notes.
    lesson sits in the audio by offset (audio seconds = lesson seconds - offset). A fast tab is
    reviewed counting slower beats (counted_beat); the lesson keeps the tab's written meter.
    """
    factor = counted_beat(tab['music'])
    reference = tab['music'] if factor == 1 else scale_beats(tab['music'], Fraction(1, factor))
    music, offset, report, part = _review(lesson, offset, reference, tab['parts'][_name(tab)], onsets, played)
    if factor > 1:
        music = scale_beats(music, factor)
        report.update(tempo_bpm=music['tempo_bpm'],
                      removed_notes=[dict(n, start_beat=str(beat(n['start_beat']) * factor)) for n in report['removed_notes']])
    return _lesson(lesson, music, part), offset, report


def _review(lesson, offset, reference, tab_part, onsets, played):
    old_rules = GuitarRules(lesson['parts'][_name(lesson)])
    music, zero, context = merge_reference(lesson['music'], offset, reference, onsets, played,
                                           old_rules, GuitarRules(tab_part))
    out = context['rules']
    position = tab_hand_position(reference, tab_part)
    refinger_part(music, out.part, position, keep=context['from_tab'])
    prepare(guitar_view(dict(version=VERSION, fps=lesson['fps'], music=music, parts={'part': out.part}), 'part'))
    report = review_report(context, music, zero,
                           same=lambda old, new: old_rules.position(old) == out.position(new),
                           ghost=lambda old: dict(old_rules.position(old)))
    report['position'] = position
    return music, -round(zero, 6), report, out.part


def tab_hand_position(music: dict, part: dict) -> int | None:
    """The hand position (HAND_POSITIONS) whose planned fingering of the tab's own notes
    matches the tab most often, when it matches at least POSITION_MARGIN of the notes more
    than the automatic choice does; otherwise None, the automatic choice."""
    written = tempo_map(music)
    seconds = lambda position: float(seconds_at(written, position))
    spec = spec_of(part)
    places = [part['positions'][n['id']] for n in music['notes']]
    raw = [RawNote(pitch=spec.pitch_of(p['string'], p['fret']), start_time=seconds(beat(n['start_beat'])),
                   end_time=seconds(beat(n['start_beat']) + beat(n['duration_beats'])))
           for n, p in zip(music['notes'], places)]

    def agreement(position):
        chosen = plan_positions(raw, tolerate_unplayable=True, position=position, spec=spec)
        return sum(1 for p, place in zip(places, chosen) if place and (place.string, place.fret) == (p['string'], p['fret']))

    best = max(HAND_POSITIONS, key=agreement)
    return best if agreement(best) - agreement(None) >= POSITION_MARGIN * len(raw) else None
