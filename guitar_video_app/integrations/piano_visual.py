"""PIANO_VISUAL: a compact 88-key stage piano on a two-leg stand, for visualization videos.

Built procedurally so the key layout, names and MIDI mapping are exact and reproducible. It is a
separate asset from the lesson keyboard in integrations/piano_scene.py; both take their key layout
from instruments.piano.keyboard, so a key's x position is the same in the piano view and here.

World units are metres. PianoVisual_Root stands on the floor at the origin, the keyboard running
along x (centered), the players' side toward -y and up +z. PianoVisual_KeyboardFrame sits at the
white key tops (KEY_TOP_M above the floor) with y = 0 at the front edge of the white keys; keys,
body, controls and anchors are its children, the stand is a child of the root.

Keys are PianoVisual_Key_<index 000-087>_<note>, A0 (MIDI 21) to C8 (MIDI 108), with custom
properties midi_number, note_name, key_index, key_type, press_angle, pv_highlight (0-1) and
pv_highlight_color. A key's origin is its pivot, PIVOT_MM behind the front edge at the bottom of
the key; rotation_euler.x = press_angle presses it fully, 0 is rest. The key materials glow in
pv_highlight_color by pv_highlight, read per object, so highlighting a key needs no extra material.

A pedal unit (PIANO_VISUAL_PEDALS) stands on the floor between the legs: PianoVisual_Pedal_Soft,
_Sostenuto and _Sustain (left to right, MIDI CC 67, 66, 64) with pedal_type, midi_cc, press_angle,
pv_highlight and pv_highlight_color. A pedal's origin is its rear hinge; rotation_euler.x =
press_angle pushes its tip down PEDAL_DIP_MM, 0 is rest.

Anchors under PIANO_VISUAL_VISUALIZATION_ANCHORS give the keyboard center, its left and right
ends, a camera target, the pedals, and for every key its top center (PianoVisual_KeyCenter_<index>_<note>)
and a particle spawn point SPAWN_HEIGHT_MM above it (PianoVisual_Spawn_<index>_<note>); they stay
put when keys press.

Nothing rises above the key tops within the keyboard's footprint: the body behind the keys is
TOP_MM high and holds only flush controls, so particles can rise from every key.
"""
from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Vector

from guitar_video_app.instruments.piano.keyboard import (BLACK_HEIGHT_MM, BLACK_LENGTH_MM, BLACK_MM, HIGH, LOW,
                                                         PRESS_MM, WHITE_LENGTH_MM, WHITE_MM, WIDTH_MM, is_black,
                                                         key_x_mm)

MM = 0.001
PREFIX = 'PianoVisual'
ROOT = 'PIANO_VISUAL_ROOT'
BODY = 'PIANO_VISUAL_BODY'
KEYBOARD = 'PIANO_VISUAL_KEYBOARD'
STAND = 'PIANO_VISUAL_STAND'
CONTROLS = 'PIANO_VISUAL_CONTROLS'
PEDAL_UNIT = 'PIANO_VISUAL_PEDALS'
ANCHORS = 'PIANO_VISUAL_VISUALIZATION_ANCHORS'
KEY_CENTERS = 'PIANO_VISUAL_KEY_CENTERS'
SPAWN_POINTS = 'PIANO_VISUAL_SPAWN_POINTS'
PRESENTATION = 'PIANO_VISUAL_PRESENTATION'
ROOT_OBJECT = f'{PREFIX}_Root'
FRAME_OBJECT = f'{PREFIX}_KeyboardFrame'
CAMERA_OBJECT = f'{PREFIX}_PresentationCamera'
NOTE_TOKENS = ('C', 'Cs', 'D', 'Ds', 'E', 'F', 'Fs', 'G', 'Gs', 'A', 'As', 'B')
NOTE_NAMES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')

