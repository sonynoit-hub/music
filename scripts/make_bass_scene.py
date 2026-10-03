"""Build the 4-string bass scene from the 9:16 guitar scene, keeping its body, materials, lights and tab panel.

Blender -b outputs/v4-vertical.blend --python scripts/make_bass_scene.py -- [--out outputs/bass-vertical.blend]

The guitar's six strings become four thicker ones (String_1 is the low E, as String_1 is the guitar's low E);
the neck, fretboard, frets and inlays stretch toward the headstock to a 34-inch scale with frets placed by the
12th-root rule; the tab keeps Lesson_Tab_Line_1..4, spread over the six lines' height so the cursor still fits.
The camera zooms out so the frame shows the same stretch of neck (headstock to 12th fret) and the tab panel
keeps its place on screen. When the longer neck does not fit the frame the guitar's length is kept and the
script says so. Rebuild the file with this script rather than editing it by hand.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from mathutils import Matrix, Vector
from bpy_extras.object_utils import world_to_camera_view
from guitar_video_app.instruments.fretted import BASS_SPEC
from guitar_video_app.integrations import lesson_controller as legacy
from guitar_video_app.integrations.blender_scene_refs import SCENE_STRINGS
from guitar_video_app.integrations.lesson_setup import install_v2

SCALE_INCHES = 34.0
STRINGS = BASS_SPEC.strings
# Curve bevel radius of String_1 (low E) .. String_4 (G); the guitar's low E is 0.0010.
STRING_BEVELS = (0.0019, 0.0016, 0.0013, 0.0010)
# Bass string -> the guitar string whose tuner post it winds on (posts nearest the nut, two per side).
TUNER_OF = {1: 1, 2: 2, 3: 5, 4: 6}
UNUSED_TUNERS = ('_-1_2', '_1_2')
# The 12th fret and the headstock tip must stay in the frame, the 12th fret above the tab panel.
FRAME_MARGIN = 0.03
PANEL_MARGIN = 0.02
SCENE_NAME = 'Bass - Four String Build'
PROTECTED = ('v4-vertical.blend', 'reference-guitar.blend', 'v3-tests.blend')

parser = argparse.ArgumentParser()
parser.add_argument('--out', type=Path, default=ROOT / 'outputs/bass-vertical.blend')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
if args.out.name in PROTECTED:
    raise SystemExit(f'Refusing to write {args.out.name}; the bass scene is saved to its own file.')


def objects():
    return bpy.data.objects


def curve_world(obj):
    return [obj.matrix_world @ Vector(p.co[:3]) for sp in obj.data.splines for p in sp.points]


def set_curve(obj, points):
    inverse = obj.matrix_world.inverted()
    obj.data.splines.clear()
    spline = obj.data.splines.new('POLY')
    spline.points.add(len(points) - 1)
    for point, world in zip(spline.points, points):
        point.co = (*(inverse @ world), 1.0)
    obj.data.update_tag()


def map_mesh_y(obj, mapping):
    inverse = obj.matrix_world.inverted()
    for vertex in obj.data.vertices:
        world = obj.matrix_world @ vertex.co
        vertex.co = inverse @ Vector((world.x, mapping(world.y), world.z))
    obj.data.update_tag()


def move_world(obj, offset):
    obj.matrix_world = Matrix.Translation(offset) @ obj.matrix_world


def center(obj):
    return legacy._object_center_world(obj.name)


def remove(name):
    obj = objects().get(name)
    if obj is not None:
        bpy.data.objects.remove(obj, do_unlink=True)


def view(scene, point):
    return world_to_camera_view(scene, scene.camera, point)


def headstock_tip():
    head = objects()['Headstock']
    top = max((head.matrix_world @ v.co for v in head.data.vertices), key=lambda v: v.y)
    return Vector((0.0, top.y, top.z))


def build(stretch):
    scene = bpy.context.scene
    bpy.app.handlers.frame_change_post.clear()
    cam = scene.camera
    if scene.get(SCENE_STRINGS) == STRINGS:
        raise SystemExit('Run this on the guitar scene (outputs/v4-vertical.blend), not on the bass scene.')
    guitar = {i: curve_world(objects()[f'String_{i}']) for i in range(1, 7)}
    saddle_y = guitar[1][1].y
    nut_y = curve_world(objects()['Nut'])[0].y
    guitar_scale = nut_y - saddle_y
    bass_scale = SCALE_INCHES * 0.0254 if stretch else guitar_scale
    factor = bass_scale / guitar_scale
    shift = Vector((0, bass_scale - guitar_scale, 0))
    before = dict(tip=headstock_tip(), fret12=center(objects()['Fret_12']))

    # Tab: four lines spread over the six lines' height, so the cursor and bar lines still fit.
    top, bottom = (sorted(curve_world(objects()[f'Lesson_Tab_Line_{i}']), key=lambda p: view(scene, p).x)
                   for i in (1, 6))
    for i in range(1, STRINGS + 1):
        t = (i - 1) / (STRINGS - 1)
        set_curve(objects()[f'Lesson_Tab_Line_{i}'], [top[0].lerp(bottom[0], t), top[-1].lerp(bottom[-1], t)])
    for i in range(STRINGS + 1, 7):
        remove(f'Lesson_Tab_Line_{i}')
        remove(f'Lesson_V2_Marker_{i}')

    # Neck: the fretboard scales about the saddle (so its frets stay true), the neck stretches from the body joint.
    along = lambda y: saddle_y + (y - saddle_y) * factor
    map_mesh_y(objects()['Fretboard'], along)
    neck = objects()['Neck']
    neck_low = min((neck.matrix_world @ v.co).y for v in neck.data.vertices)
    map_mesh_y(neck, lambda y: neck_low + (y - neck_low) * (nut_y + shift.y - neck_low) / (nut_y - neck_low))
    for fret in range(1, 21):
        obj = objects()[f'Fret_{fret:02d}']
        y = saddle_y + bass_scale * 2 ** (-fret / 12)
        set_curve(obj, [Vector((p.x, y, p.z)) for p in curve_world(obj)])
    for obj in [o for o in objects() if o.name.startswith('Inlay_')]:
        c = center(obj)
        move_world(obj, Vector((0, along(c.y) - c.y, 0)))
    for obj in [o for o in objects() if o.name in ('Nut', 'Headstock', 'Headstock_Face') or o.name.startswith('Tuner_')]:
        move_world(obj, shift)
    for obj in [o for o in objects() if o.name.startswith('Tuner_') and o.name.endswith(UNUSED_TUNERS)]:
        remove(obj.name)

    # Strings: spread between the guitar's outer strings at bridge, saddle and nut; each winds on a tuner post.
    neutral = legacy._ensure_materials()[2]
    for i in range(1, STRINGS + 1):
        t = (i - 1) / (STRINGS - 1)
        bridge, saddle, nut = (guitar[1][k].lerp(guitar[6][k], t) for k in range(3))
        post = guitar[TUNER_OF[i]][3]
        obj = objects()[f'String_{i}']
        obj.animation_data_clear()
        if 'JSON_String_Rest_State' in obj:
            del obj['JSON_String_Rest_State']
        set_curve(obj, [bridge, saddle, nut + shift, post + shift])
        obj.data.bevel_depth = STRING_BEVELS[i - 1]
        obj.data.materials.clear()
        obj.data.materials.append(neutral)
        for slot in obj.material_slots:
            slot.link = 'DATA'
            slot.material = neutral
        for part in ('Bridge_Pin', 'Bridge_Pin_Dot'):
            pin = objects().get(f'{part}_{i}')
            if pin:
                move_world(pin, Vector((bridge.x - guitar[i][0].x, 0, 0)))
    for i in range(STRINGS + 1, 7):
        remove(f'String_{i}')
        remove(f'Bridge_Pin_{i}')
        remove(f'Bridge_Pin_Dot_{i}')
    bpy.context.view_layer.update()

    # Camera: show the same neck stretch (headstock tip to 12th fret), headstock where it was on screen;
    # the tab panel's camera-aligned frame moves and scales with the view so it keeps its place.
    after = dict(tip=headstock_tip(), fret12=center(objects()['Fret_12']))
    zoom = (after['tip'] - after['fret12']).length / (before['tip'] - before['fret12']).length
    tip_view = view(scene, before['tip'])
    old_camera = cam.matrix_world.copy()
    cam.data.ortho_scale *= zoom
    bpy.context.view_layer.update()
    rotation = cam.matrix_world.to_quaternion()
    right, up = rotation @ Vector((1, 0, 0)), rotation @ Vector((0, 1, 0))
    now = view(scene, after['tip'])
    width = cam.data.ortho_scale * scene.render.resolution_x / max(scene.render.resolution_x, scene.render.resolution_y)
    height = cam.data.ortho_scale * scene.render.resolution_y / max(scene.render.resolution_x, scene.render.resolution_y)
    cam.location += right * ((now.x - tip_view.x) * width) + up * ((now.y - tip_view.y) * height)
    bpy.context.view_layer.update()
    frame = objects()['App_Tab_Frame_9x16']
    frame.matrix_world = cam.matrix_world @ Matrix.Diagonal((zoom, zoom, 1, 1)) @ old_camera.inverted() @ frame.matrix_world
    bpy.context.view_layer.update()

    panel_top = legacy._bbox(scene, cam, objects()['App_Tab_White_Panel'])[3]
    points = {name: view(scene, point) for name, point in
              (('headstock tip', after['tip']), ('12th fret', after['fret12']), ('nut', center(objects()['Nut'])))}
    misfit = [name for name, p in points.items()
              if not (FRAME_MARGIN <= p.x <= 1 - FRAME_MARGIN and FRAME_MARGIN <= p.y <= 1 - FRAME_MARGIN)]
    if points['12th fret'].y < panel_top + PANEL_MARGIN:
        misfit.append('12th fret above the tab panel')
    return dict(scale_m=round(bass_scale, 4), factor=round(factor, 4), zoom=round(zoom, 4),
                ortho_scale=round(cam.data.ortho_scale, 4), misfit=misfit)


def demo_view():
    """A short bass line on every string, so the saved scene opens with a bass lesson installed."""
    riff = [(4, 0), (4, 3), (3, 0), (3, 2), (2, 0), (2, 2), (1, 0), (1, 4), (1, 7), (2, 5), (3, 5), (4, 5),
            (4, 12), (3, 10), (2, 9), (1, 9)]
    notes = [dict(id=f'b{i:02d}', string=s, fret=f, start_beat=str(i / 2), duration_beats='1/2')
             for i, (s, f) in enumerate(riff)]
    return dict(version=2, name='Bass demo', tempo_bpm=100, fps=30, time_signature=[4, 4],
                string_numbering=BASS_SPEC.numbering, instrument=BASS_SPEC.name, tuning=list(BASS_SPEC.tuning),
                end_beat='8', notes=notes)


report = build(stretch=True)
fallback = bool(report['misfit'])
if fallback:
    print(f"The 34-inch neck does not fit the frame ({', '.join(report['misfit'])}); keeping the guitar's length.")
    bpy.ops.wm.revert_mainfile()
    report = build(stretch=False)
scene = bpy.context.scene
scene.name = SCENE_NAME
scene[SCENE_STRINGS] = STRINGS
install_v2(demo_view())
# As in the guitar scene, opening the file starts the dashboard bridge.
bpy.data.texts['Demo_16_Note_Tab_Controller.py'].write(
    '\nfrom guitar_video_app.integrations.blender_bridge_server import start_bridge\nstart_bridge()\n')
scene.frame_set(0)
print('Bass scene:', json.dumps(dict(report, fallback=fallback)))
bpy.ops.wm.save_as_mainfile(filepath=str(args.out.resolve()))
print(f'Saved {args.out}')
