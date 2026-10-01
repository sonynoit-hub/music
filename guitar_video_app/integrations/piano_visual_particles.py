"""Blue plumes of glowing particles rising from PIANO_VISUAL's keys while they sound, with key and pedal motion.

Blender only draws. Note and pedal seconds come from instruments.piano.performance (the lesson's tempo map): a
key emits while it is held and, thinner and dimmer, while the sustain pedal keeps it sounding; released
particles float on up and fade. Key presses follow the lesson controller's press and release envelope
(integrations.piano_lesson.key_events).

The particles are stateless: Geometry Nodes compute each one from the scene time in seconds, so any frame
renders the same in any order, with no simulation, bake or cache. PianoVisual_Plumes (collection
PIANO_VISUAL_PARTICLES, outside the asset) holds one point per note at its key's spawn anchor with
pv_start, pv_end and pv_sound_end in seconds, pv_seed and pv_width. The PV_Plumes modifier gives each
sounding note SLOTS particle slots; slot k emits at start + (k + m * SLOTS) / RATE for m = 0, 1, ..., so a
slot carries one particle at a time and a particle lives SLOTS / RATE = LIFE seconds.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
import json
import math
from pathlib import Path

import bpy

from guitar_video_app.instruments.piano.camera import validate as validate_shots
from guitar_video_app.instruments.piano.keyboard import HIGH, LOW, WHITE_MM, is_black
from guitar_video_app.instruments.piano.performance import pedal_amount, performance
from guitar_video_app.instruments.piano.view import prepare
from guitar_video_app.integrations import piano_visual as pv
from guitar_video_app.integrations import piano_visual_camera as shot_camera
from guitar_video_app.integrations.piano_lesson import key_events, key_state

COLLECTION = 'PIANO_VISUAL_PARTICLES'
OBJECT = f'{pv.PREFIX}_Plumes'
TREE = 'PV_Plumes'
MATERIAL = 'PV_Plume'
GLOW_TREE = 'PV_Glow'
HANDLER = 'piano_visual_particles_controller'
TEXT = 'PianoVisual_Lesson_JSON'
LOADER = 'PianoVisual_Particles_Controller.py'

RATE = 420.0                 # particles per second from a held key
LIFE = 2.2                   # seconds a particle lives
SLOTS = round(RATE * LIFE)
SUSTAIN_DENSITY = 0.4        # share of slots that still emit while only the pedal holds the note
SUSTAIN_DIM = 0.55           # pedal-held particles are this much dimmer
RISE = 0.3                   # m/s, varied +-25 % per particle
RISE_ACCEL = 0.06            # m/s^2
DRIFT = 0.14                 # m of swirl at the end of a life
DIFFUSE = 0.035              # m of per-particle scatter at the end of a life
SPARK_FRACTION = 0.25
BREAK_AT = 0.4               # sparks break away after this share of their life
SPARK_SPEED = 0.08           # m/s
MIST_FRACTION = 0.35         # large faint see-through particles that give a plume its body
MIST_SCALE = 4.0
MIST_GLOW = 0.4
MIST_ALPHA = 0.5
CORE_RADIUS = 0.002
SPRITE = 3.0                 # sprite side per unit of radius; the painted glow fades out before its edges
GLOW = 10.0
FLASH = 16.0                 # extra glow of a newborn particle, which lights the plume's base
FLASH_SECONDS = 0.2
PLUME_COLORS = ((0.0, (0.01, 0.05, 0.45)), (0.55, (0.04, 0.3, 1.0)), (1.0, (0.6, 0.85, 1.0)))
KEY_GLOW_COLOR = (0.1, 0.4, 1.0)
# A palette is the deep, main and pale colour an effect cools through, and the colour its key glows.
PALETTE_ATTRIBUTES = ('pv_deep', 'pv_main', 'pv_pale')
PALETTE_MIDDLE = PLUME_COLORS[1][0]
PALETTES = {
    'blue': (*(color for _, color in PLUME_COLORS), KEY_GLOW_COLOR),
    'white': ((0.22, 0.24, 0.3), (0.72, 0.78, 0.9), (1.0, 1.0, 1.0), (0.85, 0.9, 1.0)),
    'gold': ((0.35, 0.12, 0.01), (1.0, 0.55, 0.12), (1.0, 0.9, 0.6), (1.0, 0.62, 0.18)),
    'orange': ((0.4, 0.08, 0.0), (1.0, 0.38, 0.05), (1.0, 0.8, 0.55), (1.0, 0.6, 0.22)),
}
COLORS = ('blue', 'white', 'gold', 'hands')
COLORS_PROPERTY = 'pv_colors'
HAND_PALETTES = {'right': 'orange', 'left': 'blue'}   # like the lesson piano; other hands are white
KEY_SUSTAIN_GLOW = 0.3
PEDAL_GLOW = 0.4
EVENT_ATTRIBUTES = ('pv_start', 'pv_end', 'pv_sound_end', 'pv_seed', 'pv_width', 'pv_kind')
EFFECTS = ('notes', 'plumes')
EFFECT_PROPERTY = 'pv_effect'
HALF_BEATS = 1.5             # written lengths from here show a half note, from QUARTER_BEATS a quarter, else an eighth
QUARTER_BEATS = 0.75
_keys = {}
_sustain = {}
_pedals = []
_shown = {}
_colors = 'blue'


# Geometry Nodes

class _Graph:
    def __init__(self, tree):
        self.tree, self.nodes, self.links = tree, tree.nodes, tree.links

    def node(self, kind, **props):
        node = self.nodes.new(kind)
        for key, value in props.items():
            setattr(node, key, value)
        return node

    def feed(self, socket, value):
        if isinstance(value, bpy.types.NodeSocket):
            self.links.new(value, socket)
        else:
            socket.default_value = value

    def math(self, op, *values):
        node = self.node('ShaderNodeMath', operation=op)
        for socket, value in zip(node.inputs, values):
            self.feed(socket, value)
        return node.outputs[0]

    def vector(self, op, a, b):
        node = self.node('ShaderNodeVectorMath', operation=op)
        self.feed(node.inputs[0], a)
        self.feed(node.inputs['Scale'] if op == 'SCALE' else node.inputs[1], b)
        return node.outputs['Vector']

    def xyz(self, x, y, z):
        node = self.node('ShaderNodeCombineXYZ')
        for socket, value in zip(node.inputs, (x, y, z)):
            self.feed(socket, value)
        return node.outputs[0]

    def attribute(self, name):
        node = self.node('GeometryNodeInputNamedAttribute', data_type='FLOAT')
        node.inputs['Name'].default_value = name
        return pv._socket(node.outputs, 'Attribute')

    def random(self, ident, seed, low=None, high=None):
        """A float in 0-1, or a vector between low and high."""
        node = self.node('FunctionNodeRandomValue', data_type='FLOAT_VECTOR' if low else 'FLOAT')
        self.feed(node.inputs['ID'], ident)
        self.feed(node.inputs['Seed'], seed)
        if low:
            pv._socket(node.inputs, 'Min', 'VECTOR').default_value = low
            pv._socket(node.inputs, 'Max', 'VECTOR').default_value = high
            return pv._socket(node.outputs, 'Value', 'VECTOR')
        return pv._socket(node.outputs, 'Value', 'VALUE')

    def geometry(self, kind, geometry, **inputs):
        node = self.node(kind)
        props = {k: inputs.pop(k) for k in ('domain', 'data_type') if k in inputs}
        for key, value in props.items():
            setattr(node, key, value)
        self.feed(node.inputs[0], geometry)
        for name, value in inputs.items():
            socket = node.inputs[name]
            if name == 'Value' and 'data_type' in props:
                socket = pv._socket(node.inputs, 'Value', 'VALUE')
            self.feed(socket, value)
        return node


def new_tree(name):
    """A fresh Geometry Nodes group: (graph, the event points as a point cloud, group output, scene seconds)."""
    tree = bpy.data.node_groups.get(name)
    if tree:
        bpy.data.node_groups.remove(tree)
    tree = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    tree.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    tree.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    g = _Graph(tree)
    source = g.node('NodeGroupInput').outputs[0]
    points = g.geometry('GeometryNodeMeshToPoints', source).outputs['Points']
    return g, points, g.node('NodeGroupOutput'), g.node('GeometryNodeInputSceneTime').outputs['Seconds']


def emission(g, geometry, now, start, rate, slots):
    """Particle slots per event point: (geometry, emitted, ident, birth, age). Slot k emits at
    start + (k + m * slots) / rate; emitted < 0 means the slot has not emitted yet."""
    duplicate = g.geometry('GeometryNodeDuplicateElements', geometry, domain='POINT', Amount=slots)
    slot = duplicate.outputs['Duplicate Index']
    m = g.math
    emitted = m('SUBTRACT', m('MULTIPLY', m('SUBTRACT', now, start), rate), slot)
    ident = m('ADD', slot, m('MULTIPLY', m('FLOOR', m('DIVIDE', emitted, slots)), slots))
    birth = m('ADD', start, m('DIVIDE', ident, rate))
    return duplicate.outputs['Geometry'], emitted, ident, birth, m('SUBTRACT', now, birth)


def facing_camera(g, upright=False):
    """Rotation turning an instance's +Z to the active camera; upright also turns its +Y to the camera's up, so it
    stands straight in the picture."""
    camera = g.node('GeometryNodeObjectInfo', transform_space='RELATIVE')
    g.feed(camera.inputs['Object'], g.node('GeometryNodeInputActiveCamera').outputs[0])
    facing = g.node('FunctionNodeAlignRotationToVector', axis='Z')
    g.feed(facing.inputs['Vector'], g.vector('SUBTRACT', camera.outputs['Location'],
                                             g.node('GeometryNodeInputPosition').outputs[0]))
    if not upright:
        return facing.outputs[0]
    up = g.node('FunctionNodeRotateVector')
    up.inputs['Vector'].default_value = (0.0, 1.0, 0.0)
    g.feed(up.inputs['Rotation'], camera.outputs['Rotation'])
    level = g.node('FunctionNodeAlignRotationToVector', axis='Y', pivot_axis='Z')
    g.feed(level.inputs['Rotation'], facing.outputs[0])
    g.feed(level.inputs['Vector'], up.outputs[0])
    return level.outputs[0]


def sprites(g, points):
    """Each point (with radius, pv_heat, pv_glow, pv_alpha) as a small square turned to the active camera, with a
    round glow painted on it; realized, with the plume material."""
    grid = g.node('GeometryNodeMeshGrid')
    for name, value in (('Size X', 1.0), ('Size Y', 1.0), ('Vertices X', 2), ('Vertices Y', 2)):
        grid.inputs[name].default_value = value
    sprite = g.geometry('GeometryNodeStoreNamedAttribute', grid.outputs['Mesh'], domain='CORNER', data_type='FLOAT2',
                        Name='pv_uv')
    g.feed(pv._socket(sprite.inputs, 'Value', 'VECTOR'), grid.outputs['UV Map'])
    instances = g.node('GeometryNodeInstanceOnPoints')
    g.feed(instances.inputs['Points'], points)
    g.feed(instances.inputs['Instance'], sprite.outputs[0])
    g.feed(instances.inputs['Rotation'], facing_camera(g))
    g.feed(instances.inputs['Scale'], g.math('MULTIPLY', g.node('GeometryNodeInputRadius').outputs[0], SPRITE))
    real = g.geometry('GeometryNodeRealizeInstances', instances.outputs[0]).outputs[0]
    return g.geometry('GeometryNodeSetMaterial', real, Material=plume_material()).outputs[0]


def plume_tree():
    g, points, output, now = new_tree(TREE)
    m, v = g.math, g.vector
    start, end, sound_end = (g.attribute(n) for n in ('pv_start', 'pv_end', 'pv_sound_end'))
    seed, width = g.attribute('pv_seed'), g.attribute('pv_width')

    silent = m('MAXIMUM', m('LESS_THAN', now, start), m('GREATER_THAN', now, m('ADD', sound_end, LIFE)))
    sounding = g.geometry('GeometryNodeDeleteGeometry', points, domain='POINT', Selection=silent).outputs[0]
    slots, emitted, ident, birth, age = emission(g, sounding, now, start, RATE, SLOTS)
    life = m('DIVIDE', age, LIFE)
    rand = [g.random(ident, m('ADD', m('MULTIPLY', seed, 16), j)) for j in range(7)]
    held = m('LESS_THAN', birth, end)
    pedalled = m('MULTIPLY', m('LESS_THAN', birth, sound_end), m('LESS_THAN', rand[4], SUSTAIN_DENSITY))
    alive = m('MULTIPLY', m('GREATER_THAN', emitted, -1e-4), m('MAXIMUM', held, pedalled))
    spark = m('LESS_THAN', rand[3], SPARK_FRACTION)
    mist = m('GREATER_THAN', rand[3], 1 - MIST_FRACTION)
    broken = m('MULTIPLY', spark, m('GREATER_THAN', life, BREAK_AT))

    speed = m('MULTIPLY', RISE, m('ADD', 0.75, m('MULTIPLY', rand[0], 0.5)))
    rise = m('ADD', m('MULTIPLY', speed, age), m('MULTIPLY', 0.5 * RISE_ACCEL, m('MULTIPLY', age, age)))
    start_offset = g.xyz(m('MULTIPLY', m('SUBTRACT', rand[1], 0.5), m('MULTIPLY', width, 0.55)),
                         m('MULTIPLY', m('SUBTRACT', rand[2], 0.5), 0.018), rise)
    spawn = g.node('ShaderNodeSeparateXYZ')
    g.feed(spawn.inputs[0], g.node('GeometryNodeInputPosition').outputs[0])
    noise = g.node('ShaderNodeTexNoise', noise_dimensions='4D')
    g.feed(noise.inputs['Vector'], g.xyz(m('MULTIPLY', spawn.outputs[0], 6), m('MULTIPLY', spawn.outputs[1], 6),
                                         m('MULTIPLY', rise, 3)))
    g.feed(noise.inputs['W'], m('MULTIPLY', now, 0.3))
    noise.inputs['Scale'].default_value = 1.5
    noise.inputs['Detail'].default_value = 2.0
    swirl = v('SCALE', v('SUBTRACT', noise.outputs['Color'], (0.5, 0.5, 0.35)), m('MULTIPLY', DRIFT, m('POWER', life, 1.4)))
    scatter = v('SCALE', g.random(ident, m('ADD', m('MULTIPLY', seed, 16), 7), (-1, -1, -0.3), (1, 1, 0.3)),
                m('MULTIPLY', m('MULTIPLY', DIFFUSE, life), m('ADD', 1, m('MULTIPLY', mist, 1.5))))
    burst = v('SCALE', g.random(ident, m('ADD', m('MULTIPLY', seed, 16), 8), (-1, -1, -0.2), (1, 1, 0.6)),
              m('MULTIPLY', m('MULTIPLY', spark, SPARK_SPEED), m('MAXIMUM', 0, m('SUBTRACT', age, BREAK_AT * LIFE))))
    offset = v('ADD', v('ADD', start_offset, swirl), v('ADD', scatter, burst))
    moved = g.geometry('GeometryNodeSetPosition', slots, Offset=offset).outputs[0]

    fade = m('POWER', m('SUBTRACT', 1, life), 1.5)
    flash = m('MULTIPLY', FLASH, m('MAXIMUM', 0, m('SUBTRACT', 1, m('DIVIDE', age, FLASH_SECONDS))))
    glow = m('ADD', m('MULTIPLY', GLOW, fade), flash)
    glow = m('MULTIPLY', glow, m('SUBTRACT', 1, m('MULTIPLY', SUSTAIN_DIM, m('SUBTRACT', 1, held))))
    phase = m('ADD', m('MULTIPLY', now, 29), m('MULTIPLY', rand[6], 62.8))
    twinkle = m('ADD', 0.3, m('MULTIPLY', 2.2, m('MAXIMUM', 0, m('SINE', phase))))
    glow = m('MULTIPLY', glow, m('ADD', 1, m('MULTIPLY', broken, m('SUBTRACT', twinkle, 1))))
    radius = m('MULTIPLY', m('MULTIPLY', CORE_RADIUS, m('ADD', 0.6, m('MULTIPLY', rand[5], 0.8))),
               m('SUBTRACT', 1, m('MULTIPLY', 0.55, life)))
    radius = m('MULTIPLY', radius, m('SUBTRACT', 1, m('MULTIPLY', 0.3, m('SUBTRACT', 1, held))))
    radius = m('MULTIPLY', radius, m('SUBTRACT', 1, m('MULTIPLY', 0.45, broken)))
    radius = m('MULTIPLY', radius, m('ADD', 1, m('MULTIPLY', mist, MIST_SCALE - 1)))
    glow = m('MULTIPLY', glow, m('SUBTRACT', 1, m('MULTIPLY', mist, 1 - MIST_GLOW)))

    stored = moved
    for name, value in (('pv_heat', m('SUBTRACT', 1, life)), ('pv_glow', glow),
                        ('pv_alpha', m('SUBTRACT', 1, m('MULTIPLY', mist, 1 - MIST_ALPHA)))):
        stored = g.geometry('GeometryNodeStoreNamedAttribute', stored, domain='POINT', data_type='FLOAT',
                            Name=name, Value=value).outputs[0]
    sized = g.geometry('GeometryNodeSetPointRadius', stored, Radius=radius).outputs[0]
    living = g.geometry('GeometryNodeDeleteGeometry', sized, domain='POINT',
                        Selection=m('SUBTRACT', 1, alive)).outputs[0]
    g.feed(output.inputs[0], sprites(g, living))
    return g.tree


def plume_material():
    return glow_material(MATERIAL)


def glow_material(name, painted=True):
    """Emission as strong as pv_glow and as opaque as pv_alpha, coloured by pv_heat along the point's own palette
    (pv_deep at 0, pv_main at PALETTE_MIDDLE, pv_pale at 1); painted adds the round falloff read from the sprite's
    pv_uv."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    heat = nodes.new('ShaderNodeAttribute')
    heat.attribute_type, heat.attribute_name, heat.location = 'GEOMETRY', 'pv_heat', (-900, 100)
    glow = nodes.new('ShaderNodeAttribute')
    glow.attribute_type, glow.attribute_name, glow.location = 'GEOMETRY', 'pv_glow', (-700, -150)
    shades = []
    for index, attribute in enumerate(PALETTE_ATTRIBUTES):
        shade = nodes.new('ShaderNodeAttribute')
        shade.attribute_type, shade.attribute_name, shade.location = 'GEOMETRY', attribute, (-900, -300 - 150 * index)
        shades.append(shade.outputs['Color'])
    ramp = None
    for index, (low, high) in enumerate(((0.0, PALETTE_MIDDLE), (PALETTE_MIDDLE, 1.0))):
        along = nodes.new('ShaderNodeMapRange')
        along.clamp, along.location = True, (-700, 250 - 150 * index)
        along.inputs['From Min'].default_value, along.inputs['From Max'].default_value = low, high
        links.new(heat.outputs['Fac'], along.inputs['Value'])
        blend = nodes.new('ShaderNodeMix')
        blend.data_type, blend.location = 'RGBA', (-450, 150 - 150 * index)
        links.new(along.outputs['Result'], blend.inputs['Factor'])
        links.new(ramp if ramp else shades[0], pv._socket(blend.inputs, 'A', 'RGBA'))
        links.new(shades[index + 1], pv._socket(blend.inputs, 'B', 'RGBA'))
        ramp = pv._socket(blend.outputs, 'Result', 'RGBA')
    alpha = nodes.new('ShaderNodeAttribute')
    alpha.attribute_type, alpha.attribute_name, alpha.location = 'GEOMETRY', 'pv_alpha', (-450, 300)
    emission = nodes.new('ShaderNodeEmission')
    emission.location = (-150, 0)
    clear = nodes.new('ShaderNodeBsdfTransparent')
    clear.location = (-150, 200)
    mix = nodes.new('ShaderNodeMixShader')
    mix.location = (100, 100)
    out = nodes.new('ShaderNodeOutputMaterial')
    out.location = (300, 100)
    links.new(ramp, emission.inputs['Color'])
    links.new(glow.outputs['Fac'], emission.inputs['Strength'])
    links.new(clear.outputs[0], mix.inputs[1])
    links.new(emission.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs['Surface'])
    mat.diffuse_color = (*PLUME_COLORS[1][1], 1)
    if not painted:
        links.new(alpha.outputs['Fac'], mix.inputs['Fac'])
        return mat
    uv = nodes.new('ShaderNodeAttribute')
    uv.attribute_type, uv.attribute_name, uv.location = 'GEOMETRY', 'pv_uv', (-1100, 450)
    center = nodes.new('ShaderNodeVectorMath')
    center.operation, center.location = 'DISTANCE', (-900, 450)
    center.inputs[1].default_value = (0.5, 0.5, 0.0)
    edge = nodes.new('ShaderNodeMath')
    edge.operation, edge.use_clamp, edge.location = 'MULTIPLY_ADD', True, (-700, 450)
    edge.inputs[1].default_value, edge.inputs[2].default_value = -2.0, 1.0
    soft = nodes.new('ShaderNodeMath')
    soft.operation, soft.location = 'POWER', (-500, 450)
    soft.inputs[1].default_value = 2.0
    fade = nodes.new('ShaderNodeMath')
    fade.operation, fade.location = 'MULTIPLY', (-150, 400)
    links.new(uv.outputs['Vector'], center.inputs[0])
    links.new(center.outputs['Value'], edge.inputs[0])
    links.new(edge.outputs[0], soft.inputs[0])
    links.new(soft.outputs[0], fade.inputs[0])
    links.new(alpha.outputs['Fac'], fade.inputs[1])
    links.new(fade.outputs[0], mix.inputs['Fac'])
    return mat


