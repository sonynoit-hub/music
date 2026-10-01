"""The PIANO_VISUAL camera planner without Blender: Auto shots on bar lines within the length limits, deterministic
and without repeated presets, cuts where the music jumps, the focus's dead zone and speed limit, every sounding key
inside the 9:16 safe box, bars from the tempo map, and the shot list validation errors.

.venv/bin/python scripts/verify_piano_camera.py
"""
import copy
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from guitar_video_app.instruments.piano import camera
from guitar_video_app.instruments.piano.view import prepare

FPS = 30
SLACK = 1e-9


def song(notes, tempo_changes=None):
    data = dict(version=1, instrument='piano', name='Camera check', fps=FPS, tempo_bpm=120, time_signature=[4, 4],
                notes=notes)
    if tempo_changes:
        data['tempo_changes'] = tempo_changes
    return prepare(data)


def long_song():
    """36 bars: a busy middle-register run, a sustained melody two octaves up from bar 13 and two hands far
    apart from bar 21, with a slower tempo from bar 25."""
    notes = []
    for b in range(36):
        if b < 12:
            notes += [dict(id=f'a{b}{k}', pitch=60 + (k * 2) % 7, hand='right', start_beat=b * 4 + k * 0.5,
                           duration_beats=0.5) for k in range(8)]
        elif b < 20:
            notes.append(dict(id=f'h{b}', pitch=84 + b % 3, hand='right', start_beat=b * 4, duration_beats=4))
        else:
            notes += [dict(id=f'l{b}', pitch=36, hand='left', start_beat=b * 4, duration_beats=2),
                      dict(id=f'r{b}', pitch=79, hand='right', start_beat=b * 4 + 1, duration_beats=1)]
    return song(notes, [dict(beat=96, bpm=90)])


def short_song():
    """Six bars of chords and single notes around middle C, like the PIANO_VISUAL demo."""
    notes = []
    for b in range(5):
        notes += [dict(id=f'c{b}{p}', pitch=p, hand='left' if p < 60 else 'right', start_beat=b * 4 + 1,
                       duration_beats=1.5) for p in (48, 55, 60, 64)]
        notes.append(dict(id=f'm{b}', pitch=67 + b, hand='right', start_beat=b * 4 + 3, duration_beats=1))
    return song(notes)


def spans(lesson, plan):
    starts = [s['start_bar'] for s in plan['shots']]
    end = float(camera.seconds_at(lesson['tempo_map'], lesson['end']))
    times = [camera.bar_seconds(lesson, b) for b in starts] + [end]
    return [(b, nxt, times[i + 1] - times[i]) for i, (b, nxt) in
            enumerate(zip(starts, starts[1:] + [camera.bar_count(lesson) + 1]))]


def auto_checks(lesson, name):
    plan = camera.auto_shots(lesson)
    assert camera.auto_shots(copy.deepcopy(lesson)) == plan, 'Auto must be deterministic'
    assert camera.validate(plan, lesson) == plan
    shots = plan['shots']
    assert shots[0]['start_bar'] == 1 and shots[0]['camera'] in ('wide', 'hero')
    if len(shots) > 1:
        assert shots[-1]['camera'] == 'wide'
    for a, b in zip(shots, shots[1:]):
        assert a['camera'] != b['camera'], f'{name}: {a["camera"]} twice in a row'
    measure_seconds = [camera.bar_seconds(lesson, b + 1) - camera.bar_seconds(lesson, b)
                       for b in range(1, camera.bar_count(lesson))]
    longest_bar = max(measure_seconds, default=0)
    for first, after, seconds in spans(lesson, plan):
        assert after - first >= camera.MIN_BARS and seconds >= camera.MIN_SECONDS - SLACK, (name, first, seconds)
        assert seconds <= camera.MAX_SECONDS + 2 * longest_bar, (name, first, seconds)
    sides = [camera.bar_seconds(lesson, s['start_bar']) for s in shots if s['camera'] == 'side']
    assert all(b - a >= camera.SIDE_GAP for a, b in zip(sides, sides[1:]))
    return plan


def safe_box_checks(lesson, plan):
    """Every sounding key's spawn point stays in the safe box on every frame outside blends."""
    path = camera.CameraPath(lesson, plan)
    keys = camera.timed_keys(lesson)
    checked = 0
    for frame in range(round(keys[-1][1] * FPS)):
        t = frame / FPS
        i = path.shot_index(t)
        shot = path.shots[i]
        if path.blending(t):
            continue
        state = path.frame_state(frame)
        for x in camera._sounding(keys, t, t + 1e-4):
            spot = camera.project(state, (x, camera.KEY_MID, 0.015))
            assert camera.inside(spot), (frame, shot.camera, x, spot)
            checked += 1
    return path, checked


