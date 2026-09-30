"""Rising musical notes for PIANO_VISUAL: one glowing note symbol per key press.

The symbol follows the written length (half, quarter or eighth, see piano_visual_particles.note_kind). It pops in
at the key, rises with a gentle sway, stays bright while the key is held, dims while only the pedal holds it and
fades out at the end of its life, dropping a faint trail of sparkles. Everything is a pure function of the scene
time, like the plumes, so any frame can be rendered alone and nothing is baked.
"""
from __future__ import annotations

import math

import bpy

from guitar_video_app.integrations import piano_visual as pv
from guitar_video_app.integrations import piano_visual_particles as particles

TREE = 'PV_Notes'
MATERIAL = 'PV_NoteGlyph'
GLYPHS = ('Half', 'Quarter', 'Eighth')      # by pv_kind
LIFE = 2.4                   # seconds a note lives after its key is pressed ...
HOLD_MAX = 2.0               # ... plus how long it sounds, up to this
SIZE = 0.075                 # m from the note head to the top of the stem
LIFT = 0.03                  # m above the key where a note appears
RISE = 0.2                   # m/s
RISE_ACCEL = 0.04            # m/s^2
SWAY = 0.012                 # m
SWAY_HZ = 0.4
SCATTER = 0.6                # share of the key width a note may start off its centre
POP_SECONDS = 0.15
GLOW = 5.0
FLASH = 10.0                 # extra glow of a newborn note
FLASH_SECONDS = 0.25
PEDAL_LEVEL = 0.75           # glow while only the pedal holds the note
AFTER_LEVEL = 0.55           # glow once the note has stopped sounding
FADE_SHARE = 0.4             # the last share of a life fades out
HEAT = 0.72                  # colour ramp position of a newborn note, cooling by HEAT_DROP over its life
HEAT_DROP = 0.35
HALO_SIZE = 0.16             # m across the soft glow behind a note, in final renders only: viewports draw it as a square
HALO_GLOW = 1.0
HALO_ALPHA = 0.35
TRAIL_RATE = 50.0            # sparkles per second
TRAIL_LIFE = 0.8
TRAIL_SLOTS = round(TRAIL_RATE * TRAIL_LIFE)
TRAIL_SHARE = 0.75           # a note stops dropping sparkles after this share of its life
TRAIL_FALL = 0.03            # m/s
TRAIL_SCATTER = 0.03         # m/s
TRAIL_GLOW = 6.0
TRAIL_RADIUS = 0.0018
PART_GLYPH, PART_HALO, PART_TRAIL = 0.0, 1.0, 2.0


def life(note):
    return LIFE + min(note['sound_end'] - note['start'], HOLD_MAX)


def fade_end(note):
    """When the note and its last sparkle have faded, in seconds."""
    span = life(note)
    return note['start'] + max(span, TRAIL_SHARE * span + TRAIL_LIFE)


# Glyphs: flat meshes in XY facing +Z, head centred on the origin, stem top at y = 1.

def _ellipse(rx, ry, tilt, count=24):
    c, s = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))
    return [(rx * math.cos(a) * c - ry * math.sin(a) * s, rx * math.cos(a) * s + ry * math.sin(a) * c, 0.0)
            for a in (2 * math.pi * i / count for i in range(count))]


def _bezier(p0, p1, p2, steps):
    return [tuple((1 - t) ** 2 * a + 2 * (1 - t) * t * b + t * t * c for a, b, c in zip(p0, p1, p2)) + (0.0,)
            for t in (i / steps for i in range(steps + 1))]


def glyph(kind):
    """(vertices, faces) of a half (0), quarter (1) or eighth (2) note."""
    verts, faces = [], []

    def add(points, polys):
        base = len(verts)
        verts.extend(points)
        faces.extend([tuple(base + i for i in poly) for poly in polys])

    outer = _ellipse(0.30, 0.21, 20)
    n = len(outer)
    if kind == 0:
        add(outer + _ellipse(0.20, 0.09, 35), [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)])
    else:
        add(outer, [tuple(range(n))])
    add([(0.25, 0.0, 0.0), (0.29, 0.0, 0.0), (0.29, 1.0, 0.0), (0.25, 1.0, 0.0)], [(0, 1, 2, 3)])
    if kind == 2:
        steps = 10
        edge = _bezier((0.29, 1.0), (0.60, 0.74), (0.50, 0.36), steps)
        inner = _bezier((0.29, 0.80), (0.50, 0.64), (0.50, 0.36), steps)
        add(edge + inner, [(steps + 1 + i, steps + 2 + i, i + 1, i) for i in range(steps)])
    return verts, faces


