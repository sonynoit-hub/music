"""Check a bass song in the dashboard: MIDI import, switching instrument, tab edit limits, tab import, the
render command and Send.

.venv/bin/python scripts/verify_dashboard_bass.py

Runs with a temporary store, a stand-in render process and a stand-in bridge; nothing is rendered or sent.
"""
import asyncio
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import wave

import mido

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Two bars of bass (pitch, start beat): low E up the A minor pentatonic and down again.
LINE = [(28, 0), (33, 1), (36, 2), (38, 3), (40, 4), (43, 5), (45, 6), (40, 7)]


def midi_bytes(notes):
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120), time=0))
    track.append(mido.Message('program_change', program=33, time=0))
    for pitch, _ in notes:
        track.append(mido.Message('note_on', note=pitch, velocity=80, time=0))
        track.append(mido.Message('note_off', note=pitch, velocity=0, time=480))
    out = BytesIO()
    midi.save(file=out)
    return out.getvalue()


def wav_bytes(seconds=5):
    out = BytesIO()
    with wave.open(out, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\0\0' * 8000 * seconds)
    return out.getvalue()


class FakeRender:
    calls = []

    def __init__(self, args, **_):
        FakeRender.calls.append(args)
        self.output = Path(args[args.index('--out') + 1])
        self.stdout = iter(['Frame range: 0-239\n', 'Frame written: 239\n'])

    def wait(self):
        self.output.write_bytes(b'video')
        return 0


def refused(call, *args):
    from fastapi import HTTPException
    try:
        call(*args)
    except HTTPException as exc:
        assert exc.status_code == 400, exc
        return exc.detail
    raise AssertionError(f'{call.__name__} accepted {args}')


def view_of(song_id, part):
    from guitar_video_app.api.dashboard import lesson
    return json.loads(lesson(song_id, part=part).body)


def main():
    with tempfile.TemporaryDirectory() as store:
        os.environ['GUITAR_DASHBOARD_STORE'] = store
        from fastapi import UploadFile
        from guitar_video_app.api import dashboard
        from guitar_video_app.api.dashboard import (InstrumentInput, RenderInput, SongInput, TabNoteEdit, TabNoteNew,
                                                    add_note, create, import_tab, song, update_instrument,
                                                    update_note, upload)
        from guitar_video_app.instruments.fretted import BASS_SPEC

        # Import: a bass song analyses MIDI with the bass's strings; notes below the guitar's low E are kept.
        song_id = create(SongInput(name='Bass test'))['id']
        assert update_instrument(song_id, InstrumentInput(instrument='bass'))['instrument'] == 'bass'
        row = asyncio.run(upload(song_id, 'midi', UploadFile(BytesIO(midi_bytes(LINE)), filename='line.mid')))
        assert row['summary']['notes'] == len(LINE) and row['instrument'] == 'bass', row
        view = view_of(song_id, 'bass')
        assert view['instrument'] == 'bass' and view['tuning'] == [43, 38, 33, 28], view.keys()
        assert [BASS_SPEC.pitch_of(n['string'], n['fret']) for n in view['notes']] == [p for p, _ in LINE]
        assert list(json.loads(dashboard.lesson(song_id).body)['parts']) == ['bass']

        # Tab edits: strings 1-4 on the bass; the pitch follows the bass tuning.
        first = view['notes'][0]['id']
        assert '1-4' in refused(update_note, song_id, TabNoteEdit(note_id=first, string=5, fret=0))
        assert '1-4' in refused(add_note, song_id, TabNoteNew(string=6, fret=3, start_beat='8', duration_beats='1'))
        update_note(song_id, TabNoteEdit(note_id=first, string=4, fret=5))
        music = json.loads(dashboard.lesson(song_id).body)['music']
        assert next(n for n in music['notes'] if n['id'] == first)['pitch'] == 33, 'string 4 fret 5 is A1'
        added = add_note(song_id, TabNoteNew(string=1, fret=2, start_beat='7.5', duration_beats='1/2'))
        assert next(n for n in json.loads(dashboard.lesson(song_id).body)['music']['notes']
                    if n['id'] == added['note_id'])['pitch'] == 45

        # Muted (x) notes: toggled on an existing note, added muted, kept by note Undo (PUT), and toggled off.
        second = view['notes'][1]['id']
        update_note(song_id, TabNoteEdit(note_id=second, string=4, fret=5, muted=True))
        dead = add_note(song_id, TabNoteNew(string=3, fret=0, start_beat='8', duration_beats='1/4', muted=True))
        muted = {n['id'] for n in view_of(song_id, 'bass')['notes'] if n.get('muted')}
        assert muted == {second, dead['note_id']}, muted
        moved = update_note(song_id, TabNoteEdit(note_id=second, string=3, fret=0))
        assert next(n for n in view_of(song_id, 'bass')['notes'] if n['id'] == second).get('muted'), \
            'moving a muted note keeps it muted'
        notes = view_of(song_id, 'bass')['notes']
        dashboard.replace_notes(song_id, dashboard.TabNotes(notes=notes))
        assert {n['id'] for n in view_of(song_id, 'bass')['notes'] if n.get('muted')} == muted
        update_note(song_id, TabNoteEdit(note_id=dead['note_id'], string=3, fret=0, muted=False))
        assert {n['id'] for n in view_of(song_id, 'bass')['notes'] if n.get('muted')} == {second}
        assert moved['revision'] > row['revision']

        # Switching: a line with notes below the guitar's low E cannot move to the guitar; one that fits goes to
        # the guitar and back to the bass with its strings and frets kept.
        assert 'cannot be played on the guitar' in refused(update_instrument, song_id, InstrumentInput(instrument='guitar'))
        assert song(song_id)['instrument'] == 'bass'
        high = create(SongInput(name='Bass up an octave'))['id']
        update_instrument(high, InstrumentInput(instrument='bass'))
        asyncio.run(upload(high, 'midi', UploadFile(BytesIO(midi_bytes([(p + 12, s) for p, s in LINE])),
                                                     filename='high.mid')))
        bass_notes = view_of(high, 'bass')['notes']
        update_instrument(high, InstrumentInput(instrument='guitar'))
        assert 'instrument' not in view_of(high, 'guitar'), 'the guitar view is unchanged'
        assert update_instrument(high, InstrumentInput(instrument='bass'))['changed'] == 0
        assert view_of(high, 'bass')['notes'] == bass_notes
        update_instrument(high, InstrumentInput(instrument='piano'))
        assert 'guitar and bass' in refused(update_note, high, TabNoteEdit(note_id=bass_notes[0]['id'], string=1, fret=0))

        # Tab import: a tab for the other fretted instrument is refused before any audio analysis.
        asyncio.run(upload(song_id, 'wav', UploadFile(BytesIO(wav_bytes()), filename='bass.wav')))
        guitar_tab = json.dumps(dict(instrument='guitar', tempo_bpm=120, notes=[
            dict(string=6, fret=0, start_beat=0, duration_beats=1)])).encode()
        assert 'guitar tab' in refused(import_tab, song_id, guitar_tab, 'guitar.tab.json')

        # Render: the bass scene and the bass view.
        FakeRender.calls.clear()
        real_popen, real_blender = dashboard.subprocess.Popen, dashboard.BLENDER
        dashboard.subprocess.Popen, dashboard.BLENDER = FakeRender, Path(sys.executable)
        try:
            if dashboard.BASS_RENDER_SCENE.exists():
                dashboard.start_render(song_id, RenderInput(mode='test'))
                for _ in range(100):
                    if dashboard.render_job['status'] != 'running':
                        break
                    time.sleep(0.02)
                assert dashboard.render_job['status'] == 'done', dashboard.render_job
                args = FakeRender.calls[0]
                assert args[2] == str(dashboard.BASS_RENDER_SCENE), args
                view_path = Path(args[args.index('--json') + 1])
                assert view_path.name == 'bass_view.json' and json.loads(view_path.read_text())['instrument'] == 'bass'
            else:
                print(f'Skipping the render command: {dashboard.BASS_RENDER_SCENE.name} is not built.')
            real_scene = dashboard.BASS_RENDER_SCENE
            dashboard.BASS_RENDER_SCENE = Path(store) / 'missing-bass.blend'
            try:
                dashboard.start_render(song_id, RenderInput(mode='test'))
                raise AssertionError('a missing bass scene must be reported')
            except dashboard.HTTPException as exc:
                assert exc.status_code == 503 and 'make_bass_scene.py' in exc.detail, exc.detail
            finally:
                dashboard.BASS_RENDER_SCENE = real_scene
        finally:
            dashboard.subprocess.Popen, dashboard.BLENDER = real_popen, real_blender

        # Send: the bridge gets the bass view and the instrument.
        sent = []
        real_bridge = dashboard.bridge
        dashboard.bridge = lambda command, port=8765: sent.append(command) or dict(ok=True, note_count=0)
        try:
            dashboard.send(song_id)
        finally:
            dashboard.bridge = real_bridge
        assert sent[0]['instrument'] == 'bass' and Path(sent[0]['json_path']).name == 'bass_view.json', sent[0]

        # Recording: a bass song is the bass alone by default (the line from the strongest attacks); a full band
        # keeps the lowest line. The guitar has no line options either way.
        from guitar_video_app.api.dashboard import RecordingInput, transcription_setup, update_recording
        assert song(song_id)['recording'] is None and transcription_setup(song(song_id))[0]['line'] == 'attacks'
        assert update_recording(song_id, RecordingInput(recording='band'))['recording'] == 'band'
        options, folder = transcription_setup(song(song_id))
        assert options['line'] == 'lowest' and folder.name == 'generated-midi-bass', (options, folder)
        # Full band, extract bass first: Basic Pitch hears the separated stem, and cleanup gets the stem's
        # attack strength and pitch track.
        assert update_recording(song_id, RecordingInput(recording='stem'))['recording'] == 'stem'
        row = dict(song(song_id), wav_path=str(Path(store) / song_id / 'mix.wav'))
        options, folder = transcription_setup(row)
        assert options['line'] == 'attacks' and options['attack_strength'] == dashboard.STEM_ATTACK_STRENGTH, options
        assert options['pitch'] == str(folder / 'mix_bass.pitch.json'), options
        # Bass style: slap or pick keeps only clear attacks of the stem; fingers (the default) keeps soft ones.
        from guitar_video_app.api.dashboard import BassStyleInput, update_bass_style
        assert update_bass_style(song_id, BassStyleInput(style='slap'))['bass_style'] == 'slap'
        slap = transcription_setup(dict(song(song_id), wav_path=row['wav_path']))[0]
        assert slap['attack_strength'] == dashboard.SLAP_ATTACK_STRENGTH > dashboard.STEM_ATTACK_STRENGTH, slap
        assert update_bass_style(song_id, BassStyleInput(style='fingers'))['bass_style'] is None
        assert transcription_setup(dict(song(song_id), wav_path=row['wav_path']))[0] == options
        heard, real = [], (dashboard.separated_bass, dashboard.transcribe_wav_to_midi)
        dashboard.separated_bass = lambda wav, out, low, high: heard.append(('separate', Path(wav).name, low, high))
        dashboard.transcribe_wav_to_midi = lambda wav, out, **settings: heard.append(('transcribe', Path(wav).name))
        try:
            dashboard.transcribe_song(row, folder, options)
        finally:
            dashboard.separated_bass, dashboard.transcribe_wav_to_midi = real
        assert heard == [('separate', 'mix.wav', 28, 63), ('transcribe', 'mix_bass.wav')], heard
        assert update_recording(song_id, RecordingInput(recording='alone'))['recording'] is None
        assert 'pitch' not in transcription_setup(dict(song(song_id), wav_path=row['wav_path']))[0]
        guitar = create(SongInput(name='Guitar test'))['id']
        assert transcription_setup(song(guitar)) == ({}, Path(store) / guitar / 'generated-midi')

        # Bass only: the bass is separated on request, flagged on the song and served as its own audio, from
        # the folder Generate MIDI with recording 'stem' reuses.
        assert dashboard.public(song(song_id))['bass_stem'] is False
        assert dashboard.audio(song_id).path == song(song_id)['wav_path']
        try:
            dashboard.audio(song_id, stem='bass')
            raise AssertionError('no bass before it is extracted')
        except dashboard.HTTPException as exc:
            assert exc.status_code == 404, exc

        def fake_separate(wav, out, low, high):
            stem_wav, track = dashboard.bass_stem_paths(wav, out)
            stem_wav.parent.mkdir(parents=True, exist_ok=True)
            stem_wav.write_bytes(wav_bytes(1))
            track.write_text('{"times": [], "midi": []}')
        real_separate = dashboard.separated_bass
        dashboard.separated_bass = fake_separate
        try:
            assert dashboard.extract_bass_stem(song_id)['bass_stem'] is True
        finally:
            dashboard.separated_bass = real_separate
        stem_file = dashboard.bass_stem_of(song(song_id))
        assert stem_file.parent == transcription_setup(song(song_id))[1] and stem_file.exists(), stem_file
        assert dashboard.audio(song_id, stem='bass').path == stem_file
        assert '400' not in str(refused(dashboard.extract_bass_stem, guitar)), 'a song without audio is refused'

    print('PASS: dashboard bass song: MIDI import, instrument switching, 4-string tab edits, muted notes, tab import, '
          'render, Send, the recording choice, the bass style and Bass only.')


if __name__ == '__main__':
    main()
