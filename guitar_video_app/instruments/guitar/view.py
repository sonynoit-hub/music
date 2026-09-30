"""The guitar view of a lesson: the version 2 format that Blender, the renderer and the tab editor use.

V2 is {"version": 2, "string_numbering": "1=high E, 6=low E", tempo and signature fields, "notes":
[{id, string, fret, start_beat, duration_beats}]}; the pitch is the string's open pitch plus the
fret. guitar_view builds it from a V3 lesson's music and guitar part, from_v2 goes back.
"""
from __future__ import annotations

from guitar_video_app.music.lesson import MUSIC_KEYS, VERSION, check_timing, playback, timed_notes
from guitar_video_app.music.tempo import tempo_map
from guitar_video_app.instruments.guitar.tuning import MAX_FRET, TUNING, pitch_of

STRING_NUMBERING = '1=high E, 6=low E'
PART = 'guitar'


def _check_position(item):
    string, fret = item['string'], item['fret']
    if type(string) is not int or not 1 <= string <= 6 or type(fret) is not int or not 0 <= fret <= MAX_FRET:
        raise ValueError('String must be 1-6 and fret must be 0-20.')


def prepare(data: dict) -> dict:
    """Validated playback data of a V2 lesson (see music.lesson.prepare); notes keep string and fret."""
    if data.get('version') != 2 or data.get('string_numbering') != STRING_NUMBERING:
        raise ValueError('Expected version 2 with standard guitar string numbering.')
    tempos = tempo_map(data)
    fps = data['fps']
    measure = check_timing(fps, data['time_signature'])
    string = lambda note: note['string']
    notes = timed_notes(data['notes'], tempos, fps, string, _check_position, 'string')
    return playback(notes, tempos, fps, measure, data.get('end_beat'), string, string)


def new_part() -> dict:
    return dict(instrument='guitar', tuning=list(TUNING), positions={})


def from_v2(data: dict) -> dict:
    """The V3 lesson of a valid V2 lesson; note order and every field are kept."""
    prepare(data)
    music = {key: data[key] for key in MUSIC_KEYS if key in data}
    part = new_part()
    notes = []
    for note in data['notes']:
        extra = {k: v for k, v in note.items() if k not in ('id', 'string', 'fret', 'start_beat', 'duration_beats')}
        notes.append(dict(id=note['id'], pitch=pitch_of(note['string'], note['fret']),
                          start_beat=note['start_beat'], duration_beats=note['duration_beats'], **extra))
        part['positions'][note['id']] = dict(string=note['string'], fret=note['fret'])
    music['notes'] = notes
    lesson = {k: v for k, v in data.items() if k not in (*MUSIC_KEYS, 'version', 'string_numbering', 'notes')}
    return dict(version=VERSION, **lesson, music=music, parts={PART: part})


def guitar_view(lesson: dict, name: str = PART) -> dict:
    """The V2 lesson of a V3 lesson's music played by its guitar part name."""
    music, part = lesson['music'], lesson['parts'][name]
    if part.get('tuning', TUNING) != TUNING:
        raise ValueError('Only standard tuning can be drawn.')
    notes = []
    for note in music['notes']:
        position = part['positions'].get(note['id'])
        if position is None:
            raise ValueError(f"Note {note['id']} has no string and fret.")
        if pitch_of(position['string'], position['fret']) != note['pitch']:
            raise ValueError(f"Note {note['id']}: string {position['string']} fret {position['fret']} "
                             f"does not play MIDI pitch {note['pitch']}.")
        extra = {k: v for k, v in note.items() if k not in ('id', 'pitch', 'start_beat', 'duration_beats')}
        notes.append(dict(id=note['id'], string=position['string'], fret=position['fret'],
                          start_beat=note['start_beat'], duration_beats=note['duration_beats'], **extra))
    fields = {k: v for k, v in lesson.items() if k not in ('version', 'music', 'parts')}
    fields.update((k, v) for k, v in music.items() if k != 'notes')
    fields['string_numbering'] = STRING_NUMBERING
    order = ('name', 'tempo_bpm', 'tempo_changes', 'fps', 'time_signature', 'string_numbering', 'end_beat', 'source')
    view = dict(version=2, **{k: fields.pop(k) for k in order if k in fields})
    return dict(view, **fields, notes=notes)


def set_notes(lesson: dict, notes: list[dict], name: str = PART) -> None:
    """Replace the lesson's notes with V2 notes (id, string, fret, start_beat, duration_beats)."""
    positions = lesson['parts'][name]['positions']
    lesson['music']['notes'] = []
    for note in notes:
        lesson['music']['notes'].append(dict(id=note['id'], pitch=pitch_of(note['string'], note['fret']),
                                             start_beat=note['start_beat'], duration_beats=note['duration_beats']))
        positions[note['id']] = dict(string=note['string'], fret=note['fret'])


def set_position(lesson: dict, note: dict, string: int, fret: int, name: str = PART) -> None:
    """Play note on string and fret; its pitch follows."""
    note['pitch'] = pitch_of(string, fret)
    lesson['parts'][name]['positions'][note['id']] = dict(string=string, fret=fret)
