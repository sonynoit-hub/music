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
    """Stands in for background Blender: reports a frame range and frames, then writes the video file (or the
    layer / reference folder)."""
    calls = []

    def __init__(self, args, **_):
        FakeRender.calls.append(args)
        self.output = Path(args[args.index('--out') + 1])
        self.folder = '--layers' in args or '--reference-frames' in args
        if '--reference-frames' in args:
            self.stdout = iter(['Reference written: shot 1 (bar 1, hero)\n', 'Reference written: shot 2 (bar 2, close)\n'])
        else:
            layers = ['Layer 1/2: instrument\n', 'Frame written: 150\n', 'Layer 2/2: notes\n'] if self.folder else []
            self.stdout = iter(['Frame range: 0-150\n', *layers, 'Frame written: 0\n', 'Frame written: 150\n'])

    def wait(self):
        if self.folder:
            self.output.mkdir(parents=True)
            (self.output / 'frame_0000.png').write_bytes(b'png')
        else:
            self.output.write_bytes(b'video')
        return 0

    def terminate(self):
        pass


def render(dashboard, song_id, mode, start_bar=None):
    from guitar_video_app.api.dashboard import RenderInput
    FakeRender.calls.clear()
    real = dashboard.subprocess.Popen
    dashboard.subprocess.Popen = FakeRender
    try:
        dashboard.start_render(song_id, RenderInput(mode=mode, start_bar=start_bar))
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


def refused(call, *args):
    from fastapi import HTTPException
    try:
        call(*args)
    except HTTPException as exc:
        assert exc.status_code == 400, exc
        return exc.detail
    raise AssertionError(f'{call.__name__} accepted {args}')


def camera_checks(dashboard, song_id):
    """Camera shots: NULL is today's single wide view; saved shots go to Send and the render; Auto and Delete."""
    from guitar_video_app.api.dashboard import CameraShotsInput, song
    from guitar_video_app.instruments.piano.camera import bar_seconds
    reply = dashboard.get_camera(song_id)
    assert reply['camera_shots'] is None and reply['song']['camera_shots'] is None, 'new songs use the wide view'
    assert reply['bars'] == 3 and reply['measure_beats'] == 4 and 'hero' in reply['cameras'], reply
    assert send(dashboard, song_id)['camera_shots'] is None
    args, _ = render(dashboard, song_id, 'test')
    assert '--camera' not in args and args[args.index('--start') + 1] == '0', 'NULL must render as before'

    revision = song(song_id)['revision']
    plan = dict(version=1, shots=[dict(start_bar=1, camera='hero', move='drift', transition='cut'),
                                  dict(start_bar=2, camera='close', move='push', transition='blend')])
    reply = dashboard.put_camera(song_id, CameraShotsInput(**plan))
    assert reply['camera_shots'] == plan and reply['song']['revision'] == revision + 1, reply
    assert dashboard.put_camera(song_id, CameraShotsInput(**plan))['song']['revision'] == revision + 1, 'no-op'
    for bad in (dict(version=1, shots=[dict(start_bar=2, camera='hero')]),
                dict(version=1, shots=[dict(start_bar=1, camera='hero'), dict(start_bar=4, camera='wide')]),
                dict(version=1, shots=[dict(start_bar=1, camera='drone')]),
                dict(version=1, shots=[dict(start_bar=1, camera='hero'), dict(start_bar=1, camera='wide')])):
        refused(dashboard.put_camera, song_id, CameraShotsInput(**bad))
    assert dashboard.get_camera(song_id)['camera_shots'] == plan, 'a refused list must not change the shots'
    assert send(dashboard, song_id)['camera_shots'] == plan
    args, job = render(dashboard, song_id, 'test')
    shots_file = Path(args[args.index('--camera') + 1])
    assert shots_file.name == 'camera_shots.json' and shots_file.parent == Path(args[args.index('--json') + 1]).parent
    assert json.loads(shots_file.read_text()) == plan

    args, job = render(dashboard, song_id, 'test', start_bar=2)
    prepared = dashboard.camera_lesson(song(song_id))
    start = round(bar_seconds(prepared, 2) * dashboard.RENDER_FPS)
    assert args[args.index('--start') + 1] == str(start), args
    assert args[args.index('--end') + 1] == str(start + dashboard.RENDER_FPS * dashboard.RENDER_TEST_SECONDS - 1)
    assert 'past the end' in refused(render, dashboard, song_id, 'test', 9)

    revision = song(song_id)['revision']
    auto = dashboard.auto_camera(song_id)
    assert auto['camera_shots']['shots'][0]['start_bar'] == 1 and auto['song']['revision'] == revision + 1
    assert dashboard.auto_camera(song_id)['camera_shots'] == auto['camera_shots'], 'Auto must be deterministic'
    reply = dashboard.delete_camera(song_id)
    assert reply['camera_shots'] is None and reply['song']['revision'] == revision + 2
    args, _ = render(dashboard, song_id, 'test')
    assert '--camera' not in args and not shots_file.exists(), 'Delete must go back to the wide view'
    dashboard.put_camera(song_id, CameraShotsInput(**plan))


