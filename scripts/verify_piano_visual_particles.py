"""Check PIANO_VISUAL's particle plumes, key and pedal motion on a test phrase; the .blend is not saved.

Blender -b outputs/piano-visual.blend --python scripts/verify_piano_visual_particles.py [-- --renders DIR]
"""
import argparse
import hashlib
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
import numpy as np
from guitar_video_app.integrations import piano_visual as pv
from guitar_video_app.integrations import piano_visual_particles as pvp

FPS = 24
BUDGET = 6000
BLEND = Path(bpy.data.filepath)
WHITE, BLACK, REPEAT = 60, 73, 64
# 120 bpm: a beat is 0.5 s. WHITE is held 0.5-1.5 s with no pedal; BLACK is held 3.0-3.5 s and the pedal
# (3.25-5.0 s) keeps it sounding to 5.0 s; REPEAT strikes twice at 6.0 and 6.25 s; a chord starts at 7.0 s.
PHRASE = dict(version=1, instrument='piano', name='Plume check', fps=FPS, tempo_bpm=120, time_signature=[4, 4],
              end_beat=18, pedal_events=[dict(type='sustain', start_beat=6.5, duration_beats=3.5)],
              notes=[dict(id='w', pitch=WHITE, hand='right', start_beat=1, duration_beats=2),
                     dict(id='b', pitch=BLACK, hand='right', start_beat=6, duration_beats=1),
                     dict(id='r1', pitch=REPEAT, hand='right', start_beat=12, duration_beats=0.4),
                     dict(id='r2', pitch=REPEAT, hand='right', start_beat=12.5, duration_beats=0.4),
                     *(dict(id=f'c{p}', pitch=p, hand='left', start_beat=14, duration_beats=2) for p in (48, 52, 55))])


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def at(seconds):
    scene = bpy.context.scene
    scene.frame_set(round(seconds * FPS))


