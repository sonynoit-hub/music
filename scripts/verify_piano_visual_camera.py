"""Check PIANO_VISUAL's shot camera on a test piece; the .blend is not saved.

Blender -b outputs/piano-visual.blend --python scripts/verify_piano_visual_camera.py

Without shots the presentation camera renders as before. With Auto shots, and with a list that uses every camera,
move and transition: every sounding key's spawn anchor stays inside the 9:16 safe box (outside blends), cuts land on
the downbeat frames, the camera glides between them, any frame seeks to the same camera, the notes face the shot
camera, a reload rebuilds it, and uninstall restores the untouched presentation camera.
"""
import hashlib
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from bpy_extras.object_utils import world_to_camera_view
import numpy as np
from guitar_video_app.instruments.piano import camera as plan
from guitar_video_app.instruments.piano.view import prepare
from guitar_video_app.integrations import piano_visual as pv
from guitar_video_app.integrations import piano_visual_camera as shot_camera
from guitar_video_app.integrations import piano_visual_notes as notes
from guitar_video_app.integrations import piano_visual_particles as pvp

FPS = 24
STEP = 3                     # frames between safe-box samples
GLIDE = 0.06                 # m the camera may move in one frame inside a shot
BLEND_STEP = 0.35            # m it may move in one frame of a 0.75 s blend
BLEND = Path(bpy.data.filepath)


def piece():
    """12 bars at 120 bpm: chords and a melody around middle C, a melody two octaves up from bar 7, and both
    hands far apart from bar 10."""
    items = []
    for b in range(12):
        if b < 6:
            items += [dict(id=f'c{b}{p}', pitch=p, hand='left' if p < 60 else 'right', start_beat=b * 4,
                           duration_beats=2) for p in (48, 55, 64)]
            items += [dict(id=f'm{b}{k}', pitch=67 + (k * 2) % 5, hand='right', start_beat=b * 4 + 2 + k * 0.5,
                           duration_beats=0.5) for k in range(4)]
        elif b < 9:
            items += [dict(id=f'h{b}{k}', pitch=84 + k, hand='right', start_beat=b * 4 + k * 2, duration_beats=2)
                      for k in range(2)]
        else:
            items += [dict(id=f'l{b}', pitch=36, hand='left', start_beat=b * 4, duration_beats=2),
                      dict(id=f'r{b}', pitch=81, hand='right', start_beat=b * 4 + 1, duration_beats=1)]
    return dict(version=1, instrument='piano', name='Camera check', fps=FPS, tempo_bpm=120, time_signature=[4, 4],
                notes=items)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def presentation_state():
    cam = bpy.data.objects[pv.CAMERA_OBJECT]
    data = cam.data
    return ([tuple(row) for row in cam.matrix_world], tuple(cam.location), data.lens, data.shift_x, data.shift_y,
            data.sensor_width, data.sensor_fit, data.clip_start, data.clip_end,
            [(c.type, c.target.name if c.target else None) for c in cam.constraints], cam.parent)


def camera_state(scene):
    cam = scene.camera
    return (tuple(round(v, 6) for row in cam.matrix_world for v in row), round(cam.data.lens, 6),
            round(cam.data.shift_x, 6), round(cam.data.shift_y, 6))


def sounding(lesson, seconds):
    tempos = lesson['tempo_map']
    return [n['pitch'] for n in lesson['notes']
            if float(plan.seconds_at(tempos, n['start'])) <= seconds < float(plan.seconds_at(tempos, n['end']))]


def check_safe_box(scene, lesson, path):
    """Every sounding key's spawn anchor projects inside the safe box on sampled frames outside blends."""
    box, checked = plan.SAFE_BOX, 0
    end = round(float(plan.seconds_at(lesson['tempo_map'], lesson['end'])) * FPS)
    for frame in range(0, end, STEP):
        t = frame / FPS
        i = path.shot_index(t)
        if path.blending(t):
            continue
        scene.frame_set(frame)
        for pitch in sounding(lesson, t):
            spot = world_to_camera_view(scene, scene.camera, bpy.data.objects[pv.spawn_name(pitch)].matrix_world.translation)
            assert spot.z > 0 and box['left'] <= spot.x <= box['right'] and box['bottom'] <= spot.y <= box['top'], \
                (frame, path.shots[i].camera, pitch, tuple(spot))
            checked += 1
    return checked


def check_cuts(scene, lesson, path):
    """A cut jumps on the frame nearest its downbeat; between cuts the camera glides."""
    cuts = {round(plan.bar_seconds(lesson, s['start_bar']) * FPS): s for s in path.plan['shots'][1:]}
    for shot, (frame, entry) in zip(path.shots[1:], cuts.items()):
        assert abs(shot.start * FPS - frame) < 1e-6, 'cut is not on the downbeat frame'
    end = round(float(plan.seconds_at(lesson['tempo_map'], lesson['end'])) * FPS)
    blending = lambda f: path.blending(f / FPS) or path.blending((f - 1) / FPS)
    scene.frame_set(0)
    previous, jumps, glide, blend = scene.camera.matrix_world.translation.copy(), [], 0.0, 0.0
    for frame in range(1, end):
        scene.frame_set(frame)
        here = scene.camera.matrix_world.translation.copy()
        step = (here - previous).length
        if frame in cuts and cuts[frame]['transition'] == 'cut':
            jumps.append(step)
        elif blending(frame):
            blend = max(blend, step)
        else:
            glide = max(glide, step)
        previous = here
    assert glide <= GLIDE, f'the camera jumped {glide:.3f} m inside a shot'
    assert blend <= BLEND_STEP, f'a blend jumped {blend:.3f} m in one frame'
    assert all(j > glide for j in jumps), (jumps, glide)
    return len(jumps), glide


