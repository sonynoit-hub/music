"""Instruments that play a lesson's music; each keeps its own part of a V3 lesson.

The music layer never depends on an instrument. The lesson's first part is the active one: music
operations take their instrument decisions from its rules (lesson_rules; pitch-only rules when the
lesson has no part), and only it has to play every note. Other parts are kept so a song can switch
back to them (activate), and are completed then.
"""
from __future__ import annotations

from guitar_video_app.instruments.base import Instrument
from guitar_video_app.instruments.bass import BASS
from guitar_video_app.instruments.guitar import GUITAR
from guitar_video_app.instruments.piano import PIANO
from guitar_video_app.music.lesson import VERSION, prepare
from guitar_video_app.music.rules import PitchRules

INSTRUMENTS: dict[str, Instrument] = {GUITAR.name: GUITAR, PIANO.name: PIANO, BASS.name: BASS}


def get_instrument(name: str) -> Instrument:
    try:
        return INSTRUMENTS[name]
    except KeyError:
        raise ValueError(f'Unknown instrument {name!r}; known: {", ".join(INSTRUMENTS)}.') from None


def parts(lesson: dict) -> list[tuple[str, dict, Instrument]]:
    return [(name, part, get_instrument(part.get('instrument', name))) for name, part in lesson.get('parts', {}).items()]


def lesson_rules(lesson: dict) -> PitchRules:
    found = parts(lesson)
    if not found:
        return PitchRules()
    _, part, instrument = found[0]
    return instrument.rules(part)


def as_lesson(data: dict) -> dict:
    """A V3 lesson from V3 or V2 (guitar) lesson data."""
    if not isinstance(data, dict):
        raise ValueError('A lesson must be a JSON object.')
    if data.get('version') == VERSION:
        if not isinstance(data.get('music'), dict) or not isinstance(data.get('parts', {}), dict):
            raise ValueError('A version 3 lesson needs a music object and a parts object.')
        data.setdefault('parts', {})
        return data
    if data.get('version') == 2:
        from guitar_video_app.instruments.guitar.view import from_v2

        return from_v2(data)
    raise ValueError('Expected a version 2 or version 3 lesson.')


def check_lesson(lesson: dict) -> dict:
    """Playback data of the lesson's music (music.lesson.prepare) after checking it and the active part."""
    played = prepare(lesson['music'], lesson['fps'], lesson_rules(lesson))
    for name, _, instrument in parts(lesson)[:1]:
        instrument.check(lesson, name)
    return played


def active_instrument(lesson: dict) -> str | None:
    found = parts(lesson)
    return found[0][2].name if found else None


def activate(lesson: dict, instrument: str, **options) -> int:
    """Make the lesson's part for instrument the active (first) one, adding it when missing; its
    notes are chosen again when it does not play every note (options go to Instrument.assign).
    Returns how many notes it plays differently; ValueError when it cannot play the music."""
    player = get_instrument(instrument)
    unplayable = sum(not player.playable(n['pitch']) for n in lesson['music']['notes'])
    if unplayable:
        raise ValueError(f"{unplayable} note{'s' if unplayable > 1 else ''} cannot be played on the {instrument}.")
    found = [name for name, part, owner in parts(lesson) if owner is player]
    name = found[0] if found else instrument
    lesson.setdefault('parts', {})
    part = lesson['parts'].get(name) or player.new_part()
    lesson['parts'] = {name: part, **{k: v for k, v in lesson['parts'].items() if k != name}}
    try:
        player.check(lesson, name)
        return 0
    except (KeyError, ValueError):
        return player.assign(lesson, part, **options)


def sync_parts(lesson: dict) -> None:
    for name, _, instrument in parts(lesson):
        instrument.sync(lesson, name)


def part_view(lesson: dict, name: str) -> dict:
    if name not in lesson.get('parts', {}):
        raise ValueError(f'This lesson has no {name} part.')
    return get_instrument(lesson['parts'][name].get('instrument', name)).view(lesson, name)