def particles(seconds):
    """Sprite centers (n x 3) in the keyboard frame's space at a time."""
    at(seconds)
    obj = bpy.data.objects[pvp.OBJECT]
    geometry = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
    mesh = geometry.mesh
    if mesh is None or not len(mesh.vertices):
        return np.zeros((0, 3))
    co = np.empty(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get('co', co)
    return co.reshape(-1, 4, 3).mean(axis=1)


def spawn(pitch):
    frame = bpy.data.objects[pv.FRAME_OBJECT]
    return np.array(frame.matrix_world.inverted() @ bpy.data.objects[pv.spawn_name(pitch)].matrix_world.translation)


def near(points, pitch, radius=0.09):
    return points[np.abs(points[:, 0] - spawn(pitch)[0]) < radius]


def young(points, pitch):
    """Particles just born over the key: still within a few centimetres of its spawn point."""
    base = spawn(pitch)
    return points[(np.abs(points[:, 0] - base[0]) < 0.03) & (points[:, 2] < base[2] + 0.04)]


def check_timing():
    assert len(particles(0.25)) == 0, 'particles before the first note'
    held = particles(1.25)
    count = len(near(held, WHITE))
    expected = pvp.RATE * 0.75
    assert 0.85 * expected <= count <= 1.05 * expected, f'held key emitted {count}, expected about {expected:.0f}'
    base = spawn(WHITE)
    assert abs(held[:, 0].mean() - base[0]) < 0.02, 'plume is not over its key'
    assert held[:, 2].min() > base[2] - 0.01, 'particles below the spawn point'
    assert len(young(held, WHITE)) > 20, 'no particles leaving a held key'
    released = near(particles(2.5), WHITE)
    assert len(released) > 0 and len(young(released, WHITE)) == 0, 'released key should float, not emit'
    assert released[:, 2].min() > base[2] + 0.15, 'released plume did not rise'
    assert len(near(particles(1.5 + pvp.LIFE + 0.05), WHITE)) == 0, 'released plume did not fade in time'
    return count


def check_sustain():
    held = len(young(particles(3.4), BLACK))
    pedalled = len(young(particles(4.5), BLACK))
    assert 0.15 * held < pedalled < 0.7 * held, f'pedal-held emission {pedalled} vs held {held}'
    assert len(young(particles(5.3), BLACK)) == 0, 'emission continued after the pedal lifted'
    return held, pedalled


def check_seeking():
    def fingerprint(seconds):
        points = np.round(particles(seconds), 6)
        return hashlib.sha256(points[np.lexsort(points.T)].tobytes()).hexdigest()
    first = fingerprint(4.5)
    for seconds in (7.5, 0.5, 2.0, 6.1):
        particles(seconds)
    assert fingerprint(4.5) == first, 'the same frame gave different particles'


def check_keys_and_pedal():
    keys = pv.keys_by_midi()
    at(1.0)
    key = keys[WHITE]
    assert math.isclose(key.rotation_euler.x, key['press_angle'], abs_tol=1e-6), 'held key is not down'
    assert key['pv_highlight'] == 1.0, 'held key does not glow'
    assert np.allclose(tuple(key['pv_highlight_color']), pvp.KEY_GLOW_COLOR), 'key glow is not blue'
    at(2.0)
    assert key.rotation_euler.x == 0 and key['pv_highlight'] == 0, 'released key did not rest'
    at(4.5)
    assert keys[BLACK].rotation_euler.x == 0, 'pedal must not hold the key down'
    assert math.isclose(keys[BLACK]['pv_highlight'], pvp.KEY_SUSTAIN_GLOW), 'pedal-held key should glow softly'
    sustain = bpy.data.objects[pv.pedal_name('sustain')]
    assert math.isclose(sustain.rotation_euler.x, sustain['press_angle'], abs_tol=1e-6), 'sustain pedal not down'
    for other in ('soft', 'sostenuto'):
        assert bpy.data.objects[pv.pedal_name(other)].rotation_euler.x == 0, f'{other} pedal moved'
    at(6.1)
    assert keys[REPEAT].rotation_euler.x > 0, 'repeated key not pressed'
    at(5.5)
    assert sustain.rotation_euler.x == 0, 'sustain pedal did not return'


def check_budget(scene):
    peak, slowest = 0, 0.0
    for frame in range(scene.frame_start, scene.frame_end + 1, 2):
        started = time.perf_counter()
        peak = max(peak, len(particles(frame / FPS)))
        slowest = max(slowest, time.perf_counter() - started)
    assert peak <= BUDGET, f'{peak} particles, budget {BUDGET}'
    return peak, slowest


def check_asset_untouched(asset_objects):
    root = bpy.data.collections[pv.ROOT]
    assert pvp.COLLECTION not in {c.name for c in root.children_recursive}, 'plumes inside the asset'
    assert {o.name for o in root.all_objects} == asset_objects, 'asset objects changed'
    moving = [o.name for o in root.all_objects if o.animation_data and o.animation_data.action]
    assert not moving, f'animation baked into the asset: {moving[:3]}'


def render_views(out):
    out.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.resolution_percentage = 50
    for seconds in (1.25, 4.5, 7.6):
        at(seconds)
        scene.render.filepath = str(out / f'plumes_{seconds:.2f}s.png')
        bpy.ops.render.render(write_still=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--renders', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    before = sha(BLEND)
    asset_objects = {o.name for o in bpy.data.collections[pv.ROOT].all_objects}
    scene = bpy.context.scene
    summary = pvp.install(PHRASE, effect='plumes')
    assert scene.render.fps == FPS and scene.frame_end >= round((7.0 + 1.0 + pvp.LIFE) * FPS), 'frame range'
    count = check_timing()
    held, pedalled = check_sustain()
    check_seeking()
    check_keys_and_pedal()
    peak, slowest = check_budget(scene)
    check_asset_untouched(asset_objects)
    if args.renders:
        render_views(args.renders)
    pvp.remove_plumes()
    pv.reset_keys()
    pv.reset_pedals()
    assert pvp.COLLECTION not in bpy.data.collections and sha(BLEND) == before, 'cleanup or file changed'
    print(f"PASS: {summary['note_count']} notes; held key {count} particles in 0.75 s; young particles held "
          f"{held} vs pedal {pedalled}; seeking deterministic; keys and pedals follow; peak {peak} particles "
          f"(budget {BUDGET}), slowest evaluation {slowest * 1000:.0f} ms; asset and .blend unchanged")


main()
