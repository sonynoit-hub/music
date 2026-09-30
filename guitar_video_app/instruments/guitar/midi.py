"""Guitar MIDI: one track, or one track per string for the audio renderer."""
import json
from pathlib import Path

from guitar_video_app.instruments import as_lesson
from guitar_video_app.instruments.guitar import GUITAR_PROGRAM
from guitar_video_app.instruments.guitar.rules import GuitarRules
from guitar_video_app.instruments.guitar.tuning import STANDARD_TUNING
from guitar_video_app.instruments.guitar.view import PART, guitar_view, prepare
from guitar_video_app.music.midi_export import music_midi
from guitar_video_app.music.tempo import seconds_at


def lesson_midi(data, single_track=False, name='Guitar'):
    """MIDI of a V2 or V3 guitar lesson on its beat grid and tempo map: one guitar track, or one
    track per string."""
    lesson = as_lesson(data)
    tracks = ((name, 0, None),) if single_track else tuple((f'Guitar string {s}', s - 1, s) for s in range(1, 7))
    return music_midi(lesson['music'], lesson['fps'], GuitarRules(lesson['parts'][PART]), tracks, GUITAR_PROGRAM)


def export_lesson(source, destination):
    data = guitar_view(as_lesson(json.loads(Path(source).read_text())))
    lesson = prepare(data)
    midi = lesson_midi(data)
    seconds = lambda position: float(seconds_at(lesson['tempo_map'], position))
    render_notes = [dict(id=note['id'], string=note['string'], pitch=STANDARD_TUNING[note['string']] + note['fret'],
                         start_seconds=seconds(note['start']), end_seconds=seconds(note['end']))
                    for string in range(1, 7) for note in lesson['notes'] if note['string'] == string]
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    midi.save(destination)
    manifest = destination.with_suffix('.audio.json')
    manifest.write_text(json.dumps(dict(duration_seconds=seconds(lesson['end']),
                                        notes=render_notes),indent=2)+'\n')
    return manifest
