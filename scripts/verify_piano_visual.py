"""Check PIANO_VISUAL: 88 uniquely named keys A0-C8 on MIDI 21-108 (52 white, 36 black), no baked
animation, every key pressing on its own, and nothing above the keys. With --renders, also render
the presentation view, the piano from seven angles and a close-up with pressed, highlighted keys.
The file is not saved.

Blender -b outputs/piano-visual.blend --python-exit-code 1 --python scripts/verify_piano_visual.py -- [--renders DIR]
"""
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from mathutils import Vector

from guitar_video_app.instruments.piano.keyboard import BLACK_HEIGHT_MM, HIGH, LOW, PRESS_MM, WHITE_LENGTH_MM, is_black
from guitar_video_app.integrations.piano_visual import (BODY_BOTTOM_MM, CAMERA_OBJECT, FRAME_OBJECT, KEY_MATERIALS,
                                                        KEY_TOP_M, MM, PEDAL_DIP_MM, PEDALS, PREFIX, ROOT as
                                                        ROOT_COLLECTION, highlight, key_center_name, key_name,
                                                        keys_by_midi, pedal_name, press, press_pedal, reset_keys,
                                                        reset_pedals, spawn_name)

KEY_PATTERN = re.compile(rf'{PREFIX}_Key_(\d{{3}})_([A-G]s?)(\d)')


def same(a, b, tolerance=1e-9):
    return all(abs(a[i][j] - b[i][j]) < tolerance for i in range(4) for j in range(4))


def world_bounds(obj):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return [min(c[i] for c in corners) for i in range(3)], [max(c[i] for c in corners) for i in range(3)]


def front_top(obj):
    """Local position of the key's front top corner (lowest y, then highest z)."""
    vertices = [v.co for v in obj.data.vertices]
    front = min(v.y for v in vertices)
    return max((v for v in vertices if v.y < front + 1e-4), key=lambda v: v.z).copy()


def check_keys(scene):
    keys = [o for o in scene.objects if KEY_PATTERN.fullmatch(o.name)]
    assert len(keys) == 88, len(keys)
    assert len({k.name for k in keys}) == 88
    keys.sort(key=lambda k: k['key_index'])
    assert [k['midi_number'] for k in keys] == list(range(LOW, HIGH + 1))
    by_midi = keys_by_midi(scene)
    assert by_midi[21].name == 'PianoVisual_Key_000_A0' and by_midi[21]['note_name'] == 'A0'
    assert by_midi[60].name == 'PianoVisual_Key_039_C4' and by_midi[60]['note_name'] == 'C4'
    assert by_midi[108].name == 'PianoVisual_Key_087_C8' and by_midi[108]['note_name'] == 'C8'
    for key in keys:
        midi = key['midi_number']
        assert key.name == key_name(midi) and key['key_index'] == midi - LOW
        assert key['key_type'] == ('black' if is_black(midi) else 'white')
        assert key.type == 'MESH' and key.parent.name == FRAME_OBJECT
        assert key.data.users == 1 and key.data.materials[0].name in KEY_MATERIALS
        assert 'pv_highlight' in key and 'pv_highlight_color' in key
    whites = sum(k['key_type'] == 'white' for k in keys)
    assert (whites, len(keys) - whites) == (52, 36)
    return keys


def check_rest_and_no_animation(keys):
    assert not bpy.data.actions, [a.name for a in bpy.data.actions]
    for key in keys:
        assert key.animation_data is None and not key.constraints and not key.modifiers, key.name
        assert tuple(key.rotation_euler) == (0, 0, 0) and key['pv_highlight'] == 0


def check_independent(keys, view_layer):
    view_layer.update()
    rest = {k.name: k.matrix_world.copy() for k in keys}
    anchors = [bpy.data.objects[n(k['midi_number'])] for k in keys for n in (key_center_name, spawn_name)]
    anchor_rest = {a.name: a.matrix_world.copy() for a in anchors}
    dips = {}
    for key in keys:
        tip = front_top(key)
        before = key.matrix_world @ tip
        press(key['midi_number'], 1.0)
        view_layer.update()
        moved = [k.name for k in keys if not same(k.matrix_world, rest[k.name])]
        assert moved == [key.name], (key.name, moved[:5])
        dips[key['key_type']] = max(dips.get(key['key_type'], 0), (before - key.matrix_world @ tip).z / MM)
        press(key['midi_number'], 0.0)
    view_layer.update()
    assert all(same(k.matrix_world, rest[k.name]) for k in keys)
    assert all(same(a.matrix_world, anchor_rest[a.name]) for a in anchors)
    assert abs(dips['white'] - PRESS_MM) < 0.5, dips
    return dips


def check_pedals(keys, view_layer):
    """Three pedals (soft, sostenuto, sustain on CC 67, 66, 64) under the body, at rest, each
    pressing alone with its tip going down PEDAL_DIP_MM."""
    pedals = [bpy.data.objects[pedal_name(kind)] for _, kind, _, _ in PEDALS]
    assert [(p['pedal_type'], p['midi_cc']) for p in pedals] == [('soft', 67), ('sostenuto', 66), ('sustain', 64)]
    assert [round(p.location.x, 4) for p in pedals] == sorted(round(p.location.x, 4) for p in pedals)
    view_layer.update()
    body_bottom = KEY_TOP_M + BODY_BOTTOM_MM * MM
    for pedal in pedals:
        assert pedal.animation_data is None and not pedal.constraints and tuple(pedal.rotation_euler) == (0, 0, 0)
        assert pedal['pv_highlight'] == 0 and world_bounds(pedal)[1][2] < body_bottom and world_bounds(pedal)[0][2] > 0
    moving = keys + pedals
    rest = {o.name: o.matrix_world.copy() for o in moving}
    dips = []
    for pedal in pedals:
        tip = front_top(pedal)
        before = pedal.matrix_world @ tip
        press_pedal(pedal['pedal_type'], 1.0)
        view_layer.update()
        moved = [o.name for o in moving if not same(o.matrix_world, rest[o.name])]
        assert moved == [pedal.name], (pedal.name, moved[:5])
        after = pedal.matrix_world @ tip
        assert after.z > 0.02, pedal.name
        dips.append((before - after).z / MM)
        press_pedal(pedal['pedal_type'], 0.0)
    view_layer.update()
    assert all(abs(d - PEDAL_DIP_MM) < 0.5 for d in dips), dips
    return dips