KEY_TOP_M = 0.745            # floor to white key tops, as on a typical stage piano stand
WHITE_GAP_MM = 1.0           # gap between neighbouring white keys
WHITE_THICK_MM = 22.0
NOTCH_CLEAR_MM = 0.6         # clearance between a white key's back part and a black key
BLACK_BASE_MM = BLACK_MM - 1.5
BLACK_TOP_MM = BLACK_BASE_MM - 2.6
BLACK_FRONT_SLOPE_MM = 7.0   # the black key top starts this far behind its front at the base
BLACK_BOTTOM_MM = -10.0      # black keys sit between the white keys' back parts
BLACK_FRONT_MM = WHITE_LENGTH_MM - BLACK_LENGTH_MM
PIVOT_MM = 250.0
PRESS_ANGLE = math.atan(PRESS_MM / PIVOT_MM)
CHEEK_MM = 48.0
BODY_BACK_MM = 290.0
BODY_BOTTOM_MM = -118.0
TOP_MM = 28.0                # top of the body behind the keys, above the white key tops
LIP_BOTTOM_MM = BLACK_HEIGHT_MM + 3
LIP_FRONT_MM = WHITE_LENGTH_MM + 1
SPAWN_HEIGHT_MM = 15.0
LEG_X_MM = WIDTH_MM / 2 - 45
HIGHLIGHT_COLOR = (1.0, 0.55, 0.2)
# Pedals, in root millimetres: name, pedal_type, MIDI controller, x of the pedal's center line.
PEDALS = (('Soft', 'soft', 67, -58.0), ('Sostenuto', 'sostenuto', 66, 0.0), ('Sustain', 'sustain', 64, 58.0))
PEDAL_HINGE_Y_MM = 215.0
PEDAL_HINGE_Z_MM = 52.0
PEDAL_LENGTH_MM = 200.0      # hinge to tip; the tip ends 15 mm behind the front of the keys
PEDAL_THICK_MM = 8.0
PEDAL_TILT = math.radians(5)  # the pedal rises toward its tip at rest
PEDAL_DIP_MM = 14.0
PEDAL_PRESS_ANGLE = math.atan(PEDAL_DIP_MM / PEDAL_LENGTH_MM)

MATERIALS = {
    # name: base color, roughness, metallic, coat
    'PV_Body_Satin': ((0.011, 0.011, 0.012, 1), 0.34, 0.0, 0.15),
    'PV_Body_Matte': ((0.014, 0.014, 0.015, 1), 0.62, 0.0, 0.0),
    'PV_Key_White': ((0.83, 0.82, 0.78, 1), 0.2, 0.0, 0.35),
    'PV_Key_Black': ((0.008, 0.008, 0.009, 1), 0.22, 0.0, 0.5),
    'PV_Metal': ((0.72, 0.72, 0.74, 1), 0.28, 1.0, 0.0),
    'PV_Felt': ((0.13, 0.012, 0.016, 1), 0.95, 0.0, 0.0),
    'PV_Rubber': ((0.02, 0.02, 0.021, 1), 0.7, 0.0, 0.0),
    'PV_LED': ((0.02, 0.02, 0.02, 1), 0.4, 0.0, 0.0),
    'PV_Pedal': ((0.8, 0.8, 0.82, 1), 0.22, 1.0, 0.0),
}
KEY_MATERIALS = ('PV_Key_White', 'PV_Key_Black')
GLOW_MATERIALS = KEY_MATERIALS + ('PV_Pedal',)
BOX_FACES = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


def note_token(pitch: int) -> str:
    return f'{NOTE_TOKENS[pitch % 12]}{pitch // 12 - 1}'


def note_name(pitch: int) -> str:
    return f'{NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}'


def key_name(pitch: int) -> str:
    return f'{PREFIX}_Key_{pitch - LOW:03d}_{note_token(pitch)}'


def key_center_name(pitch: int) -> str:
    return f'{PREFIX}_KeyCenter_{pitch - LOW:03d}_{note_token(pitch)}'


def spawn_name(pitch: int) -> str:
    return f'{PREFIX}_Spawn_{pitch - LOW:03d}_{note_token(pitch)}'


def pedal_name(pedal_type: str) -> str:
    return f'{PREFIX}_Pedal_{pedal_type.title()}'


def frame_x_mm(pitch: int) -> float:
    return key_x_mm(pitch) - WIDTH_MM / 2


def key_top_center_mm(pitch: int) -> tuple[float, float, float]:
    """Where a key's anchors sit at rest, in keyboard-frame millimetres: the middle of a black key's
    top, and the middle of a white key's full-width front, which black keys never hide (the back
    of a white key is notched, so its x can lie on the notch edge)."""
    if is_black(pitch):
        return frame_x_mm(pitch), (BLACK_FRONT_MM + BLACK_FRONT_SLOPE_MM + WHITE_LENGTH_MM) / 2, BLACK_HEIGHT_MM
    return frame_x_mm(pitch), (BLACK_FRONT_MM - NOTCH_CLEAR_MM) / 2, 0.0


