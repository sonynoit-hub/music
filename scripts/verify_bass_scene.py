"""Check the bass scene: four strings, twenty frets toward the body, four tab lines and markers, and a lesson's
markers on the right string and fret. Nothing is saved.

Blender -b outputs/bass-vertical.blend --python-exit-code 1 --python scripts/verify_bass_scene.py
"""
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
from mathutils.geometry import intersect_point_line
from guitar_video_app.instruments.fretted import BASS_SPEC
from guitar_video_app.instruments.guitar.view import prepare
from guitar_video_app.integrations import lesson_controller as legacy
from guitar_video_app.integrations.blender_scene_refs import scene_strings
from guitar_video_app.integrations.lesson_setup import install_v2
from guitar_video_app.music.lesson import state
from guitar_video_app.music.tempo import seconds_at

STRINGS = BASS_SPEC.strings
objects = bpy.data.objects
scene = bpy.context.scene
saved = Path(bpy.data.filepath)
saved_time = saved.stat().st_mtime


def curve(name):
    obj = objects[name]
    return [obj.matrix_world @ Vector(p.co[:3]) for sp in obj.data.splines for p in sp.points]


def distance_to(points, target):
    best = math.inf
    for a, b in zip(points, points[1:]):
        p, t = intersect_point_line(target, a, b)
        p = a if t < 0 else b if t > 1 else p
        best = min(best, (p - target).length)
    return best


def fret_y(fret):
    return legacy._object_center_world('Nut' if fret == 0 else f'Fret_{fret:02d}').y


# Strings, frets, tab lines and markers.
assert scene_strings(scene) == STRINGS, scene.get('Lesson_Strings')
for i in range(1, 7):
    for name in (f'String_{i}', f'Lesson_Tab_Line_{i}'):
        assert (name in objects) == (i <= STRINGS), name
frets = [fret_y(f) for f in range(0, 21)]
gaps = [a - b for a, b in zip(frets, frets[1:])]
assert all(g > 0 for g in gaps), 'frets run from the nut toward the body'
assert all(b < a for a, b in zip(gaps, gaps[1:])), 'fret spacing shrinks toward the body'
assert all(abs(b / a - 2 ** (-1 / 12)) < 0.01 for a, b in zip(gaps, gaps[1:])), 'frets follow the 12th-root rule'
assert abs(gaps[0] / 0.0254 * 17.817 - 34) < 0.5, 'a 34-inch scale (first fret = scale / 17.817)'
bevels = [objects[f'String_{i}'].data.bevel_depth for i in range(1, STRINGS + 1)]
assert bevels == sorted(bevels, reverse=True), 'String_1 (low E) is the thickest'
lines = [world_to_camera_view(scene, scene.camera, sum(curve(f'Lesson_Tab_Line_{i}'), Vector()) / 2).y
         for i in range(1, STRINGS + 1)]
assert all(a > b for a, b in zip(lines, lines[1:])), 'tab line 1 (high G) is on top'
assert max(lines[i] - lines[i + 1] for i in range(3)) - min(lines[i] - lines[i + 1] for i in range(3)) < 1e-4
for point in (curve('Nut')[0], legacy._object_center_world('Fret_12')):
    p = world_to_camera_view(scene, scene.camera, point)
    assert 0 < p.x < 1 and 0 < p.y < 1, 'the nut and the 12th fret are in the frame'

# A lesson over every string at frets 0, 1, 5, 12 and 20: one note sounds at a time.
riff = [(s, f) for s in range(STRINGS, 0, -1) for f in (0, 1, 5, 12, 20)]
view = dict(version=2, name='Bass scene check', tempo_bpm=120, fps=30, time_signature=[4, 4],
            string_numbering=BASS_SPEC.numbering, instrument=BASS_SPEC.name, tuning=list(BASS_SPEC.tuning),
            end_beat=str(math.ceil(len(riff) / 4) * 4),
            notes=[dict(id=f'v{i:02d}', string=s, fret=f, start_beat=str(i), duration_beats='1',
                        **({'muted': True} if f == 5 else {}))  # fret 5 is muted (x) on every string
                   for i, (s, f) in enumerate(riff)])
install_v2(view)
for i in range(1, 7):
    assert (f'Lesson_V2_Marker_{i}' in objects) == (i <= STRINGS), i
lesson = prepare(view)
checked = 0
for note in lesson['notes']:
    frame = math.ceil(seconds_at(lesson['tempo_map'], (note['start'] + note['end']) / 2) * lesson['fps'])
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    assert [n['id'] for n in state(lesson, frame)[2]] == [note['id']], frame
    for s in range(1, STRINGS + 1):
        assert objects[f'Lesson_V2_Marker_{s}'].hide_render == (s != note['string']), (note, s)
    shown = objects[f'Lesson_V2_Marker_{note["string"]}']
    assert (shown.data.name == f'Lesson_V2_Mute_X_{note["string"]}') == bool(note.get('muted')), (note, shown.data.name)
    if note.get('muted'):
        page = [o.data.body for o in objects if o.name.startswith('Lesson_Tab_Number_') and not o.hide_render]
        assert page.count('x') == sum(1 for n in lesson['notes'] if n.get('muted')
                                      and n['start'] // lesson['page_beats'] == note['start'] // lesson['page_beats'])
    marker = shown.matrix_world.translation
    near = {s: distance_to(curve(f'String_{STRINGS + 1 - s}'), marker) for s in range(1, STRINGS + 1)}
    assert min(near, key=near.get) == note['string'] and near[note['string']] < 1e-3, (note, near)
    if note['fret']:
        assert fret_y(note['fret']) < marker.y < fret_y(note['fret'] - 1), (note, marker.y)
    else:
        assert marker.y > fret_y(0), 'open strings are marked on the headstock side of the nut'
    checked += 1

scene.frame_set(0)
assert all(objects[f'Lesson_V2_Marker_{s}'].data.name != f'Lesson_V2_Mute_X_{s}' for s in range(1, STRINGS + 1)), \
    'markers go back to their round shape'
assert saved.stat().st_mtime == saved_time, 'the bass scene was written'
print(f'BLENDER PASS: bass scene: 4 strings, 20 frets (34-inch scale), 4 tab lines; {checked} markers on their '
      'string and fret, muted ones as x; nothing saved.')
