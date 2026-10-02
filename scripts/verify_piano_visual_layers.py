"""Check PIANO_VISUAL's compositing layers and reference frames on a test piece; the .blend is not saved.

Blender -b outputs/piano-visual.blend --python scripts/verify_piano_visual_layers.py

The notes' Parts input splits symbols from halos and sparkles; setup_layers() renders the instrument, notes, shadow
and fx layers as transparent RGBA (the piano held out of notes and fx, the shadow a black Cycles matte); locked
shots hold one camera each; reference_frames() writes a reference, guide and mask per shot and cameras.json; and
teardown() puts the scene back as it was.
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
import numpy as np
from guitar_video_app.instruments.piano.camera import locked
from guitar_video_app.integrations import compositing
from guitar_video_app.integrations import piano_visual as pv
from guitar_video_app.integrations import piano_visual_camera as shot_camera
from guitar_video_app.integrations import piano_visual_notes as notes
from guitar_video_app.integrations import piano_visual_particles as pvp

FPS = 24
SCALE = 10                   # % of 1080x1920 for the test renders
BLEND = Path(bpy.data.filepath)
PLAN = dict(version=1, shots=[dict(start_bar=1, camera='hero', move='drift', transition='cut'),
                              dict(start_bar=3, camera='close', move='push', transition='blend')])
CAMERA_KEYS = {'shot', 'start_bar', 'camera', 'frame_start', 'frame_end', 'seconds_start', 'seconds_end', 'lens_mm',
               'sensor_mm', 'sensor_fit', 'shift_x', 'shift_y', 'fov_vertical_degrees', 'location',
               'rotation_euler_degrees', 'rotation_quaternion', 'horizon_from_bottom', 'floor_z', 'note_space',
               'files'}


def piece():
    """4 bars at 120 bpm of chords and a melody around middle C."""
    items = []
    for b in range(4):
        items += [dict(id=f'c{b}{p}', pitch=p, hand='left' if p < 60 else 'right', start_beat=b * 4,
                       duration_beats=2) for p in (48, 55, 64)]
        items += [dict(id=f'm{b}{k}', pitch=67 + k, hand='right', start_beat=b * 4 + 2 + k * 0.5,
                       duration_beats=0.5) for k in range(4)]
    return dict(version=1, instrument='piano', name='Layers check', fps=FPS, tempo_bpm=120, time_signature=[4, 4],
                notes=items)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parts_of(obj):
    modifier = obj.modifiers[pvp.MODIFIER]
    identifier = modifier.node_group.interface.items_tree[notes.PARTS_INPUT].identifier
    return getattr(modifier.properties.inputs, identifier).value


def points(obj):
    geometry = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
    return (len(geometry.mesh.vertices) if geometry.mesh else 0) + \
        (len(geometry.pointcloud.points) if geometry.pointcloud else 0)


def state(scene):
    render, floor = scene.render, bpy.data.objects[f'{pv.PREFIX}_Floor']
    return dict(
        engine=render.engine, film=render.film_transparent, compositing=render.use_compositing,
        layers=[(layer.name, layer.use) for layer in scene.view_layers],
        collections=sorted(c.name for c in bpy.data.collections), objects=sorted(o.name for o in bpy.data.objects),
        materials=sorted(m.name for m in bpy.data.materials), floor_collections=[c.name for c in floor.users_collection],
        catcher=floor.is_shadow_catcher, floor_scale=tuple(floor.scale), floor_material=floor.data.materials[0].name,
        seen=[(o.name, o.visible_camera) for o in bpy.data.collections[pv.ROOT].all_objects if o.type == 'MESH'],
        parts=parts_of(bpy.data.objects[pvp.OBJECT]), cycles=(scene.cycles.samples, scene.cycles.use_denoising,
                                                              scene.cycles.device),
        eevee=scene.eevee.taa_render_samples)


def read(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    image.colorspace_settings.name = 'Non-Color'
    width, height = image.size
    pixels = np.empty(width * height * 4, np.float32)
    image.pixels.foreach_get(pixels)
    bpy.data.images.remove(image)
    return pixels.reshape(height, width, 4)


def render_layers(scene, folder, frame):
    images = {}
    for name in compositing.LAYERS:
        compositing.use_layer(scene, name)
        assert scene.render.engine == ('CYCLES' if name == 'shadow' else 'BLENDER_EEVEE'), (name, scene.render.engine)
        compositing.configure_rgba_sequence(scene, folder / name, FPS, scale=SCALE)
        assert scene.render.film_transparent and scene.render.image_settings.color_mode == 'RGBA'
        scene.render.filepath = str(folder / f'{name}.png')
        scene.frame_set(frame)
        bpy.ops.render.render(write_still=True)
        images[name] = read(folder / f'{name}.png')
    return images


def layer_checks(images):
    alpha = {name: image[..., 3] for name, image in images.items()}
    piano = alpha['instrument'] > 0.99
    coverage = {name: float((a > 0.02).mean()) for name, a in alpha.items()}
    assert 0.05 < coverage['instrument'] < 0.9, coverage
    assert alpha['instrument'][-1].max() < 0.02, 'the top row should be empty: no floor or background in the instrument'
    for name in ('notes', 'fx'):
        assert coverage[name] > 0.001, f'the {name} layer is empty'
        assert alpha[name][piano].mean() < 0.02, f'the piano is not held out of the {name} layer'
    assert coverage['notes'] < coverage['instrument'], 'the notes layer shows more than the symbols'
    shadow = images['shadow']
    dark = alpha['shadow'] > 0.1
    assert 0.002 < dark.mean() < 0.6, f'shadow coverage {dark.mean():.3f}: the floor is not a shadow catcher'
    assert shadow[..., :3][dark].max() < 0.05, 'the shadow matte should be black'
    return coverage


def locked_checks(scene, path):
    spans = compositing.shot_frames(scene, path)
    assert [index for index, _, _ in spans] == list(range(len(PLAN['shots']))), spans
    for index, first, last in spans:
        matrices = []
        for frame in (first, (first + last) // 2, last):
            scene.frame_set(frame)
            matrices.append(np.array(scene.camera.matrix_world))
        assert all(np.allclose(m, matrices[0], atol=1e-5) for m in matrices), f'shot {index + 1} moved'
    return spans


def reference_checks(scene, path, folder):
    result = compositing.reference_frames(scene, path, folder, locked(PLAN)['shots'], samples=4)
    saved = json.loads((folder / 'cameras.json').read_text())
    assert saved == json.loads(json.dumps(result)) and len(saved['shots']) == len(PLAN['shots']), saved
    for shot, planned in zip(saved['shots'], PLAN['shots']):
        assert CAMERA_KEYS <= set(shot), CAMERA_KEYS - set(shot)
        assert shot['camera'] == planned['camera'] and shot['start_bar'] == planned['start_bar']
        assert shot['horizon_from_bottom'] is None or 0 <= shot['horizon_from_bottom'] <= 1.5, shot
        assert 10 < shot['fov_vertical_degrees'] < 120
        assert set(shot['files']) == {'reference', 'guide', 'mask'}
        reference, mask = read(folder / shot['files']['reference']), read(folder / shot['files']['mask'])
        assert reference[..., 3].min() > 0.99, 'the reference frame must be opaque'
        assert (folder / shot['files']['guide']).exists()
        kept = mask[..., 0] > 0.5
        assert 0.02 < kept.mean() < 0.98, f'the mask keeps {kept.mean():.2f} of the frame'
    assert not list(folder.glob('*_alpha.png')), 'temporary alpha renders were left behind'
    return saved


def main():
    before_file = sha(BLEND)
    scene = bpy.context.scene
    pvp.uninstall()
    data = piece()
    pvp.install(data, effect='notes', colors='blue', camera=locked(PLAN))
    path = shot_camera._path
    frame = round(2.6 * FPS)
    scene.frame_set(frame)
    main_object = bpy.data.objects[pvp.OBJECT]
    counts = {}
    for parts in (notes.PARTS_ALL, notes.PARTS_NOTES, notes.PARTS_FX):
        notes.set_parts(main_object, parts)
        counts[parts] = points(main_object)
    notes.set_parts(main_object, notes.PARTS_ALL)
    assert counts[notes.PARTS_NOTES] and counts[notes.PARTS_FX], counts
    assert counts[notes.PARTS_NOTES] + counts[notes.PARTS_FX] == counts[notes.PARTS_ALL], counts
    assert compositing.layers_for('plumes') == ('instrument', 'shadow', 'fx')

    before = state(scene)
    assert compositing.setup_layers(scene, 'notes') == compositing.LAYERS
    assert {f'PV_Layer_{n}' for n in (*compositing.LAYERS, 'reference')} <= {l.name for l in scene.view_layers}
    assert parts_of(main_object) == notes.PARTS_NOTES
    assert parts_of(bpy.data.objects[compositing.FX_OBJECT]) == notes.PARTS_FX
    assert not scene.render.use_compositing, 'bloom belongs in the compositing program'
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        coverage = layer_checks(render_layers(scene, folder, frame))
        spans = locked_checks(scene, path)
        cameras = reference_checks(scene, path, folder / 'reference')
    compositing.teardown(scene)
    after = state(scene)
    changed = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    assert not changed, f'teardown left changes: {changed}'
    compositing.teardown(scene)                      # a second teardown does nothing
    pvp.uninstall()
    assert sha(BLEND) == before_file, '.blend changed'
    print('BLENDER PASS: Parts splits {} symbol and {} effect points (sum {}); layers rendered as transparent RGBA '
          '(coverage instrument {instrument:.2f}, notes {notes:.3f}, shadow {shadow:.3f}, fx {fx:.3f}) with the piano '
          'held out of notes and fx and a black Cycles shadow matte; {} locked shots each hold one camera; {} reference '
          'frames with guide, mask and cameras.json; teardown restored the scene; .blend not saved'.format(
              counts[notes.PARTS_NOTES], counts[notes.PARTS_FX], counts[notes.PARTS_ALL], len(spans),
              len(cameras['shots']), **coverage))


main()
