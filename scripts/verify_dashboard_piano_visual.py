"""Check the dashboard's piano look: PIANO_VISUAL for Send to Blender and renders, the lesson keyboard unchanged.

.venv/bin/python scripts/verify_dashboard_piano_visual.py

The dashboard part runs with a temporary store, a stand-in bridge and a stand-in render process; it then runs
itself in background Blender on outputs/piano-visual.blend to check the Blender side of Send. Nothing is saved.
"""
import asyncio
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
VISUAL_BLEND = ROOT / 'outputs/piano-visual.blend'


def midi_bytes():
    import mido
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=500000))
    for pitch in (60, 64, 67, 72, 48, 55) * 2:
        track.append(mido.Message('note_on', note=pitch, velocity=80, time=0))
        track.append(mido.Message('note_off', note=pitch, velocity=0, time=480))
    out = BytesIO()
    midi.save(file=out)
    return out.getvalue()


class FakeRender:
    """Stands in for background Blender: reports a frame range and frames, then writes the video file."""
    calls = []

    def __init__(self, args, **_):
        FakeRender.calls.append(args)
        self.output = Path(args[args.index('--out') + 1])
        self.stdout = iter(['Frame range: 0-150\n', 'Frame written: 0\n', 'Frame written: 150\n'])

    def wait(self):
        self.output.write_bytes(b'video')
        return 0

    def terminate(self):
        pass


def render(dashboard, song_id, mode):
    from guitar_video_app.api.dashboard import RenderInput
    FakeRender.calls.clear()
    real = dashboard.subprocess.Popen
    dashboard.subprocess.Popen = FakeRender
    try:
        dashboard.start_render(song_id, RenderInput(mode=mode))
        for _ in range(100):
            if dashboard.render_job['status'] != 'running':
                break
            time.sleep(0.02)
    finally:
        dashboard.subprocess.Popen = real
    assert dashboard.render_job['status'] == 'done', dashboard.render_job
    return FakeRender.calls[0], dict(dashboard.render_job)


def send(dashboard, song_id):
    sent = []
    real = dashboard.bridge
    dashboard.bridge = lambda command, port=8765: sent.append(command) or dict(ok=True, note_count=0)
    try:
        dashboard.send(song_id)
    finally:
        dashboard.bridge = real
    return sent[0]