def _glyph_objects(collection):
    objects = []
    for kind, name in enumerate(GLYPHS):
        mesh = bpy.data.meshes.new(f'{pv.PREFIX}_Note_{name}')
        verts, faces = glyph(kind)
        mesh.from_pydata(verts, [], faces)
        obj = bpy.data.objects.new(mesh.name, mesh)
        collection.objects.link(obj)
        obj.hide_viewport = obj.hide_render = obj.hide_select = True
        objects.append(obj)
    return objects


# Geometry Nodes

def _drift(g, age, seed, width):
    """Offset of a note from its key's spawn anchor at a given age."""
    m = g.math
    across = m('MULTIPLY', m('SUBTRACT', g.random(seed, 101), 0.5), m('MULTIPLY', width, SCATTER))
    swing = m('SINE', m('ADD', m('MULTIPLY', age, 2 * math.pi * SWAY_HZ), m('MULTIPLY', seed, 2.39996)))
    sway = m('MULTIPLY', m('MULTIPLY', SWAY, swing), m('MINIMUM', 1, m('DIVIDE', age, 0.8)))
    rise = m('ADD', m('ADD', LIFT, m('MULTIPLY', RISE, age)), m('MULTIPLY', 0.5 * RISE_ACCEL, m('MULTIPLY', age, age)))
    return g.xyz(m('ADD', across, sway), 0, rise)


def _store(g, geometry, **values):
    for name, value in values.items():
        geometry = g.geometry('GeometryNodeStoreNamedAttribute', geometry, domain='POINT', data_type='FLOAT',
                              Name=name, Value=value).outputs[0]
    return geometry


