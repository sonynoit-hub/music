"""The fretted view of a lesson: the version 2 format that Blender, the renderer and the tab editor use.

V2 is {"version": 2, "string_numbering": "1=high E, 6=low E", tempo and signature fields, "notes":
[{id, string, fret, start_beat, duration_beats}]}; the pitch is the string's open pitch plus the
fret. guitar_view builds it from a V3 lesson's music and guitar part, from_v2 goes back. A bass
part gives the same format with "string_numbering": "1=high G, 4=low E", plus "instrument": "bass"
and "tuning" (open pitches of strings 1-4); a guitar view has neither, so readers default to six
guitar strings. A note with "muted": true is a dead note: the fretting hand only touches the string
at its fret, so it is drawn as "x" and sounds as a short click; other notes have no "muted" key.
"""
from __future__ import annotations

from guitar_video_app.instruments.fretted import GUITAR_SPEC, Fretted, spec_for_numbering, spec_of
from guitar_video_app.music.lesson import MUSIC_KEYS, VERSION, check_timing, playback, timed_notes
from guitar_video_app.music.tempo import tempo_map

STRING_NUMBERING = GUITAR_SPEC.numbering
PART = 'guitar'


def _position_check(spec: Fretted):
    def check(item):
        string, fret = item['string'], item['fret']
        if (type(string) is not int or not 1 <= string <= spec.strings
                or type(fret) is not int or not 0 <= fret <= spec.max_fret):
            raise ValueError(f'String must be 1-{spec.strings} and fret must be 0-{spec.max_fret}.')
        if item.get('muted', True) is not True:
            raise ValueError('"muted" is true or left out.')
    return check


def view_spec(data: dict) -> Fretted | None:
    """The spec of a V2 view, None when its string numbering is not a known one."""
    return spec_for_numbering(data.get('string_numbering'))


def prepare(data: dict) -> dict:
    """Validated playback data of a V2 lesson (see music.lesson.prepare); notes keep string and fret."""
    spec = view_spec(data)
    if data.get('version') != 2 or spec is None:
        raise ValueError('Expected version 2 with standard guitar string numbering.')
    tempos = tempo_map(data)
    fps = data['fps']
    measure = check_timing(fps, data['time_signature'])
    string = lambda note: note['string']
    notes = timed_notes(data['notes'], tempos, fps, string, _position_check(spec), 'string')
    return playback(notes, tempos, fps, measure, data.get('end_beat'), string, string)


def new_part(spec: Fretted = GUITAR_SPEC) -> dict:
    return dict(instrument=spec.name, tuning=list(spec.tuning), positions={})


def from_v2(data: dict) -> dict:
    """The V3 lesson of a valid V2 lesson; note order and every field are kept."""
    prepare(data)
    spec = view_spec(data)
    music = {key: data[key] for key in MUSIC_KEYS if key in data}
    part = new_part(spec)
    notes = []
    for note in data['notes']:
        extra = {k: v for k, v in note.items() if k not in ('id', 'string', 'fret', 'start_beat', 'duration_beats')}
        notes.append(dict(id=note['id'], pitch=spec.pitch_of(note['string'], note['fret']),
                          start_beat=note['start_beat'], duration_beats=note['duration_beats'], **extra))
        part['positions'][note['id']] = dict(string=note['string'], fret=note['fret'])
    music['notes'] = notes
    skip = (*MUSIC_KEYS, 'version', 'string_numbering', 'notes', 'instrument', 'tuning')
    lesson = {k: v for k, v in data.items() if k not in skip}
    return dict(version=VERSION, **lesson, music=music, parts={spec.name: part})


def guitar_view(lesson: dict, name: str = PART) -> dict:
    """The V2 lesson of a V3 lesson's music played by its guitar (or bass) part name."""
    music, part = lesson['music'], lesson['parts'][name]
    spec = spec_of(part)
    if part.get('tuning', list(spec.tuning)) != list(spec.tuning):
        raise ValueError('Only standard tuning can be drawn.')
    notes = []
    for note in music['notes']:
        position = part['positions'].get(note['id'])
        if position is None:
            raise ValueError(f"Note {note['id']} has no string and fret.")
        if spec.pitch_of(position['string'], position['fret']) != note['pitch']:
            raise ValueError(f"Note {note['id']}: string {position['string']} fret {position['fret']} "
                             f"does not play MIDI pitch {note['pitch']}.")
        extra = {k: v for k, v in note.items() if k not in ('id', 'pitch', 'start_beat', 'duration_beats')}
        notes.append(dict(id=note['id'], string=position['string'], fret=position['fret'],
                          start_beat=note['start_beat'], duration_beats=note['duration_beats'], **extra))
    fields = {k: v for k, v in lesson.items() if k not in ('version', 'music', 'parts')}
    fields.update((k, v) for k, v in music.items() if k != 'notes')
    fields['string_numbering'] = spec.numbering
    if spec is not GUITAR_SPEC:
        fields.update(instrument=spec.name, tuning=list(spec.tuning))
    order = ('name', 'tempo_bpm', 'tempo_changes', 'fps', 'time_signature', 'string_numbering',
             'instrument', 'tuning', 'end_beat', 'source')
    view = dict(version=2, **{k: fields.pop(k) for k in order if k in fields})
    return dict(view, **fields, notes=notes)


def set_notes(lesson: dict, notes: list[dict], name: str = PART) -> None:
    """Replace the lesson's notes with V2 notes (id, string, fret, start_beat, duration_beats, optional muted)."""
    part = lesson['parts'][name]
    spec, positions = spec_of(part), part['positions']
    lesson['music']['notes'] = []
    for note in notes:
        lesson['music']['notes'].append(dict(id=note['id'], pitch=spec.pitch_of(note['string'], note['fret']),
                                             start_beat=note['start_beat'], duration_beats=note['duration_beats'],
                                             **({'muted': True} if note.get('muted') else {})))
        positions[note['id']] = dict(string=note['string'], fret=note['fret'])


def set_muted(note: dict, muted: bool) -> None:
    """Make a music note a dead note ("x") or a played one."""
    if muted:
        note['muted'] = True
    else:
        note.pop('muted', None)


def set_position(lesson: dict, note: dict, string: int, fret: int, name: str = PART) -> None:
    """Play note on string and fret; its pitch follows."""
    part = lesson['parts'][name]
    note['pitch'] = spec_of(part).pitch_of(string, fret)
    part['positions'][note['id']] = dict(string=string, fret=fret)
