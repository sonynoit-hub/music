"""Export V2 lessons with the exact same note cutoffs as Blender playback."""
import json
from fractions import Fraction
from pathlib import Path

from guitar_video_app.core.lesson_v2 import prepare, seconds_at
from guitar_video_app.core.note_mapping import STANDARD_TUNING


def export_lesson(source, destination):
    import mido

    data = json.loads(Path(source).read_text())
    lesson = prepare(data)
    midi = mido.MidiFile(type=1, ticks_per_beat=960)
    end_tick = round(lesson['end'] * midi.ticks_per_beat)
    conductor = mido.MidiTrack()
    midi.tracks.append(conductor)
    conductor.append(mido.MetaMessage('time_signature', numerator=data['time_signature'][0], denominator=data['time_signature'][1]))
    last = 0
    for position, _, bpm in lesson['tempo_map']:
        tick = round(position * midi.ticks_per_beat)
        conductor.append(mido.MetaMessage('set_tempo', tempo=round(Fraction(60000000) / bpm), time=tick - last))
        last = tick
    conductor.append(mido.MetaMessage('end_of_track', time=max(0, end_tick - last)))
    render_notes = []
    seconds = lambda position: float(seconds_at(lesson['tempo_map'], position))
    for string in range(1, 7):
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.MetaMessage('track_name', name=f'Guitar string {string}'))
        track.append(mido.Message('program_change', channel=string-1, program=24))
        events = []
        for note in lesson['notes']:
            if note['string'] != string:
                continue
            pitch = STANDARD_TUNING[string] + note['fret']
            events.append((round(note['start']*960), 1, pitch))
            events.append((round(note['end']*960), 0, pitch))
            render_notes.append(dict(id=note['id'],string=string,pitch=pitch,
                                     start_seconds=seconds(note['start']),
                                     end_seconds=seconds(note['end'])))
        last = 0
        for tick, on, pitch in sorted(events):
            track.append(mido.Message('note_on' if on else 'note_off', channel=string-1,
                                      note=pitch, velocity=85 if on else 0, time=tick-last))
            last = tick
        track.append(mido.MetaMessage('end_of_track', time=end_tick-last))
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    midi.save(destination)
    manifest = destination.with_suffix('.audio.json')
    manifest.write_text(json.dumps(dict(duration_seconds=seconds(lesson['end']),
                                        notes=render_notes),indent=2)+'\n')
    return manifest
