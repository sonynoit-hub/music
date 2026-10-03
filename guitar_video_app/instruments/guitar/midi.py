"""Guitar and bass MIDI: one track, or one track per string for the audio renderer."""
import json
from pathlib import Path

from guitar_video_app.instruments import as_lesson
from guitar_video_app.instruments.fretted import SPECS, spec_of, spec_for_numbering
from guitar_video_app.instruments.guitar.rules import GuitarRules
from guitar_video_app.instruments.guitar.view import guitar_view, prepare
from guitar_video_app.music.midi_export import MUTED_VELOCITY, music_midi, muted_end
from guitar_video_app.music.tempo import seconds_at


def _fretted_part(lesson):
    return next((name, part) for name, part in lesson['parts'].items() if part.get('instrument', name) in SPECS)


def lesson_midi(data, single_track=False, name=None):
    """MIDI of a V2 or V3 guitar (or bass) lesson on its beat grid and tempo map: one track, or one
    track per string."""
    lesson = as_lesson(data)
    part = _fretted_part(lesson)[1]
    spec = spec_of(part)
    title = spec.name.capitalize()
    tracks = (((name or title), 0, None),) if single_track else tuple(
        (f'{title} string {s}', s - 1, s) for s in range(1, spec.strings + 1))
    return music_midi(lesson['music'], lesson['fps'], GuitarRules(part), tracks, spec.program)


def export_lesson(source, destination):
    lesson_v3 = as_lesson(json.loads(Path(source).read_text()))
    data = guitar_view(lesson_v3, _fretted_part(lesson_v3)[0])
    spec = spec_for_numbering(data['string_numbering'])
    lesson = prepare(data)
    midi = lesson_midi(data)
    seconds = lambda position: float(seconds_at(lesson['tempo_map'], position))
    render_notes = [dict(id=note['id'], string=note['string'], pitch=spec.pitch_of(note['string'], note['fret']),
                         start_seconds=seconds(note['start']),
                         **(dict(end_seconds=seconds(muted_end(lesson['tempo_map'], note)), velocity=MUTED_VELOCITY)
                            if note.get('muted') else dict(end_seconds=seconds(note['end']))))
                    for string in range(1, spec.strings + 1) for note in lesson['notes'] if note['string'] == string]
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    midi.save(destination)
    manifest = destination.with_suffix('.audio.json')
    manifest.write_text(json.dumps(dict(duration_seconds=seconds(lesson['end']), program=spec.program,
                                        strings=spec.strings, notes=render_notes),indent=2)+'\n')
    return manifest