def cut_checks(lesson, path):
    """A cut changes the camera exactly on the frame nearest its bar's downbeat, from the tempo map."""
    for shot, start_bar in zip(path.shots[1:], [s['start_bar'] for s in path.plan['shots'][1:]]):
        frame = round(camera.bar_seconds(lesson, start_bar) * FPS)
        assert abs(shot.start - frame / FPS) < SLACK
        before, at = path.frame_state(frame - 1), path.frame_state(frame)
        assert path.shot_index((frame - 1) / FPS) == path.shot_index(frame / FPS) - 1
        if shot.transition == 'cut':
            assert at == shot.state(frame / FPS) and before != at
    again = camera.CameraPath(lesson, path.plan)
    assert all(again.frame_state(f) == path.frame_state(f) for f in range(0, 600, 7))


def blend_checks(lesson):
    """Blends orbit and glide: longer for bigger moves, no whip, and no kick at their start or end."""
    plan = dict(version=1, shots=[dict(start_bar=1, camera='along', move='static'),
                                  dict(start_bar=9, camera='high', move='static', transition='blend'),
                                  dict(start_bar=17, camera='close', move='static', transition='blend'),
                                  dict(start_bar=25, camera='hero', move='push', transition='blend')])
    path = camera.CameraPath(lesson, plan)
    assert path.blends[1] == camera.BLEND_MAX and min(path.blends[1:]) >= camera.BLEND_SECONDS, path.blends
    same = path.shots[3].state(path.shots[3].start)
    assert camera.blend_length(same, same, 10.0) == camera.BLEND_SECONDS, 'A blend that barely moves stays short'
    fps = 60
    spots = [path.camera_at(f / fps)['location'] for f in range(round(path.shots[-1].end * fps))]
    step = lambda a: [tuple((y - x) * fps for x, y in zip(p, q)) for p, q in zip(a, a[1:])]
    size = lambda v: math.sqrt(sum(c * c for c in v))
    speed, accel = step(spots), step(step(spots))
    top, kick = max(map(size, speed)), max(map(size, accel))
    assert top < 3.0 and kick < 6.0, (top, kick)
    for shot, length in zip(path.shots[1:], path.blends[1:]):
        for edge in (shot.start, shot.start + length):
            f = round(edge * fps)
            assert size(accel[f - 2]) < 0.5 and size(accel[f]) < 0.5, ('blend must glide in and out', edge)
    return top, kick


def focus_checks():
    width = camera.PRESETS['hero']['octaves'] * camera.OCTAVE
    still = [(0.0, 10.0, 0.0), (2.0, 10.0, camera.DEAD_ZONE * 0.9)]
    path = camera.focus_path(still, 0.0, 6.0, width)
    assert max(path) - min(path) < 1e-9, 'Inside the dead zone the focus must not move'
    jump = [(0.0, 2.0, -0.3), (2.0, 12.0, 0.3)]
    path = camera.focus_path(jump, 0.0, 10.0, width)
    speeds = [(b - a) / camera.STEP for a, b in zip(path, path[1:])]
    top = camera.SPEED_SHARE * width
    assert max(abs(s) for s in speeds) <= top + 1e-9, max(speeds)
    accel = top / camera.EASE_SECONDS
    assert all(abs(b - a) / camera.STEP <= accel + 1e-6 for a, b in zip(speeds, speeds[1:])), 'Speed must ease'
    assert speeds[0] == 0 and abs(speeds[-1]) < 1e-3, 'The focus must start and stop gently'
    assert abs(path[-1] - 0.3) <= camera.SETTLE_SHARE * camera.DEAD_ZONE + 1e-3, path[-1]
    early = next(i for i, s in enumerate(speeds) if s > 0) * camera.STEP
    assert early < 2.0, 'The focus must lean towards coming notes'
    return top