def notes_tree(collection):
    g, points, output, now = particles.new_tree(TREE)
    m, v = g.math, g.vector
    start, end, sound_end = (g.attribute(n) for n in ('pv_start', 'pv_end', 'pv_sound_end'))
    seed, width, kind = g.attribute('pv_seed'), g.attribute('pv_width'), g.attribute('pv_kind')
    span = m('ADD', LIFE, m('MINIMUM', m('SUBTRACT', sound_end, start), HOLD_MAX))
    age = m('SUBTRACT', now, start)
    t = m('DIVIDE', age, span)

    # The note symbols, with a soft halo behind each.
    unborn_or_gone = m('MAXIMUM', m('LESS_THAN', age, 0), m('GREATER_THAN', t, 1))
    living = g.geometry('GeometryNodeDeleteGeometry', points, domain='POINT', Selection=unborn_or_gone).outputs[0]
    moved = g.geometry('GeometryNodeSetPosition', living, Offset=_drift(g, age, seed, width)).outputs[0]
    level = m('MAXIMUM', m('LESS_THAN', now, end),
              m('MAXIMUM', m('MULTIPLY', PEDAL_LEVEL, m('LESS_THAN', now, sound_end)), AFTER_LEVEL))
    fade = m('MINIMUM', 1, m('DIVIDE', m('SUBTRACT', 1, t), FADE_SHARE))
    flash = m('MULTIPLY', FLASH, m('MAXIMUM', 0, m('SUBTRACT', 1, m('DIVIDE', age, FLASH_SECONDS))))
    glow = m('MULTIPLY', m('ADD', m('MULTIPLY', GLOW, level), flash), fade)
    heat = m('SUBTRACT', HEAT, m('MULTIPLY', HEAT_DROP, t))
    shown = _store(g, moved, pv_heat=heat, pv_glow=glow, pv_alpha=fade, pv_part=PART_GLYPH)
    pop = m('SUBTRACT', 1, m('POWER', m('SUBTRACT', 1, m('MINIMUM', 1, m('DIVIDE', age, POP_SECONDS))), 3))
    rotation = particles.facing_camera(g, upright=True)
    symbols = g.node('GeometryNodeJoinGeometry')
    for index, template in enumerate(_glyph_objects(collection)):
        info = g.node('GeometryNodeObjectInfo', transform_space='ORIGINAL')
        info.inputs['Object'].default_value = template
        instances = g.node('GeometryNodeInstanceOnPoints')
        g.feed(instances.inputs['Points'], shown)
        g.feed(instances.inputs['Selection'], m('COMPARE', kind, index, 0.1))
        g.feed(instances.inputs['Instance'], info.outputs['Geometry'])
        g.feed(instances.inputs['Rotation'], rotation)
        g.feed(instances.inputs['Scale'], m('MULTIPLY', SIZE, pop))
        g.feed(symbols.inputs[0], instances.outputs[0])
    real = g.geometry('GeometryNodeRealizeInstances', symbols.outputs[0]).outputs[0]
    glyphs = g.geometry('GeometryNodeSetMaterial', real,
                        Material=particles.glow_material(MATERIAL, painted=False)).outputs[0]

    halo = g.geometry('GeometryNodeSetPosition', moved, Offset=(0.0, 0.0, 0.4 * SIZE)).outputs[0]
    halo = _store(g, halo, pv_heat=0.5, pv_glow=m('MULTIPLY', m('MULTIPLY', HALO_GLOW, level), fade),
                  pv_alpha=m('MULTIPLY', HALO_ALPHA, fade), pv_part=PART_HALO)
    halo = g.geometry('GeometryNodeSetPointRadius', halo, Radius=m('MULTIPLY', HALO_SIZE / particles.SPRITE, pop))
    viewport = g.node('GeometryNodeIsViewport').outputs[0]
    halo = g.geometry('GeometryNodeDeleteGeometry', halo.outputs[0], domain='POINT', Selection=viewport).outputs[0]

    # The sparkle trail: each sparkle starts where its note was when it was dropped, then sinks and fades.
    gone = m('MAXIMUM', m('LESS_THAN', age, 0), m('GREATER_THAN', age, m('ADD', m('MULTIPLY', span, TRAIL_SHARE),
                                                                         TRAIL_LIFE)))
    trailing = g.geometry('GeometryNodeDeleteGeometry', points, domain='POINT', Selection=gone).outputs[0]
    slots, emitted, ident, birth, spark_age = particles.emission(g, trailing, now, start, TRAIL_RATE, TRAIL_SLOTS)
    dropped_at = m('SUBTRACT', birth, start)
    shine = m('DIVIDE', spark_age, TRAIL_LIFE)
    rand = [g.random(ident, m('ADD', m('MULTIPLY', seed, 16), j)) for j in range(3)]
    around = g.random(ident, m('ADD', m('MULTIPLY', seed, 16), 3), (-0.35 * SIZE, -0.01, -0.2 * SIZE),
                      (0.45 * SIZE, 0.01, 0.9 * SIZE))
    scatter = v('SCALE', g.random(ident, m('ADD', m('MULTIPLY', seed, 16), 4), (-1, -1, -1), (1, 1, 1)),
                m('MULTIPLY', TRAIL_SCATTER, spark_age))
    offset = v('ADD', v('ADD', _drift(g, dropped_at, seed, width), around),
               v('ADD', scatter, g.xyz(0, 0, m('MULTIPLY', -TRAIL_FALL, spark_age))))
    sparks = g.geometry('GeometryNodeSetPosition', slots, Offset=offset).outputs[0]
    phase = m('ADD', m('MULTIPLY', now, 23), m('MULTIPLY', rand[0], 62.8))
    twinkle = m('ADD', 0.4, m('MULTIPLY', 1.6, m('MAXIMUM', 0, m('SINE', phase))))
    spark_glow = m('MULTIPLY', m('MULTIPLY', TRAIL_GLOW, m('POWER', m('SUBTRACT', 1, shine), 1.5)), twinkle)
    sparks = _store(g, sparks, pv_heat=m('SUBTRACT', 1, shine), pv_glow=spark_glow, pv_alpha=1.0,
                    pv_part=PART_TRAIL)
    radius = m('MULTIPLY', m('MULTIPLY', TRAIL_RADIUS, m('ADD', 0.6, m('MULTIPLY', rand[1], 0.8))),
               m('SUBTRACT', 1, m('MULTIPLY', 0.5, shine)))
    sparks = g.geometry('GeometryNodeSetPointRadius', sparks, Radius=radius).outputs[0]
    dropping = m('MULTIPLY', m('GREATER_THAN', emitted, -1e-4), m('LESS_THAN', dropped_at, m('MULTIPLY', span,
                                                                                            TRAIL_SHARE)))
    sparks = g.geometry('GeometryNodeDeleteGeometry', sparks, domain='POINT',
                        Selection=m('SUBTRACT', 1, dropping)).outputs[0]

    glows = g.node('GeometryNodeJoinGeometry')
    g.feed(glows.inputs[0], sparks)
    g.feed(glows.inputs[0], halo)
    everything = g.node('GeometryNodeJoinGeometry')
    g.feed(everything.inputs[0], particles.sprites(g, glows.outputs[0]))
    g.feed(everything.inputs[0], glyphs)
    g.feed(output.inputs[0], everything.outputs[0])
    return g.tree