def dashboard_checks():
    with tempfile.TemporaryDirectory() as store:
        os.environ['GUITAR_DASHBOARD_STORE'] = store
        from fastapi import UploadFile
        from guitar_video_app.api import dashboard
        from guitar_video_app.api.dashboard import (InstrumentInput, PianoLookInput, SongInput, create,
                                                    update_instrument, update_piano_look, upload)
        song_id = create(SongInput(name='Plume test'))['id']
        update_instrument(song_id, InstrumentInput(instrument='piano'))
        asyncio.run(upload(song_id, 'midi', UploadFile(BytesIO(midi_bytes()), filename='notes.mid')))
        wav = Path(store) / 'tone.wav'
        with wave.open(str(wav), 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(8000)
            out.writeframes(b'\0\0' * 8000 * 4)
        row = asyncio.run(upload(song_id, 'wav', UploadFile(BytesIO(wav.read_bytes()), filename='tone.wav')))
        assert row['piano_look'] is None, 'new songs use the lesson keyboard'

        lesson_command = send(dashboard, song_id)
        assert 'piano_look' not in lesson_command and lesson_command['instrument'] == 'piano'
        args, _ = render(dashboard, song_id, 'test')
        assert str(dashboard.PIANO_RENDER_SCENE) in args and str(dashboard.RENDER_SCRIPT) in args

        revision = row['revision']
        row = update_piano_look(song_id, PianoLookInput(look='visual'))
        assert row['piano_look'] == 'visual' and row['revision'] == revision + 1
        assert update_piano_look(song_id, PianoLookInput(look='visual'))['revision'] == revision + 1, 'no-op change'
        command = send(dashboard, song_id)
        assert command['piano_look'] == 'visual' and command['json_path'].endswith('piano_view.json')
        assert command['piano_effect'] == 'notes', 'the particle stage shows notes by default'

        args, job = render(dashboard, song_id, 'test')
        assert str(VISUAL_BLEND) in args and str(dashboard.PIANO_VISUAL_SCRIPT) in args, args
        assert args[args.index('--effect') + 1] == 'notes', args
        assert args[args.index('--end') + 1] == str(dashboard.RENDER_FPS * dashboard.RENDER_TEST_SECONDS - 1)
        assert all(o in args for o in dashboard.PIANO_VISUAL_TEST_OPTIONS), 'test render is not a draft'
        assert not any(a.startswith('--title') or a.startswith('--style') for a in args)
        args, job = render(dashboard, song_id, 'full')
        assert '--end' not in args and '--scale' not in args and '--samples' not in args, args
        assert job['frame_end'] == 150, 'the frame range reported by the render script was not used'

        row = update_piano_look(song_id, PianoLookInput(look='plumes'))
        assert row['piano_look'] == 'plumes'
        command = send(dashboard, song_id)
        assert command['piano_look'] == 'visual' and command['piano_effect'] == 'plumes', command
        args, _ = render(dashboard, song_id, 'test')
        assert str(VISUAL_BLEND) in args and args[args.index('--effect') + 1] == 'plumes', args

        update_instrument(song_id, InstrumentInput(instrument='guitar'))
        assert 'piano_look' not in send(dashboard, song_id), 'guitar songs ignore the piano look'
        update_instrument(song_id, InstrumentInput(instrument='piano'))
        row = update_piano_look(song_id, PianoLookInput(look='lesson'))
        assert row['piano_look'] is None and 'piano_look' not in send(dashboard, song_id)

        update_piano_look(song_id, PianoLookInput(look='visual'))
        view = Path(send(dashboard, song_id)['json_path'])
        blender = subprocess.run([str(dashboard.BLENDER), '-b', str(VISUAL_BLEND), '--factory-startup',
                                  '--python-exit-code', '1', '--python', str(Path(__file__).resolve()), '--',
                                  '--blender', str(view), str(wav)], capture_output=True, text=True)
        result = [line for line in blender.stdout.splitlines() if line.startswith('BLENDER PASS')]
        if blender.returncode or not result:
            print(blender.stdout[-3000:], blender.stderr[-3000:])
            raise SystemExit('Blender side failed')
        return result[0]


def blender_checks(view, wav):
    import bpy
    from guitar_video_app.integrations import dashboard_bridge
    from guitar_video_app.integrations import piano_visual_particles as visual

    before = hashlib.sha256(VISUAL_BLEND.read_bytes()).hexdigest()
    scene = bpy.context.scene
    command = dict(command='dashboard_sync', json_path=view, wav_path=wav, song_id='plume-test', revision=3,
                   offset_seconds=0.5, instrument='piano', piano_look='visual', timeout=60)
    result = dashboard_bridge.sync(command)
    notes = len(json.loads(Path(view).read_text())['notes'])
    assert result['ok'] and result['note_count'] == notes, result
    events = bpy.data.objects[visual.OBJECT]
    assert len(events.data.vertices) == notes, 'one event point per note'
    assert scene[visual.EFFECT_PROPERTY] == 'notes', 'the particle stage shows notes by default'
    audio = [s for s in scene.sequence_editor.strips if s.type == 'SOUND']
    assert [s.name for s in audio] == ['Lesson_JSON_Guitar_Audio'], [s.name for s in audio]
    assert audio[0].frame_start == round(0.5 * scene.render.fps), 'audio offset'
    assert scene['Dashboard_Song_ID'] == 'plume-test' and scene['Dashboard_Revision'] == 3
    assert 'start_bridge()' in bpy.data.texts[visual.LOADER].as_string(), 'the bridge would not restart on load'

    real_install = visual.install

    def failing(data, effect='notes'):
        real_install(data, effect=effect)
        if len(data['notes']) == 2:
            raise RuntimeError('install failed')
    shorter = json.loads(Path(view).read_text())
    shorter['notes'] = shorter['notes'][:2]
    other = Path(view).with_name('shorter_view.json')
    other.write_text(json.dumps(shorter))
    visual.install = failing
    try:
        dashboard_bridge.sync(dict(command, json_path=str(other), revision=4, piano_effect='plumes'))
        raise AssertionError('a failed install should raise')
    except RuntimeError:
        pass
    finally:
        visual.install = real_install
    assert len(bpy.data.objects[visual.OBJECT].data.vertices) == notes, 'previous lesson not restored'
    assert scene[visual.EFFECT_PROPERTY] == 'notes', 'previous effect not restored'
    assert scene['Dashboard_Revision'] == 3
    assert len([s for s in scene.sequence_editor.strips if s.type == 'SOUND']) == 1, 'pending audio left behind'
    assert dashboard_bridge.sync(dict(command, revision=5, piano_effect='plumes'))['ok']
    assert scene[visual.EFFECT_PROPERTY] == 'plumes', 'plumes were not sent'

    try:
        dashboard_bridge.sync({k: v for k, v in command.items() if k != 'piano_look'})
        raise AssertionError('the lesson look needs the lesson piano scene')
    except ValueError as exc:
        assert 'piano-vertical.blend' in str(exc), exc
    assert hashlib.sha256(VISUAL_BLEND.read_bytes()).hexdigest() == before, '.blend changed'
    print(f'BLENDER PASS: sent {notes} notes to PIANO_VISUAL (rising notes, then plumes) with audio at +0.5 s, a '
          'failed send restored the previous lesson and effect, the lesson look asks for piano-vertical.blend, the '
          '.blend was not saved')


if __name__ == '__main__':
    if '--blender' in sys.argv:
        blender_checks(*sys.argv[sys.argv.index('--blender') + 1:][:2])
    else:
        blender = dashboard_checks()
        print('PASS: piano look saved per song (revision bumps once); Send carries piano_look and the effect '
              '(notes by default, or plumes) only for piano songs on the particle stage; test render is a half-size '
              'PIANO_VISUAL draft to frame 119, full render runs to the reported end; lesson look and guitar '
              'unchanged. ' + blender)