# Materials

def _socket(sockets, name, kind=None):
    return next(s for s in sockets if s.name == name and (kind is None or s.type == kind))


def material(name: str):
    color, roughness, metallic, coat = MATERIALS[name]
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new('ShaderNodeOutputMaterial')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    out.location, bsdf.location = (400, 0), (0, 0)
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    bsdf.inputs['Base Color'].default_value = color
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = metallic
    bsdf.inputs['Coat Weight'].default_value = coat
    bsdf.inputs['Coat Roughness'].default_value = 0.12
    if name in ('PV_Metal', 'PV_Pedal'):
        bsdf.inputs['Anisotropic'].default_value = 0.5
    if name == 'PV_Felt':
        bsdf.inputs['Sheen Weight'].default_value = 0.6
    if name == 'PV_LED':
        bsdf.inputs['Emission Color'].default_value = (1.0, 0.95, 0.9, 1)
        bsdf.inputs['Emission Strength'].default_value = 3.0
    if name in GLOW_MATERIALS:
        _highlight_nodes(nodes, links, bsdf, color)
    mat.diffuse_color = color
    mat.roughness = roughness
    mat.metallic = metallic
    return mat


def _highlight_nodes(nodes, links, bsdf, color):
    """Per-object glow: the key's pv_highlight (0-1) tints and lights it in pv_highlight_color."""
    amount = nodes.new('ShaderNodeAttribute')
    amount.attribute_type, amount.attribute_name, amount.location = 'OBJECT', 'pv_highlight', (-800, 200)
    tint = nodes.new('ShaderNodeAttribute')
    tint.attribute_type, tint.attribute_name, tint.location = 'OBJECT', 'pv_highlight_color', (-800, -100)
    mix_amount = nodes.new('ShaderNodeMath')
    mix_amount.operation, mix_amount.location = 'MULTIPLY', (-550, 250)
    mix_amount.inputs[1].default_value = 0.85
    links.new(amount.outputs['Fac'], mix_amount.inputs[0])
    mix = nodes.new('ShaderNodeMix')
    mix.data_type, mix.location = 'RGBA', (-300, 150)
    links.new(mix_amount.outputs['Value'], _socket(mix.inputs, 'Factor', 'VALUE'))
    _socket(mix.inputs, 'A', 'RGBA').default_value = color
    links.new(tint.outputs['Color'], _socket(mix.inputs, 'B', 'RGBA'))
    links.new(_socket(mix.outputs, 'Result', 'RGBA'), bsdf.inputs['Base Color'])
    glow = nodes.new('ShaderNodeMath')
    glow.operation, glow.location = 'MULTIPLY', (-300, -150)
    glow.inputs[1].default_value = 8.0
    links.new(amount.outputs['Fac'], glow.inputs[0])
    links.new(tint.outputs['Color'], bsdf.inputs['Emission Color'])
    links.new(glow.outputs['Value'], bsdf.inputs['Emission Strength'])


# Geometry

def _mesh_from(name, vertices, faces):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    return mesh


