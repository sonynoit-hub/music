"""Check PIANO_VISUAL's rising musical notes on a test phrase; the .blend is not saved.

Blender -b outputs/piano-visual.blend --python scripts/verify_piano_visual_notes.py [-- --renders DIR]
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
from guitar_video_app.integrations import piano_visual_notes as notes
from guitar_video_app.integrations import piano_visual_particles as pvp

FPS = 24
BUDGET = 4000                # polygons
BLEND = Path(bpy.data.filepath)
WHITE, BLACK, REPEAT = 60, 73, 64
# 120 bpm: a beat is 0.5 s. WHITE is a half note held 0.5-1.5 s; BLACK a quarter held 3.0-3.5 s that the pedal
# (3.25-5.0 s) keeps sounding to 5.0 s; REPEAT two eighths at 6.0 and 6.25 s; a chord of half notes at 7.0 s.
PHRASE = dict(version=1, instrument='piano', name='Notes check', fps=FPS, tempo_bpm=120, time_signature=[4, 4],
              end_beat=18, pedal_events=[dict(type='sustain', start_beat=6.5, duration_beats=3.5)],
              notes=[dict(id='w', pitch=WHITE, hand='right', start_beat=1, duration_beats=2),
                     dict(id='b', pitch=BLACK, hand='right', start_beat=6, duration_beats=1),
                     dict(id='r1', pitch=REPEAT, hand='right', start_beat=12, duration_beats=0.4),
                     dict(id='r2', pitch=REPEAT, hand='right', start_beat=12.5, duration_beats=0.4),
                     *(dict(id=f'c{p}', pitch=p, hand='left', start_beat=14, duration_beats=2) for p in (48, 52, 55))])
STARTS = {'w': 0.5, 'b': 3.0, 'r1': 6.0, 'r2': 6.25}
KINDS = {'w': 0, 'b': 1, 'r1': 2, 'r2': 2}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def at(seconds):
    bpy.context.scene.frame_set(round(seconds * FPS))


def seed(note_id):
    starts = [a.value for a in bpy.data.objects[pvp.OBJECT].data.attributes['pv_start'].data]
    return float(min(range(len(starts)), key=lambda i: abs(starts[i] - STARTS[note_id])))


def geometry(seconds):
    """Vertices in the keyboard frame's space with their part, note and glow."""
    at(seconds)
    obj = bpy.data.objects[pvp.OBJECT]
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
    mesh = evaluated.mesh
    if mesh is None or not len(mesh.vertices):
        return dict(co=np.zeros((0, 3)), part=np.zeros(0), seed=np.zeros(0), glow=np.zeros(0), polygons=0)
    count = len(mesh.vertices)
    co = np.empty(count * 3)
    mesh.vertices.foreach_get('co', co)
    values = {}
    for name in ('pv_part', 'pv_seed', 'pv_glow'):
        values[name] = np.empty(count)
        mesh.attributes[name].data.foreach_get('value', values[name])
    return dict(co=co.reshape(-1, 3), part=values['pv_part'], seed=values['pv_seed'], glow=values['pv_glow'],
                polygons=len(mesh.polygons))


def glyph(geo, note_id):
    pick = (geo['part'] == notes.PART_GLYPH) & (geo['seed'] == seed(note_id))
    return geo['co'][pick], geo['glow'][pick]


def glyph_notes(geo):
    return set(geo['seed'][geo['part'] == notes.PART_GLYPH])


def spawn(pitch):
    frame = bpy.data.objects[pv.FRAME_OBJECT]
    return np.array(frame.matrix_world.inverted() @ bpy.data.objects[pv.spawn_name(pitch)].matrix_world.translation)


def check_symbols():
    kinds = [a.value for a in bpy.data.objects[pvp.OBJECT].data.attributes['pv_kind'].data]
    for note_id, kind in KINDS.items():
        assert kinds[int(seed(note_id))] == kind, f'{note_id} should be kind {kind}'
    assert sorted(kinds).count(0) == 4, 'the chord should be half notes'
    for note_id, when in (('w', 1.0), ('b', 3.4), ('r1', 6.1)):
        co, _ = glyph(geometry(when), note_id)
        expected = len(notes.glyph(KINDS[note_id])[0])
        assert len(co) == expected, f'{note_id} drew {len(co)} vertices, its symbol has {expected}'


def check_timing():
    assert len(geometry(0.25)['co']) == 0, 'notes before the first key press'
    assert glyph_notes(geometry(0.55)) == {seed('w')}, 'one note at the first key press'
    assert glyph_notes(geometry(6.3)) >= {seed('r1'), seed('r2')}, 'a repeated key should give two notes'
    early, late = glyph(geometry(1.0), 'w')[0], glyph(geometry(2.0), 'w')[0]
    base = spawn(WHITE)
    reach = pv.WHITE_MM * pv.MM * notes.SCATTER / 2 + notes.SWAY + notes.SIZE
    assert abs(early[:, 0].mean() - base[0]) < reach, 'note is not over its key'
    assert early[:, 2].min() > base[2] - notes.SIZE, 'note below its key'
    assert late[:, 2].mean() - early[:, 2].mean() > 0.8 * notes.RISE, 'note did not rise'
    life = notes.life(dict(start=0.5, sound_end=1.5))
    assert len(glyph(geometry(0.5 + life - 0.1), 'w')[0]), 'note left too early'
    assert not len(glyph(geometry(0.5 + life + 0.05), 'w')[0]), 'note did not fade in time'


