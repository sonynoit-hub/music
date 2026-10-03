"""Check changing a song's time signature: the music layer is re-barred with notes, tempo changes and seconds
kept, playback measures follow it, and the dashboard stores it, re-bars the lesson and camera shots, and uses it
when Generate MIDI fits the timing.

.venv/bin/python scripts/verify_time_signature.py

Runs with a temporary store; nothing is transcribed, rendered or sent.
"""
import asyncio
from fractions import Fraction
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile

import mido

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PITCHES = [40, 45, 50, 55, 59, 64, 59, 55]


def midi_bytes():
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120), time=0))
    for pitch in PITCHES:
        track.append(mido.Message('note_on', note=pitch, velocity=80, time=0))
        track.append(mido.Message('note_off', note=pitch, velocity=0, time=480))
    out = BytesIO()
    midi.save(file=out)
    return out.getvalue()


def music_checks():
    """set_time_signature moves only the bar lines and the end; switching back restores the end."""
    from guitar_video_app.music.lesson import prepare, set_time_signature
    from guitar_video_app.music.tempo import seconds_at, tempo_map
    notes = [dict(id=f'n{i}', pitch=60, start_beat=str(Fraction(i, 2)), duration_beats='1/2') for i in range(31)]
    music = dict(tempo_bpm=100, tempo_changes=[dict(beat='8', bpm=110)], time_signature=[4, 4], end_beat='16',
                 notes=[dict(n) for n in notes])
    before = [float(seconds_at(tempo_map(music), Fraction(n['start_beat']))) for n in music['notes']]
    for signature, end in (([3, 4], '18'), ([6, 8], '18'), ([2, 2], '16'), ([7, 8], '35/2'), ([4, 4], '16')):
        set_time_signature(music, signature)
        assert music['time_signature'] == signature and music['end_beat'] == end, (signature, music['end_beat'])
        assert music['notes'] == notes and music['tempo_changes'] == [dict(beat='8', bpm=110)]
        assert [float(seconds_at(tempo_map(music), Fraction(n['start_beat']))) for n in music['notes']] == before
    for bad in ([3, 5], [0, 4], [4]):
        try:
            set_time_signature(music, bad)
        except ValueError:
            continue
        raise AssertionError(f'{bad} accepted')
    set_time_signature(music, [6, 8])
    played = prepare(music, 60)
    assert played['measure'] == 3 and played['page_beats'] == 6, 'a 6/8 bar is three quarter-note beats'


def dashboard_checks():
    with tempfile.TemporaryDirectory() as store:
        os.environ['GUITAR_DASHBOARD_STORE'] = store
        from fastapi import UploadFile
        from pydantic import ValidationError
        from guitar_video_app.api import dashboard
        from guitar_video_app.api.dashboard import SignatureInput, SongInput, create, song, update_signature, upload

        song_id = create(SongInput(name='Signature test'))['id']
        assert update_signature(song_id, SignatureInput(signature='3/4'))['signature'] == '3/4', 'kept without a lesson'
        update_signature(song_id, SignatureInput(signature='4/4'))
        row = asyncio.run(upload(song_id, 'midi', UploadFile(BytesIO(midi_bytes()), filename='line.mid')))
        starts = [n['start_beat'] for n in json.loads(dashboard.lesson(song_id).body)['music']['notes']]
        assert row['summary']['signature'] == [4, 4] and row['summary']['measures'] == 2, row['summary']

        plan = dict(version=1, shots=[dict(start_bar=1, camera='wide'), dict(start_bar=2, camera='hero')])
        with dashboard.db() as conn:
            conn.execute('UPDATE songs SET camera_shots=? WHERE id=?', (json.dumps(plan), song_id))
        row = update_signature(song_id, SignatureInput(signature='3/4'))
        assert row['signature'] == '3/4' and row['summary']['signature'] == [3, 4] and row['summary']['measures'] == 3
        music = json.loads(dashboard.lesson(song_id).body)['music']
        assert music['time_signature'] == [3, 4] and [n['start_beat'] for n in music['notes']] == starts
        shots = json.loads(song(song_id)['camera_shots'])['shots']
        assert [s['start_bar'] for s in shots] == [1, 2], 'beat 4 is nearest bar 2 of 3/4 (beat 3)'
        assert dashboard.rebar_shots(json.dumps(dict(version=1, shots=[dict(start_bar=b) for b in (1, 2, 3, 9)])),
                                     Fraction(4), Fraction(12), Fraction(24)) == json.dumps(
            dict(version=1, shots=[dict(start_bar=1), dict(start_bar=2)])), 'shots on one bar or past the end drop'

        row = update_signature(song_id, SignatureInput(signature='6/8'))
        assert json.loads(dashboard.lesson(song_id, part='guitar').body)['time_signature'] == [6, 8]
        assert row['summary']['measures'] == 3 and row['synced_revision'] is None

        # Generate MIDI's timing fit bars the fresh transcription in the song's signature, not the MIDI's 4/4.
        update_signature(song_id, SignatureInput(signature='3/4'))
        lesson_path = Path(song(song_id)['json_path'])
        data = json.loads(lesson_path.read_text())
        data['music']['time_signature'] = [4, 4]
        lesson_path.write_text(json.dumps(data))
        dashboard.auto_time_transcription(song_id)
        assert json.loads(lesson_path.read_text())['music']['time_signature'] == [3, 4]
        assert song(song_id)['summary']['signature'] == [3, 4]

        assert update_signature(song_id, SignatureInput(signature='4/4'))['signature'] is None, '4/4 is the default'
        try:
            SignatureInput(signature='3/8')
        except ValidationError:
            pass
        else:
            raise AssertionError('3/8 is not offered')


def main():
    music_checks()
    dashboard_checks()
    print('PASS: time signature: re-barring keeps notes, tempo changes and seconds; 6/8 playback bars; dashboard '
          'stores it, re-bars the lesson and camera shots, and Generate MIDI timing uses it.')


if __name__ == '__main__':
    main()
