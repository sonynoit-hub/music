"""Choose strings and frets again, keeping every pitch and its timing."""
from __future__ import annotations

from collections import Counter

from guitar_video_app.instruments.fretted import GUITAR_SPEC, Fretted, spec_of
from guitar_video_app.instruments.guitar.fingering_solver import plan_positions
from guitar_video_app.instruments.guitar.schema import GuitarPosition
from guitar_video_app.music.schema import RawNote
from guitar_video_app.music.tempo import beat, seconds_at, tempo_map

HAND_POSITIONS = (3, 5, 7, 9, 12)


def refinger_lesson(data: dict, position: int | None = None, keep: set[str] = frozenset(),
                    spec: Fretted = GUITAR_SPEC) -> int:
    """Re-plan the fingering of a V2 lesson on spec's strings in place; position is the preferred index-finger fret,
    None for the automatic low-fret choice. Notes whose id is in keep, and notes the planner cannot
    place, keep their fingering; the others are planned around them.
    Returns the number of notes that moved."""
    if position is not None and position not in HAND_POSITIONS:
        raise ValueError(f'Hand position must be one of {HAND_POSITIONS}.')
    tempos = tempo_map(data)
    seconds = lambda position: float(seconds_at(tempos, beat(position)))
    raw = [RawNote(pitch=spec.pitch_of(n['string'], n['fret']), start_time=seconds(n['start_beat']),
                   end_time=seconds(beat(n['start_beat']) + beat(n['duration_beats'])))
           for n in data['notes']]
    fixed = {i: GuitarPosition(n['string'], n['fret']) for i, n in enumerate(data['notes']) if n['id'] in keep}
    chosen = plan_positions(raw, tolerate_unplayable=True, position=position, fixed=fixed, spec=spec)
    final = [(place.string, place.fret) if place else (n['string'], n['fret']) for n, place in zip(data['notes'], chosen)]
    used = Counter((string, beat(n['start_beat'])) for (string, _), n in zip(final, data['notes']))
    moved = 0
    for note, (string, fret) in zip(data['notes'], final):
        if (string, fret) == (note['string'], note['fret']) or used[(string, beat(note['start_beat']))] > 1:
            continue
        note['string'], note['fret'] = string, fret
        moved += 1
    return moved


def refinger_part(music: dict, part: dict, position: int | None = None, keep: set[str] = frozenset()) -> int:
    """refinger_lesson for the notes of a music layer played by a guitar or bass part; the part changes."""
    positions = part['positions']
    notes = [dict(id=n['id'], start_beat=n['start_beat'], duration_beats=n['duration_beats'], **positions[n['id']])
             for n in music['notes']]
    moved = refinger_lesson(dict(music, notes=notes), position, keep, spec_of(part))
    for note in notes:
        positions[note['id']] = dict(string=note['string'], fret=note['fret'])
    return moved