def check_glow():
    _, held = glyph(geometry(3.4), 'b')
    _, pedalled = glyph(geometry(4.5), 'b')
    ratio = pedalled.mean() / held.mean()
    assert math.isclose(ratio, notes.PEDAL_LEVEL, rel_tol=0.02), f'pedal-held note glows {ratio:.2f} of held'
    _, newborn = glyph(geometry(3.0 + 1 / FPS), 'b')
    assert newborn.mean() > 1.5 * held.mean(), 'no flash when the note is born'
    return ratio


def check_upright():
    co, _ = glyph(geometry(1.0), 'w')
    obj, camera = bpy.data.objects[pvp.OBJECT], bpy.context.scene.camera
    world = np.array([tuple(obj.matrix_world @ pv.Vector(p)) for p in co])
    view = np.array([tuple(camera.matrix_world.inverted() @ pv.Vector(p)) for p in world])
    centred = view - view.mean(axis=0)
    normal = np.linalg.svd(centred)[2][2]
    towards = -view.mean(axis=0) / np.linalg.norm(view.mean(axis=0))
    assert abs(normal @ towards) > 0.97, 'note does not face the camera'
    width, height = np.ptp(view[:, 0]), np.ptp(view[:, 1])
    assert height > 1.6 * width, f'note is not upright ({width:.3f} wide, {height:.3f} tall)'


def check_sparkles():
    geo = geometry(1.0)
    trail = (geo['part'] == notes.PART_TRAIL) & (geo['seed'] == seed('w'))
    count = trail.sum() // 4
    expected = notes.TRAIL_RATE * 0.5
    assert 0.85 * expected <= count <= 1.1 * expected, f'{count} sparkles, expected about {expected:.0f}'
    sparks = geo['co'][trail]
    assert sparks[:, 2].max() < glyph(geo, 'w')[0][:, 2].max() + notes.SIZE, 'sparkles above the note'
    life = notes.life(dict(start=0.5, sound_end=1.5))
    late = geometry(0.5 + notes.TRAIL_SHARE * life + notes.TRAIL_LIFE + 0.05)
    assert not ((late['part'] == notes.PART_TRAIL) & (late['seed'] == seed('w'))).any(), 'sparkles did not fade'
    return count


def check_seeking():
    def fingerprint(seconds):
        co = np.round(geometry(seconds)['co'], 6)
        return hashlib.sha256(co[np.lexsort(co.T)].tobytes()).hexdigest()
    first = fingerprint(4.5)
    for seconds in (7.5, 0.5, 2.0, 6.1):
        geometry(seconds)
    assert fingerprint(4.5) == first, 'the same frame gave different notes'


def check_keys_and_pedal():
    keys = pv.keys_by_midi()
    at(1.0)
    assert math.isclose(keys[WHITE].rotation_euler.x, keys[WHITE]['press_angle'], abs_tol=1e-6), 'key not down'
    at(4.5)
    sustain = bpy.data.objects[pv.pedal_name('sustain')]
    assert math.isclose(sustain.rotation_euler.x, sustain['press_angle'], abs_tol=1e-6), 'sustain pedal not down'


def check_budget(scene):
    peak, slowest = 0, 0.0
    for frame in range(scene.frame_start, scene.frame_end + 1, 2):
        started = time.perf_counter()
        peak = max(peak, geometry(frame / FPS)['polygons'])
        slowest = max(slowest, time.perf_counter() - started)
    assert peak <= BUDGET, f'{peak} polygons, budget {BUDGET}'
    return peak, slowest


def check_asset_untouched(asset_objects):
    root = bpy.data.collections[pv.ROOT]
    assert pvp.COLLECTION not in {c.name for c in root.children_recursive}, 'notes inside the asset'
    assert {o.name for o in root.all_objects} == asset_objects, 'asset objects changed'
    moving = [o.name for o in root.all_objects if o.animation_data and o.animation_data.action]
    assert not moving, f'animation baked into the asset: {moving[:3]}'