def compositing_checks(dashboard, song_id):
    """Test and full stay MP4 previews; layers and reference frames are folders with their own progress."""
    for mode in ('test', 'full'):
        args, job = render(dashboard, song_id, mode)
        assert job['format'] == 'mp4' and job['output'].endswith('.mp4'), job
        assert not {'--layers', '--reference-frames', '--passes'} & set(args), args
    assert str(dashboard.render_video().path).endswith('.mp4')

    args, job = render(dashboard, song_id, 'layers')
    assert '--layers' in args and '--end' not in args and '--scale' not in args, 'layers are the whole song, full size'
    assert args[args.index('--samples') + 1] == '32' and '--camera' in args, args
    output = Path(args[args.index('--out') + 1])
    assert output.name == 'Plume test layers' and job['format'] == 'folder' and output.is_dir(), job
    assert (job['part'], job['parts'], job['part_name']) == (2, 2, 'notes'), job
    assert 'Show in Finder' in refused(dashboard.render_video)
    opened = []
    real = dashboard.subprocess.run
    dashboard.subprocess.run = lambda command, **_: opened.append(command)
    try:
        assert dashboard.reveal_render()['path'] == str(output)
    finally:
        dashboard.subprocess.run = real
    assert opened == [['open', str(output)]], opened
    args, job = render(dashboard, song_id, 'layers')
    assert Path(args[args.index('--out') + 1]).name == 'Plume test layers 2', 'an earlier layer render was replaced'

    args, job = render(dashboard, song_id, 'reference')
    assert '--reference-frames' in args and '--layers' not in args and '--camera' in args, args
    assert Path(args[args.index('--out') + 1]).name == 'Plume test reference' and job['format'] == 'folder'
    assert (job['part'], job['parts']) == (2, 2), job