def install_glow(scene):
    """A soft bloom in the compositor, unless the scene already composites with its own nodes."""
    current = getattr(scene, 'compositing_node_group', None)
    if current is not None and current.name != GLOW_TREE:
        return False
    tree = bpy.data.node_groups.get(GLOW_TREE)
    if tree:
        bpy.data.node_groups.remove(tree)
    tree = bpy.data.node_groups.new(GLOW_TREE, 'CompositorNodeTree')
    tree.interface.new_socket('Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    layers = tree.nodes.new('CompositorNodeRLayers')
    glare = tree.nodes.new('CompositorNodeGlare')
    out = tree.nodes.new('NodeGroupOutput')
    layers.location, glare.location, out.location = (-400, 0), (-100, 0), (200, 0)
    glare.inputs['Type'].default_value = 'Bloom'
    glare.inputs['Quality'].default_value = 'Medium'
    glare.inputs['Threshold'].default_value = 2.0
    glare.inputs['Strength'].default_value = 0.45
    glare.inputs['Size'].default_value = 0.6
    tree.links.new(layers.outputs['Image'], glare.inputs['Image'])
    tree.links.new(glare.outputs['Image'], out.inputs[0])
    scene.compositing_node_group = tree
    return True


# The notes

def palette(colors, hand=None):
    """(deep, main, pale, key) for a note of this hand in a colour theme; hand None is the theme's neutral."""
    if colors == 'hands':
        return PALETTES[HAND_PALETTES.get(hand, 'white')]
    return PALETTES[colors]


def note_kind(beats):
    """0 half, 1 quarter, 2 eighth, from a note's written length in beats."""
    return 0 if beats >= HALF_BEATS else 1 if beats >= QUARTER_BEATS else 2


def _plume_object(notes, effect='plumes', colors='blue'):
    remove_plumes()
    frame = bpy.data.objects[pv.FRAME_OBJECT]
    to_frame = frame.matrix_world.inverted()
    bpy.context.view_layer.update()
    spawns = {p: to_frame @ bpy.data.objects[pv.spawn_name(p)].matrix_world.translation for p in range(LOW, HIGH + 1)}
    mesh = bpy.data.meshes.new(OBJECT)
    mesh.from_pydata([tuple(spawns[n['pitch']]) for n in notes], [], [])
    width = lambda p: (pv.BLACK_TOP_MM if is_black(p) else WHITE_MM - pv.WHITE_GAP_MM) * pv.MM
    values = dict(pv_start=[n['start'] for n in notes], pv_end=[n['end'] for n in notes],
                  pv_sound_end=[n['sound_end'] for n in notes], pv_seed=[float(i) for i in range(len(notes))],
                  pv_width=[width(n['pitch']) for n in notes], pv_kind=[float(n.get('kind', 1)) for n in notes])
    for name in EVENT_ATTRIBUTES:
        mesh.attributes.new(name, 'FLOAT', 'POINT').data.foreach_set('value', values[name])
    shades = [palette(colors, n.get('hand')) for n in notes]
    for index, name in enumerate(PALETTE_ATTRIBUTES):
        flat = [channel for shade in shades for channel in (*shade[index], 1.0)]
        mesh.attributes.new(name, 'FLOAT_COLOR', 'POINT').data.foreach_set('color', flat)
    collection = bpy.data.collections.new(COLLECTION)
    bpy.context.scene.collection.children.link(collection)
    obj = bpy.data.objects.new(OBJECT, mesh)
    collection.objects.link(obj)
    obj.parent = frame
    obj.visible_shadow = False
    if effect == 'notes':
        from guitar_video_app.integrations import piano_visual_notes
        tree = piano_visual_notes.notes_tree(collection)
    else:
        tree = plume_tree()
    obj.modifiers.new('PV_Plumes', 'NODES').node_group = tree
    # Solid view shows one flat colour per material: the theme's neutral.
    for mat in (bpy.data.materials.get(n) for n in (MATERIAL, 'PV_NoteGlyph')):
        if mat:
            mat.diffuse_color = (*palette(colors)[1], 1)
    return obj


def remove_plumes():
    collection = bpy.data.collections.get(COLLECTION)
    objects = list(collection.objects) if collection else []
    if bpy.data.objects.get(OBJECT) and bpy.data.objects[OBJECT] not in objects:
        objects.append(bpy.data.objects[OBJECT])
    for obj in objects:
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    if collection:
        bpy.data.collections.remove(collection)


def uninstall():
    """Stop the handler, delete the plumes and the shot camera and put keys and pedals at rest; the asset stays."""
    handlers = bpy.app.handlers.frame_change_post
    handlers[:] = [h for h in handlers if getattr(h, '__name__', '') != HANDLER]
    remove_plumes()
    shot_camera.uninstall()
    pv.reset_keys()
    pv.reset_pedals()
    _shown.clear()


def _sustain_spans(notes):
    """{pitch: (ends, spans)}: when only the pedal holds a key's note, after the key has lifted, and whose note."""
    spans = defaultdict(list)
    for note in notes:
        if note['sound_end'] > note['end']:
            spans[note['pitch']].append((note['end'], note['sound_end'], note.get('hand')))
    return {p: ([s[0] for s in sorted(v)], sorted(v)) for p, v in spans.items()}


def _sustained(pitch, now):
    """The hand of the note the pedal alone holds on this key, or False."""
    ends, spans = _sustain.get(pitch, ((), ()))
    index = bisect_right(ends, now)
    return next((hand for start, stop, hand in spans[max(0, index - 3):index] if start <= now < stop), False)


def update(scene, *_):
    now = (scene.frame_current + scene.frame_subframe) / (scene.render.fps / scene.render.fps_base)
    for pitch in range(LOW, HIGH + 1):
        amount, hand = 0.0, None
        if pitch in _keys:
            amount, hand = key_state(*_keys[pitch], now)
        held = _sustained(pitch, now)
        glow = max(amount, KEY_SUSTAIN_GLOW if held is not False else 0.0)
        color = palette(_colors, hand if amount > 0 else held or None)[3]
        if _shown.get(pitch) == (amount, glow, color):
            continue
        _shown[pitch] = (amount, glow, color)
        pv.press(pitch, amount)
        pv.highlight(pitch, glow, color)
    amount = pedal_amount(_pedals, now)
    if _shown.get('sustain') != amount:
        _shown['sustain'] = amount
        pv.press_pedal('sustain', amount, PEDAL_GLOW * amount)


def tail(note, effect):
    """When a note's effect has fully faded, in seconds."""
    if effect == 'notes':
        from guitar_video_app.integrations import piano_visual_notes
        return piano_visual_notes.fade_end(note)
    return note['sound_end'] + LIFE


def register():
    """Rebuild the effect, keys, pedals and shot camera from the stored lesson and start the frame handlers."""
    global _keys, _sustain, _pedals, _colors
    data = json.loads(bpy.data.texts[TEXT].as_string())
    effect = bpy.context.scene.get(EFFECT_PROPERTY, 'notes')
    _colors = bpy.context.scene.get(COLORS_PROPERTY, 'blue')
    lesson = prepare(data)
    notes, _pedals = performance(data, lesson)
    beats = {n['id']: float(n['end'] - n['start']) for n in lesson['notes']}
    for note in notes:
        note['kind'] = note_kind(beats[note['id']])
    _keys = key_events(lesson)
    _sustain = _sustain_spans(notes)
    _plume_object(notes, effect, _colors)
    pedal = bpy.data.objects[pv.pedal_name('sustain')]
    pedal['pv_highlight_color'] = palette(_colors)[3]
    pv.reset_keys()
    pv.reset_pedals()
    _shown.clear()
    handlers = bpy.app.handlers.frame_change_post
    handlers[:] = [h for h in handlers if getattr(h, '__name__', '') != HANDLER]
    update.__name__ = HANDLER
    handlers.append(update)
    update(bpy.context.scene)
    shot_camera.register(data)
    return notes


def install(data, effect='notes', colors='blue', camera=None):
    """Load a piano view into the open PIANO_VISUAL scene: rising notes (or plumes) in a colour theme (or coloured
    by hand), key and pedal motion, frame range from its tempo map (with a tail for the last effect to fade) and the
    compositor glow. camera is a shot list for the shot camera (instruments.piano.camera); None keeps the
    presentation camera."""
    if effect not in EFFECTS:
        raise ValueError(f'Effect must be one of {", ".join(EFFECTS)}.')
    if colors not in COLORS:
        raise ValueError(f'Colors must be one of {", ".join(COLORS)}.')
    lesson = prepare(data)
    if camera is not None:
        validate_shots(camera, lesson)
    scene = bpy.context.scene
    missing = [pv.key_name(p) for p in range(LOW, HIGH + 1) if pv.key_name(p) not in bpy.data.objects]
    if missing or pv.FRAME_OBJECT not in bpy.data.objects:
        raise ValueError('Open PIANO_VISUAL (outputs/piano-visual.blend) first.'
                         + (f' Missing {len(missing)} keys.' if missing else ''))
    text = bpy.data.texts.get(TEXT) or bpy.data.texts.new(TEXT)
    text.clear()
    text.write(json.dumps(data, indent=2))
    root = str(Path(__file__).resolve().parents[2])
    loader = bpy.data.texts.get(LOADER) or bpy.data.texts.new(LOADER)
    loader.clear()
    loader.write('import sys\n' + f'sys.path.insert(0, {root!r})\n'
                 + 'from guitar_video_app.integrations.piano_visual_particles import register\nregister()\n')
    loader.use_module = True
    scene.render.fps = lesson['fps']
    scene.render.fps_base = 1
    scene.render.use_lock_interface = True
    scene[EFFECT_PROPERTY] = effect
    scene[COLORS_PROPERTY] = colors
    shot_camera.store(data, camera)
    notes = register()
    last = max((tail(n, effect) for n in notes), default=0.0)
    scene.frame_start = 0
    scene.frame_end = max(lesson['frame_end'], math.ceil(last * lesson['fps']))
    install_glow(scene)
    scene.frame_set(scene.frame_start)
    return {'instrument': 'piano', 'visual': 'PIANO_VISUAL', 'effect': effect, 'colors': colors,
            'camera': 'shots' if camera is not None else 'wide', 'note_count': len(notes), 'timing': 'beats'}