def colors(seconds, note_id=None, chord=False):
    """The main palette colour of a note's symbol at a time (the chord's when chord)."""
    at(seconds)
    obj = bpy.data.objects[pvp.OBJECT]
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
    mesh = evaluated.mesh
    count = len(mesh.vertices)
    part, which, main = np.empty(count), np.empty(count), np.empty(count * 4)
    mesh.attributes['pv_part'].data.foreach_get('value', part)
    mesh.attributes['pv_seed'].data.foreach_get('value', which)
    mesh.attributes['pv_main'].data.foreach_get('color', main)
    starts = [a.value for a in obj.data.attributes['pv_start'].data]
    pick = [float(i) for i, s in enumerate(starts) if abs(s - 7.0) < 1e-6] if chord else [seed(note_id)]
    rows = main.reshape(-1, 4)[(part == notes.PART_GLYPH) & np.isin(which, pick), :3]
    assert len(rows), f'no symbol at {seconds} s'
    return np.unique(np.round(rows, 4), axis=0)


def check_colors():
    """By hand: right-hand notes and their keys orange, left-hand blue; a theme colours everything alike."""
    keys = pv.keys_by_midi()
    orange, blue = pvp.PALETTES['orange'], pvp.PALETTES['blue']
    summary = pvp.install(PHRASE, colors='hands')
    assert summary['colors'] == 'hands' and bpy.context.scene[pvp.COLORS_PROPERTY] == 'hands'
    assert np.allclose(colors(1.0, 'w'), [orange[1]], atol=1e-3), 'right-hand note is not orange'
    assert np.allclose(colors(7.3, chord=True), [blue[1]], atol=1e-3), 'left-hand chord is not blue'
    at(1.0)
    assert np.allclose(tuple(keys[WHITE]['pv_highlight_color']), orange[3]), 'right-hand key glow is not orange'
    at(7.2)
    assert np.allclose(tuple(keys[48]['pv_highlight_color']), blue[3]), 'left-hand key glow is not blue'
    at(4.5)
    assert np.allclose(tuple(keys[BLACK]['pv_highlight_color']), orange[3]), 'pedal-held key lost its hand colour'
    gold = pvp.PALETTES['gold']
    pvp.install(PHRASE, colors='gold')
    assert np.allclose(colors(7.3, chord=True), [gold[1]], atol=1e-3), 'gold theme not applied'
    sustain = bpy.data.objects[pv.pedal_name('sustain')]
    assert np.allclose(tuple(sustain['pv_highlight_color']), gold[3]), 'pedal glow does not follow the theme'
    pvp.install(PHRASE)
    assert np.allclose(colors(1.0, 'w'), [blue[1]], atol=1e-3), 'blue is not the default'


def check_switching():
    """Plumes and back: one effect at a time, and a file reload rebuilds the stored effect."""
    templates = lambda: sorted(o.name for o in bpy.data.objects if o.name.startswith(f'{pv.PREFIX}_Note_'))
    assert len(templates()) == 3, 'note symbols missing'
    pvp.install(PHRASE, effect='plumes')
    assert not templates() and bpy.context.scene[pvp.EFFECT_PROPERTY] == 'plumes', 'note symbols left with plumes'
    pvp.install(PHRASE)
    pvp.register()
    assert len(templates()) == 3 and bpy.context.scene[pvp.EFFECT_PROPERTY] == 'notes', 'reload lost the notes'


def render_views(out):
    out.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.resolution_percentage = 50
    for seconds in (1.0, 4.5, 7.6):
        at(seconds)
        scene.render.filepath = str(out / f'notes_{seconds:.2f}s.png')
        bpy.ops.render.render(write_still=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--renders', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    before = sha(BLEND)
    asset_objects = {o.name for o in bpy.data.collections[pv.ROOT].all_objects}
    scene = bpy.context.scene
    summary = pvp.install(PHRASE)
    assert summary['effect'] == 'notes', 'notes should be the default effect'
    last = notes.fade_end(dict(start=7.0, sound_end=8.0))
    assert scene.render.fps == FPS and scene.frame_end >= math.ceil(last * FPS) - 1, 'frame range'
    check_symbols()
    check_timing()
    ratio = check_glow()
    check_upright()
    sparkles = check_sparkles()
    check_seeking()
    check_keys_and_pedal()
    peak, slowest = check_budget(scene)
    check_asset_untouched(asset_objects)
    check_colors()
    check_switching()
    if args.renders:
        render_views(args.renders)
    pvp.uninstall()
    leftovers = [o.name for o in bpy.data.objects if o.name.startswith(f'{pv.PREFIX}_Note_')]
    assert not leftovers and pvp.COLLECTION not in bpy.data.collections, f'cleanup left {leftovers}'
    assert sha(BLEND) == before, '.blend changed'
    print(f"PASS: {summary['note_count']} notes; half/quarter/eighth symbols by length; one note per key press, "
          f"rising and fading on time; pedal-held glow {ratio:.2f}; upright facing the camera; {sparkles} "
          f"sparkles in 0.5 s; colours by hand and by theme, keys and pedal glow to match; seeking deterministic; keys and pedal follow; peak {peak} polygons (budget "
          f"{BUDGET}), slowest evaluation {slowest * 1000:.0f} ms; asset and .blend unchanged")


main()