def dashboard_checks():
    with tempfile.TemporaryDirectory() as store:
        os.environ['GUITAR_DASHBOARD_STORE'] = store
        from fastapi import UploadFile
        from guitar_video_app.api import dashboard
        from guitar_video_app.api.dashboard import (InstrumentInput, PianoColorsInput, PianoLookInput, SongInput,
                                                    create, song, update_instrument, update_piano_colors,
                                                    update_piano_look, upload)
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
        for mode in dashboard.COMPOSITING_MODES:
            assert 'piano stage' in refused(render, dashboard, song_id, mode), 'compositing needs PIANO_VISUAL'

        revision = row['revision']
        row = update_piano_look(song_id, PianoLookInput(look='visual'))
        assert row['piano_look'] == 'visual' and row['revision'] == revision + 1
        assert update_piano_look(song_id, PianoLookInput(look='visual'))['revision'] == revision + 1, 'no-op change'
        command = send(dashboard, song_id)
        assert command['piano_look'] == 'visual' and command['json_path'].endswith('piano_view.json')
        assert command['piano_effect'] == 'notes', 'the particle stage shows notes by default'
        assert command['piano_colors'] == 'blue', 'notes are blue by default'

        args, job = render(dashboard, song_id, 'test')
        assert str(VISUAL_BLEND) in args and str(dashboard.PIANO_VISUAL_SCRIPT) in args, args
        assert args[args.index('--effect') + 1] == 'notes' and args[args.index('--colors') + 1] == 'blue', args
        revision = song(song_id)['revision']
        row = update_piano_colors(song_id, PianoColorsInput(colors='hands'))
        assert row['piano_colors'] == 'hands' and row['revision'] == revision + 1
        assert send(dashboard, song_id)['piano_colors'] == 'hands'
        args, _ = render(dashboard, song_id, 'test')
        assert args[args.index('--colors') + 1] == 'hands', args
        assert update_piano_colors(song_id, PianoColorsInput(colors='blue'))['piano_colors'] is None
        assert args[args.index('--end') + 1] == str(dashboard.RENDER_FPS * dashboard.RENDER_TEST_SECONDS - 1)
        assert all(o in args for o in dashboard.PIANO_VISUAL_TEST_OPTIONS), 'test render is not a draft'
        assert not any(a.startswith('--title') or a.startswith('--style') for a in args)
        args, job = render(dashboard, song_id, 'full')
        assert '--end' not in args and '--scale' not in args, 'the full render is the whole song at full size'
        assert args[args.index('--samples') + 1] == '32', args
        assert job['frame_end'] == 150, 'the frame range reported by the render script was not used'
        camera_checks(dashboard, song_id)
        compositing_checks(dashboard, song_id)

        row = update_piano_look(song_id, PianoLookInput(look='plumes'))
        assert row['piano_look'] == 'plumes'
        command = send(dashboard, song_id)
        assert command['piano_look'] == 'visual' and command['piano_effect'] == 'plumes', command
        args, _ = render(dashboard, song_id, 'test')
        assert str(VISUAL_BLEND) in args and args[args.index('--effect') + 1] == 'plumes', args

        assert send(dashboard, song_id)['camera_shots']['shots'][1]['camera'] == 'close', 'plumes keep the shots'
        update_instrument(song_id, InstrumentInput(instrument='guitar'))
        assert 'piano_look' not in send(dashboard, song_id), 'guitar songs ignore the piano look'
        assert 'piano songs' in refused(dashboard.get_camera, song_id)
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
    from guitar_video_app.integrations import piano_visual as pv
    from guitar_video_app.integrations import piano_visual_camera as shot_camera
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
    assert scene.sync_mode == 'AUDIO_SYNC', 'viewport playback should keep time with the WAV'
    assert scene['Dashboard_Song_ID'] == 'plume-test' and scene['Dashboard_Revision'] == 3
    assert 'start_bridge()' in bpy.data.texts[visual.LOADER].as_string(), 'the bridge would not restart on load'
    presentation = bpy.data.objects[pv.CAMERA_OBJECT]
    assert scene.camera == presentation and shot_camera.CAMERA not in bpy.data.objects, 'no shots: the wide view'
    plan = dict(version=1, shots=[dict(start_bar=1, camera='hero', move='drift', transition='cut'),
                                  dict(start_bar=2, camera='close', move='push', transition='blend')])
    command['camera_shots'] = plan
    assert dashboard_bridge.sync(command)['ok']
    assert scene.camera.name == shot_camera.CAMERA and shot_camera.shots() == plan, 'shots were not sent'

    real_install = visual.install

    def failing(data, effect='notes', colors='blue', camera=None):
        real_install(data, effect=effect, colors=colors, camera=camera)
        if len(data['notes']) == 2:
            raise RuntimeError('install failed')
    shorter = json.loads(Path(view).read_text())
    shorter['notes'] = shorter['notes'][:2]
    other = Path(view).with_name('shorter_view.json')
    other.write_text(json.dumps(shorter))
    visual.install = failing
    try:
        dashboard_bridge.sync(dict(command, json_path=str(other), revision=4, piano_effect='plumes',
                                   piano_colors='gold', camera_shots=dict(version=1, shots=[
                                       dict(start_bar=1, camera='side')])))
        raise AssertionError('a failed install should raise')
    except RuntimeError:
        pass
    finally:
        visual.install = real_install
    assert len(bpy.data.objects[visual.OBJECT].data.vertices) == notes, 'previous lesson not restored'
    assert scene[visual.EFFECT_PROPERTY] == 'notes', 'previous effect not restored'
    assert scene[visual.COLORS_PROPERTY] == 'blue', 'previous colours not restored'
    assert shot_camera.shots() == plan and scene.camera.name == shot_camera.CAMERA, 'previous shots not restored'
    assert scene['Dashboard_Revision'] == 3
    assert len([s for s in scene.sequence_editor.strips if s.type == 'SOUND']) == 1, 'pending audio left behind'
    assert dashboard_bridge.sync(dict(command, revision=5, piano_effect='plumes', piano_colors='hands',
                                      camera_shots=None))['ok']
    assert scene[visual.EFFECT_PROPERTY] == 'plumes', 'plumes were not sent'
    assert scene[visual.COLORS_PROPERTY] == 'hands', 'colours were not sent'
    assert scene.camera == presentation and shot_camera.CAMERA not in bpy.data.objects, 'NULL shots: the wide view'
    assert pv.CAMERA_OBJECT in bpy.data.objects and presentation.data.lens == 35, 'presentation camera changed'

    try:
        dashboard_bridge.sync({k: v for k, v in command.items() if k != 'piano_look'})
        raise AssertionError('the lesson look needs the lesson piano scene')
    except ValueError as exc:
        assert 'piano-vertical.blend' in str(exc), exc
    assert hashlib.sha256(VISUAL_BLEND.read_bytes()).hexdigest() == before, '.blend changed'
    print(f'BLENDER PASS: sent {notes} notes to PIANO_VISUAL (rising notes, then plumes) with audio at +0.5 s '
          'and playback synced to it, '
          'camera shots on the shot camera and NULL back on the presentation camera, a failed send restored the '
          'previous lesson, effect, colours and shots, the lesson look asks for piano-vertical.blend, the .blend '
          'was not saved')


if __name__ == '__main__':
    if '--blender' in sys.argv:
        blender_checks(*sys.argv[sys.argv.index('--blender') + 1:][:2])
    else:
        blender = dashboard_checks()
        print('PASS: piano look saved per song (revision bumps once); Send carries piano_look, the effect (notes '
              'by default, or plumes) and note colours (blue by default) only for piano songs on the particle stage; '
              'test render is a half-size PIANO_VISUAL draft to frame 119 (or 4 s from a shot\'s bar), full render '
              'runs at full size and 32 samples to the reported end; camera shots (NULL is the wide view) are checked, saved with one revision '
              'bump, suggested by Auto, deleted, sent and passed to the render as camera_shots.json; test and full '
              'stay MP4, layers (whole song, 32 samples) and reference frames render to numbered folders with '
              'progress per layer or shot and Show in Finder, and are refused for the lesson look; lesson look and '
              'guitar unchanged. ' + blender)