def validation_checks(lesson):
    good = dict(version=1, shots=[dict(start_bar=1, camera='hero', move='drift', transition='cut'),
                                  dict(start_bar=3, camera='close')])
    checked = camera.validate(good, lesson)
    assert checked['shots'][1] == dict(start_bar=3, camera='close', move='static', transition='cut')
    bad = [
        (dict(version=2, shots=good['shots']), 'version 1'),
        (dict(version=1, shots=[]), 'at least one'),
        (dict(version=1, shots=[dict(start_bar=2, camera='hero')]), 'bar 1'),
        (dict(version=1, shots=[dict(start_bar=1, camera='hero'), dict(start_bar=1, camera='wide')]), 'rising'),
        (dict(version=1, shots=[dict(start_bar=1, camera='hero'), dict(start_bar=99, camera='wide')]), 'from 1 to'),
        (dict(version=1, shots=[dict(start_bar=1.0, camera='hero')]), 'from 1 to'),
        (dict(version=1, shots=[dict(start_bar=True, camera='hero')]), 'from 1 to'),
        (dict(version=1, shots=[dict(start_bar=1, camera='drone')]), 'camera must'),
        (dict(version=1, shots=[dict(start_bar=1, camera='hero', move='zoom')]), 'move must'),
        (dict(version=1, shots=[dict(start_bar=1, camera='hero', transition='wipe')]), 'transition must'),
        (dict(version=1, shots=[dict(start_bar=1, camera='hero', lens=50)]), 'expected only'),
        (dict(version=1, shots=good['shots'], extra=1), 'version 1'),
    ]
    for plan, message in bad:
        try:
            camera.validate(plan, lesson)
        except ValueError as exc:
            assert message in str(exc), (message, str(exc))
        else:
            raise AssertionError(f'Accepted a bad shot list: {plan}')
    return len(bad)


def preset_checks():
    """Every preset fits its own span: the keys sit above the captions and the notes rise above them."""
    for name, preset in camera.PRESETS.items():
        width = preset['octaves'] * camera.OCTAVE
        distance = camera.framing_distance(name, width)
        state = camera._state(name, 0.0, preset['azimuth'], distance)
        assert all(camera.inside(camera.project(state, p)) for p in camera.framing_points(0.0, width)), name
        keys = camera.project(state, (0.0, camera.KEY_MID, 0.0))
        rise = camera.project(state, (0.0, camera.KEY_MID, camera.RISE_SHOWN))
        assert camera.SAFE_BOX['bottom'] <= keys[1] < 0.45 and rise[1] > keys[1] + 0.2, (name, keys, rise)
    wide = camera.CameraPath(short_song(), dict(version=1, shots=[dict(start_bar=1, camera='wide')]))
    state = wide.camera_at(1.0)
    assert all(abs(a - b) < 1e-9 for a, b in zip(state['location'], camera.WIDE_LOCATION))
    assert state['target'] == camera.WIDE_TARGET and state['lens'] == camera.WIDE_LENS


def main():
    preset_checks()
    long, short = long_song(), short_song()
    assert abs(camera.bar_seconds(long, 26) - (48 + 4 * 60 / 90)) < 1e-9, 'Bars must follow the tempo map'
    plan = auto_checks(long, 'long')
    starts = [s['start_bar'] for s in plan['shots']]
    assert 13 in starts, f'The jump up two octaves at bar 13 must start a shot: {starts}'
    assert 'side' in [s['camera'] for s in plan['shots']]
    short_plan = auto_checks(short, 'short')
    path, checked = safe_box_checks(long, plan)
    cut_checks(long, path)
    _, short_checked = safe_box_checks(short, short_plan)
    for name in camera.CAMERAS:
        for move in camera.MOVES:
            one = dict(version=1, shots=[dict(start_bar=1, camera='hero' if name != 'hero' else 'wide'),
                                         dict(start_bar=13, camera=name, move=move, transition='cut'),
                                         dict(start_bar=21, camera='close', move='drift', transition='blend')])
            safe_box_checks(long, one)
    top = focus_checks()
    glide, kick = blend_checks(long)
    for a, b in zip(plan['shots'], plan['shots'][1:]):
        if b['transition'] == 'blend':
            assert camera.view_turn(a['camera'], b['camera']) <= camera.BLEND_TURN, (a, b)
    errors = validation_checks(short)
    print(json.dumps(plan))
    print(f'Auto: {len(plan["shots"])} shots on bars {starts}, {len(short_plan["shots"])} on the short song, '
          f'blending only between close views; {checked + short_checked} sounding-key frames inside the safe box; '
          f'every preset and move fits; focus at most {top:.3f} m/s; blends at most {glide:.2f} m/s and '
          f'{kick:.1f} m/s2, gliding in and out; {errors} bad shot lists refused.')
    print('verify_piano_camera: OK')


if __name__ == '__main__':
    main()