def _prism(name, outline, z0, z1):
    """Mesh of a counterclockwise (x, y) outline extruded from z0 to z1."""
    n = len(outline)
    vertices = [(x, y, z0) for x, y in outline] + [(x, y, z1) for x, y in outline]
    faces = [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
    faces += [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    return _mesh_from(name, vertices, faces)


def _box_mesh(name, size):
    x, y, z = (s / 2 for s in size)
    return _prism(name, [(-x, -y), (x, -y), (x, y), (-x, y)], -z, z)


def _cylinder_mesh(name, radius, depth, segments):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius, radius2=radius, depth=depth)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _clean(points):
    """Drop repeated and collinear points of a closed outline."""
    points = [p for i, p in enumerate(points) if p != points[i - 1]]
    kept = []
    for i, (x, y) in enumerate(points):
        (ax, ay), (bx, by) = points[i - 1], points[(i + 1) % len(points)]
        if abs((x - ax) * (by - ay) - (y - ay) * (bx - ax)) > 1e-12:
            kept.append((x, y))
    return kept


def _white_outline(pitch):
    """Top view of a white key relative to its pivot: full width at the front, narrowed at the
    back where the neighbouring black keys sit."""
    cx = key_x_mm(pitch)
    left, right = cx - WHITE_MM / 2 + WHITE_GAP_MM / 2, cx + WHITE_MM / 2 - WHITE_GAP_MM / 2
    back_left, back_right = left, right
    if pitch - 1 >= LOW and is_black(pitch - 1):
        back_left = key_x_mm(pitch - 1) + BLACK_BASE_MM / 2 + NOTCH_CLEAR_MM
    if pitch + 1 <= HIGH and is_black(pitch + 1):
        back_right = key_x_mm(pitch + 1) - BLACK_BASE_MM / 2 - NOTCH_CLEAR_MM
    notch = BLACK_FRONT_MM - NOTCH_CLEAR_MM
    points = [(left, 0), (right, 0), (right, notch), (back_right, notch), (back_right, WHITE_LENGTH_MM),
              (back_left, WHITE_LENGTH_MM), (back_left, notch), (left, notch)]
    return [((x - cx) * MM, (y - PIVOT_MM) * MM) for x, y in _clean(points)]


def _black_vertices():
    base, top = BLACK_BASE_MM / 2, BLACK_TOP_MM / 2
    y0, y1, top_front = BLACK_FRONT_MM, WHITE_LENGTH_MM, BLACK_FRONT_MM + BLACK_FRONT_SLOPE_MM
    # The pivot is at the bottom of the white keys, WHITE_THICK_MM below their tops.
    z0, z1 = BLACK_BOTTOM_MM + WHITE_THICK_MM, BLACK_HEIGHT_MM + WHITE_THICK_MM
    corners = [(-base, y0, z0), (base, y0, z0), (base, y1, z0), (-base, y1, z0),
               (-top, top_front, z1), (top, top_front, z1), (top, y1, z1), (-top, y1, z1)]
    return [(x * MM, (y - PIVOT_MM) * MM, z * MM) for x, y, z in corners]


def _pedal_mesh(name):
    """Pedal lever relative to its rear hinge: narrow at the hinge, widening to a rounded foot
    plate at the tip (toward -y), rising PEDAL_TILT toward the tip."""
    half_back, radius, length = 11.0, 17.0, PEDAL_LENGTH_MM
    arc = [(radius * math.cos(a), -length + radius + radius * math.sin(a))
           for a in (math.radians(180 + 30 * i) for i in range(7))]
    outline = arc + [(half_back, 0.0), (-half_back, 0.0)]
    mesh = _prism(name, [(x * MM, y * MM) for x, y in outline], -PEDAL_THICK_MM / 2 * MM, PEDAL_THICK_MM / 2 * MM)
    rise = math.tan(PEDAL_TILT)
    for vertex in mesh.vertices:
        vertex.co.z -= vertex.co.y * rise
    mesh.update()
    return mesh


def _object(name, mesh, collection, parent, location, mat, bevel_mm=0.0, segments=2):
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.parent = parent
    obj.location = location
    mesh.materials.append(mat)
    if bevel_mm:
        bevel = obj.modifiers.new('Bevel', 'BEVEL')
        bevel.width = bevel_mm * MM
        bevel.segments = segments
        bevel.limit_method = 'ANGLE'
        bevel.harden_normals = True
        mesh.shade_smooth()
    return obj


def _box(name, collection, parent, x0, x1, y0, y1, z0, z1, mat, bevel_mm, segments=3):
    """Box between millimetre bounds in its parent's space, origin at its center."""
    size = ((x1 - x0) * MM, (y1 - y0) * MM, (z1 - z0) * MM)
    center = ((x0 + x1) / 2 * MM, (y0 + y1) / 2 * MM, (z0 + z1) / 2 * MM)
    return _object(name, _box_mesh(name, size), collection, parent, center, mat, bevel_mm, segments)


def _empty(name, collection, parent, location, size, kind='PLAIN_AXES'):
    obj = bpy.data.objects.new(name, None)
    collection.objects.link(obj)
    obj.parent = parent
    obj.location = location
    obj.empty_display_type = kind
    obj.empty_display_size = size
    return obj


def _apply_modifiers(objects):
    """Apply bevels so the asset is plain meshes: nothing to evaluate when keys move."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in objects:
        if not obj.modifiers:
            continue
        old = obj.data
        mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph), preserve_all_data_layers=True,
                                               depsgraph=depsgraph)
        obj.modifiers.clear()
        obj.data = mesh
        mesh.name = old.name
        bpy.data.meshes.remove(old)


def _props(obj, values):
    for name, value in values.items():
        obj[name] = value


def _collection(name, parent):
    collection = bpy.data.collections.new(name)
    parent.children.link(collection)
    return collection


def remove_piano_visual():
    """Delete a previous PIANO_VISUAL (its objects, meshes and collections); nothing else."""
    root = bpy.data.collections.get(ROOT)
    if root is None:
        return
    collections = [root] + list(root.children_recursive)
    meshes = set()
    for collection in collections:
        for obj in list(collection.objects):
            if obj.type == 'MESH':
                meshes.add(obj.data)
            bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in meshes:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    for collection in reversed(collections):
        bpy.data.collections.remove(collection)


# The asset

def build_piano_visual(scene=None, location=(0.0, 0.0, 0.0)):
    """Build PIANO_VISUAL in scene (default: the current one) standing at location; a previous
    PIANO_VISUAL is replaced, other objects are left alone. Returns the root object."""
    scene = scene or bpy.context.scene
    remove_piano_visual()
    root = _collection(ROOT, scene.collection)
    body, keyboard, stand = (_collection(n, root) for n in (BODY, KEYBOARD, STAND))
    controls, anchors = _collection(CONTROLS, root), _collection(ANCHORS, root)
    centers, spawns = _collection(KEY_CENTERS, anchors), _collection(SPAWN_POINTS, anchors)
    mats = {name: material(name) for name in MATERIALS}

    root_obj = _empty(ROOT_OBJECT, root, None, location, 0.25, 'ARROWS')
    frame = _empty(FRAME_OBJECT, root, root_obj, (0, 0, KEY_TOP_M), 0.08)
    _props(root_obj, {'piano_visual_version': 1, 'key_count': HIGH - LOW + 1, 'midi_low': LOW, 'midi_high': HIGH,
                     'key_top_height_m': KEY_TOP_M, 'keyboard_width_m': WIDTH_MM * MM})
    beveled = []

    for pitch in range(LOW, HIGH + 1):
        name, black = key_name(pitch), is_black(pitch)
        if black:
            mesh = _mesh_from(name, _black_vertices(), BOX_FACES)
        else:
            mesh = _prism(name, _white_outline(pitch), 0.0, WHITE_THICK_MM * MM)
        pivot = (frame_x_mm(pitch) * MM, PIVOT_MM * MM, -WHITE_THICK_MM * MM)
        obj = _object(name, mesh, keyboard, frame, pivot, mats['PV_Key_Black' if black else 'PV_Key_White'],
                      1.0 if black else 0.7, 2)
        _props(obj, {'midi_number': pitch, 'note_name': note_name(pitch), 'key_index': pitch - LOW,
                    'key_type': 'black' if black else 'white', 'press_angle': PRESS_ANGLE,
                    'pv_highlight': 0.0, 'pv_highlight_color': HIGHLIGHT_COLOR})
        obj.id_properties_ui('pv_highlight').update(min=0.0, max=1.0, description='Key glow, 0 at rest')
        obj.id_properties_ui('pv_highlight_color').update(subtype='COLOR', min=0.0, max=1.0)
        obj.id_properties_ui('press_angle').update(subtype='ANGLE', description='rotation_euler.x of a full press')
        obj.lock_location = (True, True, True)
        obj.lock_rotation = (False, True, True)
        obj.lock_scale = (True, True, True)
        beveled.append(obj)
        x, y, z = key_top_center_mm(pitch)
        center = _empty(key_center_name(pitch), centers, frame, (x * MM, y * MM, z * MM), 0.006)
        spawn = _empty(spawn_name(pitch), spawns, frame, (x * MM, y * MM, (z + SPAWN_HEIGHT_MM) * MM), 0.008,
                       'SINGLE_ARROW')
        for anchor in (center, spawn):
            _props(anchor, {'midi_number': pitch, 'note_name': note_name(pitch), 'key_index': pitch - LOW})

    half, left_end, right_end = WIDTH_MM / 2, frame_x_mm(LOW) - WHITE_MM / 2, frame_x_mm(HIGH) + WHITE_MM / 2
    outer = half + CHEEK_MM
    parts = [
        # name, x0, x1, y0, y1, z0, z1, material, bevel mm, segments
        ('Housing', -outer, outer, 2, BODY_BACK_MM, BODY_BOTTOM_MM, -64, 'PV_Body_Satin', 5, 3),
        ('KeySlip', -half - 1, half + 1, 2, 60, -66, -24, 'PV_Body_Satin', 3, 3),
        ('KeyBed', -half - 1, half + 1, 40, LIP_FRONT_MM + 8, -40, -24, 'PV_Body_Matte', 0, 0),
        ('Cheek_Left', -outer, -half - 1, -6, BODY_BACK_MM, BODY_BOTTOM_MM, TOP_MM, 'PV_Body_Satin', 9, 4),
        ('Cheek_Right', half + 1, outer, -6, BODY_BACK_MM, BODY_BOTTOM_MM, TOP_MM, 'PV_Body_Satin', 9, 4),
        ('TopPanel', -half - 1, half + 1, LIP_FRONT_MM, BODY_BACK_MM, LIP_BOTTOM_MM, TOP_MM, 'PV_Body_Satin', 4, 3),
        ('BackBlock', -half - 1, half + 1, LIP_FRONT_MM + 8, BODY_BACK_MM, -66, LIP_BOTTOM_MM, 'PV_Body_Matte', 2, 2),
        ('KeyFelt', -half, half, LIP_FRONT_MM, LIP_FRONT_MM + 8, -14, 5, 'PV_Felt', 0, 0),
        ('Trim', -half + 2, half - 2, LIP_FRONT_MM + 3, LIP_FRONT_MM + 5.5, TOP_MM - 0.4, TOP_MM + 0.5, 'PV_Metal',
         0.4, 1),
    ]
    for name, x0, x1, y0, y1, z0, z1, mat, bevel_mm, segments in parts:
        beveled.append(_box(f'{PREFIX}_{name}', body, frame, x0, x1, y0, y1, z0, z1, mats[mat], bevel_mm, segments))

    # Flush controls on the top panel's left end: power button in a metal ring, four buttons, an LED.
    y = (LIP_FRONT_MM + BODY_BACK_MM) / 2 + 20
    x = -half + 34
    ring = _object(f'{PREFIX}_Control_PowerRing', _cylinder_mesh(f'{PREFIX}_Control_PowerRing', 7.5 * MM, 1.2 * MM, 32),
                   controls, frame, (x * MM, y * MM, (TOP_MM + 0.6) * MM), mats['PV_Metal'], 0.3, 1)
    button = _object(f'{PREFIX}_Control_Power', _cylinder_mesh(f'{PREFIX}_Control_Power', 5.8 * MM, 2.0 * MM, 32),
                     controls, frame, (x * MM, y * MM, (TOP_MM + 1.0) * MM), mats['PV_Rubber'], 0.5, 2)
    beveled += [ring, button]
    for index in range(4):
        bx = x + 28 + index * 22
        beveled.append(_box(f'{PREFIX}_Control_Button_{index + 1}', controls, frame, bx - 7, bx + 7, y - 4, y + 4,
                            TOP_MM, TOP_MM + 1.6, mats['PV_Rubber'], 0.6, 2))
    beveled.append(_box(f'{PREFIX}_Control_LED', controls, frame, x - 1.2, x + 1.2, y - 16, y - 13.6, TOP_MM,
                        TOP_MM + 0.4, mats['PV_LED'], 0, 0))

    # Stand: two side legs on long feet, a rear stretcher panel and metal bolt caps.
    body_bottom = KEY_TOP_M * 1000 + BODY_BOTTOM_MM
    for side, sign in (('Left', -1), ('Right', 1)):
        lx = sign * LEG_X_MM
        beveled.append(_box(f'{PREFIX}_Leg_{side}', stand, root_obj, lx - 16, lx + 16, 40, 250, 50, body_bottom,
                            mats['PV_Body_Matte'], 4, 3))
        beveled.append(_box(f'{PREFIX}_Foot_{side}', stand, root_obj, lx - 24, lx + 24, -70, 340, 0, 52,
                            mats['PV_Body_Matte'], 12, 4))
        for by in (90, 200):
            bolt = _object(f'{PREFIX}_Bolt_{side}_{by}', _cylinder_mesh(f'{PREFIX}_Bolt_{side}_{by}', 7 * MM, 4 * MM, 20),
                           stand, root_obj, ((lx + sign * 18) * MM, by * MM, (body_bottom - 45) * MM),
                           mats['PV_Metal'], 0.8, 2)
            bolt.rotation_euler = (0, math.pi / 2, 0)
            beveled.append(bolt)
    beveled.append(_box(f'{PREFIX}_Stretcher', stand, root_obj, -LEG_X_MM + 16, LEG_X_MM - 16, 222, 238, 330, 470,
                        mats['PV_Body_Matte'], 3, 3))

    # Pedal unit: a box on four rubber feet, joined to the stretcher by a slim spine, with three pedals.
    pedal_unit = _collection(PEDAL_UNIT, root)
    beveled.append(_box(f'{PREFIX}_PedalBox', pedal_unit, root_obj, -150, 150, 165, 265, 16, 92,
                        mats['PV_Body_Satin'], 10, 4))
    beveled.append(_box(f'{PREFIX}_PedalSpine', pedal_unit, root_obj, -28, 28, 226, 236, 92, 331,
                        mats['PV_Body_Matte'], 2, 2))
    for fx in (-120, 120):
        for fy in (185, 245):
            name = f'{PREFIX}_PedalFoot_{"L" if fx < 0 else "R"}{fy}'
            beveled.append(_object(name, _cylinder_mesh(name, 9 * MM, 16 * MM, 16), pedal_unit, root_obj,
                                   (fx * MM, fy * MM, 8 * MM), mats['PV_Rubber'], 1.0, 2))
    for label, pedal_type, cc, px in PEDALS:
        name = pedal_name(pedal_type)
        obj = _object(name, _pedal_mesh(name), pedal_unit, root_obj,
                      (px * MM, PEDAL_HINGE_Y_MM * MM, PEDAL_HINGE_Z_MM * MM), mats['PV_Pedal'], 1.5, 2)
        _props(obj, {'pedal_type': pedal_type, 'midi_cc': cc, 'press_angle': PEDAL_PRESS_ANGLE,
                     'pv_highlight': 0.0, 'pv_highlight_color': HIGHLIGHT_COLOR})
        obj.id_properties_ui('pv_highlight').update(min=0.0, max=1.0, description='Pedal glow, 0 at rest')
        obj.id_properties_ui('pv_highlight_color').update(subtype='COLOR', min=0.0, max=1.0)
        obj.id_properties_ui('press_angle').update(subtype='ANGLE', description='rotation_euler.x of a full press')
        obj.lock_location = (True, True, True)
        obj.lock_rotation = (False, True, True)
        obj.lock_scale = (True, True, True)
        beveled.append(obj)
    _empty(f'{PREFIX}_Anchor_Pedals', anchors, root_obj,
           (0, (PEDAL_HINGE_Y_MM - PEDAL_LENGTH_MM + 30) * MM, 70 * MM), 0.04, 'SPHERE')

    anchor_size = 0.04
    for name, point in (('KeyboardCenter', (0, WHITE_LENGTH_MM / 2, 0)),
                        ('LeftEnd', (left_end, WHITE_LENGTH_MM / 2, 0)),
                        ('RightEnd', (right_end, WHITE_LENGTH_MM / 2, 0)),
                        ('CameraTarget', (0, WHITE_LENGTH_MM / 2, 60))):
        _empty(f'{PREFIX}_Anchor_{name}', anchors, frame, tuple(v * MM for v in point), anchor_size, 'SPHERE')

    _apply_modifiers(beveled)
    try:
        root.asset_mark()
    except (AttributeError, RuntimeError):
        pass
    bpy.context.view_layer.update()
    return root_obj


# Access for later animation and visualization code

def keys_by_midi(scene=None) -> dict[int, bpy.types.Object]:
    """{MIDI number: key object}, found by the midi_number property rather than by name."""
    scene = scene or bpy.context.scene
    return {obj['midi_number']: obj for obj in scene.objects
            if obj.name.startswith(f'{PREFIX}_Key_') and 'midi_number' in obj}


def press(pitch: int, amount: float = 1.0):
    """Put a key down by amount (0 rest, 1 fully pressed)."""
    obj = bpy.data.objects[key_name(pitch)]
    obj.rotation_euler.x = obj['press_angle'] * max(0.0, min(1.0, amount))


def highlight(pitch: int, amount: float = 1.0, color=None):
    obj = bpy.data.objects[key_name(pitch)]
    obj['pv_highlight'] = max(0.0, min(1.0, amount))
    if color is not None:
        obj['pv_highlight_color'] = tuple(color)[:3]
    obj.update_tag()


def reset_keys():
    for pitch in range(LOW, HIGH + 1):
        press(pitch, 0.0)
        highlight(pitch, 0.0)


def press_pedal(pedal_type: str = 'sustain', amount: float = 1.0, glow: float | None = None):
    """Push a pedal (sustain, sostenuto or soft) down by amount (0 rest, 1 fully); glow sets its highlight."""
    obj = bpy.data.objects[pedal_name(pedal_type)]
    obj.rotation_euler.x = obj['press_angle'] * max(0.0, min(1.0, amount))
    if glow is not None:
        obj['pv_highlight'] = max(0.0, min(1.0, glow))
        obj.update_tag()


def reset_pedals():
    for _, pedal_type, _, _ in PEDALS:
        press_pedal(pedal_type, 0.0, 0.0)


def spawn_points(scene=None) -> dict[int, Vector]:
    """World position above each key where particles can start, by MIDI number."""
    bpy.context.view_layer.update()
    return {p: bpy.data.objects[spawn_name(p)].matrix_world.translation.copy() for p in range(LOW, HIGH + 1)}


# A plain stage to judge the instrument

def build_presentation(scene=None):
    """Dark world, a floor, three area lights and a 3/4 camera, in their own collection."""
    scene = scene or bpy.context.scene
    old = bpy.data.collections.get(PRESENTATION)
    if old:
        for obj in list(old.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(old)
    stage = _collection(PRESENTATION, scene.collection)
    floor_mat = bpy.data.materials.get('PV_Floor') or bpy.data.materials.new('PV_Floor')
    if floor_mat.node_tree is None:
        floor_mat.use_nodes = True
    bsdf = next(n for n in floor_mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value = (0.03, 0.03, 0.032, 1)
    bsdf.inputs['Roughness'].default_value = 0.42
    floor_mat.diffuse_color = (0.03, 0.03, 0.032, 1)
    floor = _object(f'{PREFIX}_Floor', _box_mesh(f'{PREFIX}_Floor', (14, 14, 0.001)), stage, None,
                    (0, 0, -0.0005), floor_mat)

    world = scene.world or bpy.data.worlds.new('PianoVisual_World')
    scene.world = world
    world.color = (0.006, 0.006, 0.007)
    if world.node_tree is None:
        world.use_nodes = True
    background = next((n for n in world.node_tree.nodes if n.type == 'BACKGROUND'), None)
    if background:
        background.inputs['Color'].default_value = (0.006, 0.006, 0.007, 1)
        background.inputs['Strength'].default_value = 1.0

    target = Vector((0, WHITE_LENGTH_MM / 2 * MM, KEY_TOP_M))
    # Glossy black shows the lights it reflects, so the key light comes steeply from above the
    # players' side and the rim light low from behind, keeping their mirror images off the top panel.
    for name, spot, energy, size in (('Key', (-0.5, -1.5, 2.8), 120, (1.2, 0.5)),
                                     ('Rim', (1.4, 1.3, 0.9), 90, (2.0, 0.25)),
                                     ('Fill', (2.2, -1.8, 1.2), 18, (2.0, 2.0))):
        light = bpy.data.lights.new(f'{PREFIX}_Light_{name}', 'AREA')
        light.shape, light.size, light.size_y, light.energy = 'RECTANGLE', size[0], size[1], energy
        obj = bpy.data.objects.new(f'{PREFIX}_Light_{name}', light)
        stage.objects.link(obj)
        obj.location = spot
        obj.rotation_euler = (target - Vector(spot)).to_track_quat('-Z', 'Y').to_euler()

    cam_data = bpy.data.cameras.new(CAMERA_OBJECT)
    cam_data.lens = 35
    cam_data.shift_y = 0.12
    cam = bpy.data.objects.new(CAMERA_OBJECT, cam_data)
    stage.objects.link(cam)
    cam.location = (-1.75, -2.35, 1.5)
    track = cam.constraints.new('TRACK_TO')
    track.target = bpy.data.objects[f'{PREFIX}_Anchor_CameraTarget']
    track.track_axis, track.up_axis = 'TRACK_NEGATIVE_Z', 'UP_Y'
    scene.camera = cam
    return cam