def check_seeking(scene):
    frames = list(range(0, scene.frame_end, 17))
    forward = {}
    for frame in frames:
        scene.frame_set(frame)
        forward[frame] = camera_state(scene)
    random.Random(4).shuffle(frames)
    for frame in frames:
        scene.frame_set(frame)
        assert camera_state(scene) == forward[frame], f'frame {frame} differs when seeking'
    return forward


def check_facing(scene):
    """A rising note glyph is a flat symbol turned to the active (shot) camera."""
    scene.frame_set(round(1.0 * FPS))
    obj = bpy.data.objects[pvp.OBJECT]
    geometry = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
    mesh = geometry.mesh
    count = len(mesh.vertices)
    co, part, seed = np.empty(count * 3), np.empty(count), np.empty(count)
    mesh.vertices.foreach_get('co', co)
    mesh.attributes['pv_part'].data.foreach_get('value', part)
    mesh.attributes['pv_seed'].data.foreach_get('value', seed)
    co = co.reshape(-1, 3)
    glyphs = part == notes.PART_GLYPH
    first = co[glyphs & (seed == seed[glyphs].min())]
    camera = scene.camera
    view = np.array([tuple(camera.matrix_world.inverted() @ (obj.matrix_world @ pv.Vector(p))) for p in first])
    normal = np.linalg.svd(view - view.mean(axis=0))[2][2]
    towards = -view.mean(axis=0) / np.linalg.norm(view.mean(axis=0))
    assert abs(normal @ towards) > 0.97, 'note does not face the shot camera'


def every_camera(lesson):
    shots, bar = [], 1
    for camera, move in zip(plan.CAMERAS, plan.MOVES * 2):
        shots.append(dict(start_bar=bar, camera=camera, move=move, transition='blend' if bar in (3, 7) else 'cut'))
        bar += 2
    return dict(version=1, shots=shots)


def main():
    before = sha(BLEND)
    scene = bpy.context.scene
    presentation = bpy.data.objects[pv.CAMERA_OBJECT]
    untouched = presentation_state()
    data = piece()
    lesson = prepare(data)

    summary = pvp.install(data)
    assert summary['camera'] == 'wide' and scene.camera == presentation, 'no shots must keep the presentation camera'
    assert shot_camera.CAMERA not in bpy.data.objects and shot_camera.PROPERTY not in scene

    auto = plan.auto_shots(lesson)
    assert pvp.install(data, camera=auto)['camera'] == 'shots'
    cam = scene.camera
    assert cam.name == shot_camera.CAMERA and cam.parent == bpy.data.objects[pv.FRAME_OBJECT]
    assert cam.users_collection[0].name == shot_camera.COLLECTION and shot_camera.shots() == auto
    assert not (cam.animation_data and cam.animation_data.action), 'the shot camera must not be keyed'
    path = shot_camera._path
    checked = check_safe_box(scene, lesson, path)
    jumps, glide = check_cuts(scene, lesson, path)
    seen = check_seeking(scene)
    check_facing(scene)
    assert presentation_state() == untouched, 'the presentation camera changed'

    pvp.register()
    assert scene.camera.name == shot_camera.CAMERA, 'a reload must rebuild the shot camera'
    for frame, state in list(seen.items())[:6]:
        scene.frame_set(frame)
        assert camera_state(scene) == state, 'a reload changed the shots'

    manual = every_camera(lesson)
    pvp.install(data, camera=manual)
    checked += check_safe_box(scene, lesson, shot_camera._path)
    cut_count, manual_glide = check_cuts(scene, lesson, shot_camera._path)
    try:
        pvp.install(data, camera=dict(version=1, shots=[dict(start_bar=2, camera='hero')]))
        raise AssertionError('a bad shot list was accepted')
    except ValueError:
        pass
    assert shot_camera.shots() == manual and scene.camera.name == shot_camera.CAMERA, 'a refused list changed the shots'

    pvp.uninstall()
    assert scene.camera == presentation and shot_camera.CAMERA not in bpy.data.objects
    assert shot_camera.COLLECTION not in bpy.data.collections and shot_camera.TEXT not in bpy.data.texts
    assert presentation_state() == untouched, 'the presentation camera changed'
    assert sha(BLEND) == before, '.blend changed'
    print(f"PASS: {len(auto['shots'])} Auto shots and all {len(plan.CAMERAS)} cameras/{len(plan.MOVES)} moves; "
          f"{checked} sounding-key frames inside the 9:16 safe box; {jumps + cut_count} cuts on downbeat frames, "
          f"at most {max(glide, manual_glide) * 100:.1f} cm per frame between cuts; seeking and reload give the same "
          "camera; notes face the shot camera; no shots keeps the presentation camera, which stays untouched and "
          "comes back on uninstall; .blend unchanged")


main()