def check_space_above(scene, keys, view_layer):
    """No geometry over the key footprint above the black key tops, and a clear vertical ray from every key."""
    view_layer.update()
    frame = bpy.data.objects[FRAME_OBJECT].matrix_world
    low, high = world_bounds(keys[0])[0], world_bounds(keys[-1])[1]
    front = (frame @ Vector((0, 0, 0))).y
    back = (frame @ Vector((0, WHITE_LENGTH_MM * MM, 0))).y
    ceiling = (frame @ Vector((0, 0, (BLACK_HEIGHT_MM + 0.5) * MM))).z
    blocking = []
    key_names = {k.name for k in keys}
    for obj in scene.objects:
        if obj.type != 'MESH' or obj.name in key_names or obj.name == f'{PREFIX}_Floor':
            continue
        lo, hi = world_bounds(obj)
        if lo[0] < high[0] and hi[0] > low[0] and lo[1] < back and hi[1] > front and hi[2] > ceiling:
            blocking.append(obj.name)
    assert not blocking, blocking
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for key in keys:
        midi = key['midi_number']
        spawn = bpy.data.objects[spawn_name(midi)].matrix_world.translation
        top = bpy.data.objects[key_center_name(midi)].matrix_world.translation
        hit, *_ = scene.ray_cast(depsgraph, top + Vector((0, 0, 0.0005)), Vector((0, 0, 1)))
        assert not hit, key.name
        hit, location, _, _, obj, _ = scene.ray_cast(depsgraph, spawn + Vector((0, 0, 3)), Vector((0, 0, -1)))
        assert hit and obj.name == key.name and abs(location.z - top.z) < 1e-4, (key.name, obj and obj.name)
    return ceiling


def poly_count():
    faces = triangles = 0
    for obj in bpy.data.collections[ROOT_COLLECTION].all_objects:
        if obj.type == 'MESH':
            obj.data.calc_loop_triangles()
            faces += len(obj.data.polygons)
            triangles += len(obj.data.loop_triangles)
    return faces, triangles


def render_views(scene, folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    cam = bpy.data.objects[CAMERA_OBJECT]
    scene.camera = cam
    scene.render.image_settings.file_format = 'PNG'
    shots = [('presentation', None, (1080, 1920), 50)]
    for name, spot in (('front', (0, -3.1, 1.15)), ('front_left', (-2.2, -2.3, 1.45)),
                       ('front_right', (2.2, -2.3, 1.45)), ('side', (-3.1, 0.12, 1.05)),
                       ('overhead', (0, -0.25, 3.4)), ('low_cinematic', (-1.1, -1.7, 0.32)), ('rear', (0.9, 2.8, 1.5))):
        shots.append((name, spot, (1920, 1080), 50))
    shots.append(('closeup_pressed', (-0.42, -0.62, 1.08), (1920, 1080), 50))
    shots.append(('pedals', (0.45, -0.95, 0.42), (1920, 1080), 50))
    track = cam.constraints['Track To']
    saved = cam.location.copy(), cam.data.shift_y, cam.data.lens, track.target
    for name, spot, (width, height), scale in shots:
        reset_keys()
        reset_pedals()
        cam.location, cam.data.shift_y, cam.data.lens, track.target = saved
        if spot:
            cam.location, cam.data.shift_y = spot, 0.0
        if name == 'closeup_pressed':
            cam.data.lens = 50
            press(60, 1.0)
            highlight(60, 1.0, (1.0, 0.55, 0.2))
            press(63, 1.0)
            highlight(63, 1.0, (0.25, 0.55, 1.0))
            press(67, 0.5)
        if name == 'pedals':
            cam.data.lens = 50
            track.target = bpy.data.objects[f'{PREFIX}_Anchor_Pedals']
            press_pedal('sustain', 1.0, 1.0)
            press_pedal('soft', 0.5)
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = width, height, scale
        scene.render.filepath = str(folder / f'{name}.png')
        bpy.ops.render.render(write_still=True)
    reset_keys()
    reset_pedals()
    cam.location, cam.data.shift_y, cam.data.lens, track.target = saved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--renders', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    scene, view_layer = bpy.context.scene, bpy.context.view_layer
    keys = check_keys(scene)
    check_rest_and_no_animation(keys)
    dips = check_independent(keys, view_layer)
    pedal_dips = check_pedals(keys, view_layer)
    check_space_above(scene, keys, view_layer)
    faces, triangles = poly_count()
    print(f"PASS: 88 keys A0-C8 on MIDI 21-108 (A0=21, C4=60, C8=108), 52 white / 36 black, unique names, "
          f"no animation; each key presses alone (front dip white {dips['white']:.1f} mm, black "
          f"{dips['black']:.1f} mm) and anchors stay; 3 pedals soft/sostenuto/sustain (CC 67/66/64) each press "
          f"alone (tip dip {max(pedal_dips):.1f} mm); nothing above the keys and a clear vertical ray from all 88; "
          f"{faces} faces / {triangles} triangles.")
    if args.renders:
        render_views(scene, args.renders)
        print(f'Renders written to {args.renders}')


main()
