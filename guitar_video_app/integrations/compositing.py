"""PIANO_VISUAL foreground layers and reference frames for compositing over an AI background made elsewhere.

The music animation stays in piano_visual_particles / piano_visual_notes / piano_visual_camera; this module only
decides what each render shows. setup_layers() adds one view layer per compositing layer and teardown() removes
them again, so nothing here is meant to be saved into a .blend:

- instrument: the piano (PIANO_VISUAL_ROOT) lit by the stage lights, on a transparent film, without the floor.
- notes: the rising note symbols only; the piano is a holdout, so notes behind it are cut out.
- shadow: the piano's shadow on the floor as a black RGBA matte. EEVEE ignores shadow catchers, so this layer
  renders with Cycles: the floor is a shadow catcher and the piano casts shadows without being seen.
- fx: the notes' halos and sparkles (a second object sharing the notes' events, Parts = FX), or the whole plume
  effect; the piano is a holdout.

The compositor bloom is off in every layer: glow is added in the compositing program, where it can spread over
the background. reference_frames() renders, per shot, an opaque reference, a guide with a perspective floor grid,
horizon and safe areas, a mask of the space the foreground keeps, and cameras.json.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

LAYERS = ('instrument', 'notes', 'shadow', 'fx')
VIEW_LAYER = 'PV_Layer_{}'
FLOOR_COLLECTION = 'PIANO_VISUAL_FLOOR'
FX_COLLECTION = 'PIANO_VISUAL_FX'
FX_OBJECT = 'PianoVisual_FX'
REFERENCE_LAYER = 'PV_Layer_reference'
SHADOW_SAMPLES = 16
REFERENCE_GREY = 0.18                    # linear mid grey of the reference floor and background
GRID_SPACING = 0.25                      # m between guide grid lines on the floor
GRID_LINE = 0.006                        # m half width of a guide grid line
REFERENCE_SAMPLES = 16
REFERENCE_FLOOR_SCALE = 40               # the floor is stretched this much so it reaches the horizon

_saved = {}


def layers_for(effect: str) -> tuple[str, ...]:
    """The layers an effect fills: plumes have no note symbols, so no notes layer."""
    return LAYERS if effect == 'notes' else tuple(n for n in LAYERS if n != 'notes')


def configure_rgba_sequence(scene, output: Path, fps: int, resolution=(1080, 1920), scale=100) -> None:
    """Transparent 16-bit RGBA PNG sequence settings shared by every layer render."""
    render = scene.render
    render.fps = fps
    render.fps_base = 1
    render.resolution_x, render.resolution_y = resolution
    render.resolution_percentage = scale
    render.film_transparent = True
    render.filepath = str(Path(output).resolve())
    if hasattr(render.image_settings, 'media_type'):
        render.image_settings.media_type = 'IMAGE'
    render.image_settings.file_format = 'PNG'
    render.image_settings.color_mode = 'RGBA'
    render.image_settings.color_depth = '16'
    render.image_settings.compression = 15


def _layer_collection(layer_collection, name):
    if layer_collection.collection.name == name:
        return layer_collection
    for child in layer_collection.children:
        found = _layer_collection(child, name)
        if found:
            return found
    return None


def _set_holdout(layer_collection, holdout):
    """Holdout on a collection does not reach its child collections, so set the whole tree."""
    layer_collection.holdout = holdout
    for child in layer_collection.children:
        _set_holdout(child, holdout)


def _piano_meshes():
    import bpy
    from guitar_video_app.integrations import piano_visual as pv
    return [o for o in bpy.data.collections[pv.ROOT].all_objects if o.type == 'MESH']


def _cycles_gpu(scene):
    """Use the Metal GPU for Cycles when there is one; returns what to restore."""
    import bpy
    saved = dict(device=scene.cycles.device)
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        saved['type'] = prefs.compute_device_type
        prefs.compute_device_type = 'METAL'
        prefs.get_devices()
        saved['devices'] = [(d, d.use) for d in prefs.devices]
        for device in prefs.devices:
            device.use = True
        scene.cycles.device = 'GPU'
    except Exception:
        scene.cycles.device = 'CPU'
    return saved


def setup_layers(scene, effect: str) -> tuple[str, ...]:
    """Add the compositing view layers for an installed PIANO_VISUAL song; returns the layers it can render."""
    import bpy
    from guitar_video_app.integrations import piano_visual as pv
    from guitar_video_app.integrations import piano_visual_camera as shot_camera
    from guitar_video_app.integrations import piano_visual_notes as notes
    from guitar_video_app.integrations import piano_visual_particles as particles

    if _saved:
        teardown(scene)
    render = scene.render
    floor = bpy.data.objects[f'{pv.PREFIX}_Floor']
    stage = bpy.data.collections[pv.PRESENTATION]
    _saved.update(engine=render.engine, film=render.film_transparent, compositing=render.use_compositing,
                  uses=[(layer.name, layer.use) for layer in scene.view_layers], catcher=floor.is_shadow_catcher,
                  seen={o.name: o.visible_camera for o in _piano_meshes()}, effect=effect,
                  cycles=dict(samples=scene.cycles.samples, denoise=scene.cycles.use_denoising,
                              device=scene.cycles.device))

    floors = bpy.data.collections.new(FLOOR_COLLECTION)
    scene.collection.children.link(floors)
    floors.objects.link(floor)
    stage.objects.unlink(floor)

    main = bpy.data.objects.get(particles.OBJECT)
    if effect == 'notes' and main is not None:
        fx = main.copy()
        fx.name = FX_OBJECT
        effects = bpy.data.collections.new(FX_COLLECTION)
        scene.collection.children.link(effects)
        effects.objects.link(fx)
        notes.set_parts(main, notes.PARTS_NOTES)
        notes.set_parts(fx, notes.PARTS_FX)

    known = {pv.ROOT, pv.PRESENTATION, shot_camera.COLLECTION, particles.COLLECTION, FLOOR_COLLECTION, FX_COLLECTION}
    # What each layer shows: True included, 'holdout' masks what is behind it, False excluded.
    plan = {
        'instrument': {pv.ROOT: True},
        'notes': {pv.ROOT: 'holdout', particles.COLLECTION: True},
        'shadow': {pv.ROOT: True, FLOOR_COLLECTION: True},
        'fx': {pv.ROOT: 'holdout', FX_COLLECTION if effect == 'notes' else particles.COLLECTION: True},
        'reference': {pv.ROOT: True, FLOOR_COLLECTION: True},
    }
    for name, shown in plan.items():
        layer = scene.view_layers.new(VIEW_LAYER.format(name))
        for collection in scene.collection.children:
            lc = _layer_collection(layer.layer_collection, collection.name)
            if collection.name in (pv.PRESENTATION, shot_camera.COLLECTION):
                continue                       # lights and cameras everywhere
            state = shown.get(collection.name, name == 'instrument' and collection.name not in known)
            lc.exclude = state is False
            _set_holdout(lc, state == 'holdout')
        layer.use = False
    render.film_transparent = True
    render.use_compositing = False
    return layers_for(effect)


def use_layer(scene, name: str) -> None:
    """Render only this compositing layer (view layer, engine and shadow-catcher settings)."""
    import bpy
    from guitar_video_app.integrations import piano_visual as pv

    if name not in LAYERS and name != 'reference':
        raise ValueError(f'Unknown layer {name!r}; use one of {", ".join(LAYERS)}.')
    for layer in scene.view_layers:
        layer.use = layer.name == VIEW_LAYER.format(name)
    shadow = name == 'shadow'
    bpy.data.objects[f'{pv.PREFIX}_Floor'].is_shadow_catcher = shadow
    for obj in _piano_meshes():
        obj.visible_camera = _saved['seen'][obj.name] and not shadow
    if shadow:
        scene.render.engine = 'CYCLES'
        scene.cycles.samples = SHADOW_SAMPLES
        scene.cycles.use_denoising = True
        if 'gpu' not in _saved:
            _saved['gpu'] = _cycles_gpu(scene)
    else:
        scene.render.engine = _saved['engine']
    scene.render.film_transparent = name != 'reference'


def teardown(scene) -> None:
    """Remove everything setup_layers added and put back what it changed."""
    import bpy
    from guitar_video_app.integrations import piano_visual as pv
    from guitar_video_app.integrations import piano_visual_notes as notes
    from guitar_video_app.integrations import piano_visual_particles as particles

    if not _saved:
        return
    for layer in [l for l in scene.view_layers if l.name.startswith('PV_Layer_')]:
        scene.view_layers.remove(layer)
    for name, use in _saved['uses']:
        if name in scene.view_layers:
            scene.view_layers[name].use = use
    floor = bpy.data.objects[f'{pv.PREFIX}_Floor']
    stage = bpy.data.collections[pv.PRESENTATION]
    if floor.name not in stage.objects:
        stage.objects.link(floor)
    floors = bpy.data.collections.get(FLOOR_COLLECTION)
    if floors:
        bpy.data.collections.remove(floors)
    fx = bpy.data.objects.get(FX_OBJECT)
    if fx:
        bpy.data.objects.remove(fx, do_unlink=True)
    effects = bpy.data.collections.get(FX_COLLECTION)
    if effects:
        bpy.data.collections.remove(effects)
    main = bpy.data.objects.get(particles.OBJECT)
    if main is not None and _saved['effect'] == 'notes':
        notes.set_parts(main, notes.PARTS_ALL)
    floor.is_shadow_catcher = _saved['catcher']
    for obj in _piano_meshes():
        obj.visible_camera = _saved['seen'].get(obj.name, True)
    render = scene.render
    render.engine, render.film_transparent, render.use_compositing = (_saved['engine'], _saved['film'],
                                                                      _saved['compositing'])
    cycles = _saved['cycles']
    scene.cycles.samples, scene.cycles.use_denoising, scene.cycles.device = (cycles['samples'], cycles['denoise'],
                                                                             cycles['device'])
    gpu = _saved.get('gpu')
    if gpu and 'type' in gpu:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        for device, use in gpu.get('devices', []):
            device.use = use
        prefs.compute_device_type = gpu['type']
    _saved.clear()


# Shots

def shot_frames(scene, path) -> list[tuple[int, int, int]]:
    """(shot index, first, last frame) of each shot of a camera path seen in the scene's frame range; one span of
    shot 0 without a path."""
    fps = scene.render.fps / scene.render.fps_base
    first, last = scene.frame_start, scene.frame_end
    if path is None:
        return [(0, first, last)]
    spans = []
    for frame in range(first, last + 1):
        index = path.shot_index(frame / fps)
        if spans and spans[-1][0] == index:
            spans[-1][2] = frame
        else:
            spans.append([index, frame, frame])
    return [tuple(span) for span in spans]


# Reference frames

def _project(scene, camera, point):
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    p = world_to_camera_view(scene, camera, Vector(point))
    return p.x, p.y, p.z


def horizon(scene, camera) -> float | None:
    """Image height (0 bottom, 1 top) of the floor's horizon, or None when it is outside the frame's side."""
    from mathutils import Vector
    forward = camera.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    flat = Vector((forward.x, forward.y, 0))
    if flat.length < 1e-6:
        return None
    far = camera.matrix_world.translation + flat.normalized() * 1e5
    x, y, z = _project(scene, camera, far)
    return y if z > 0 else None


def note_space(scene, camera) -> list[tuple[float, float]]:
    """Image corners (0-1, y up) of the box above the keys that the rising notes use."""
    import bpy
    from guitar_video_app.instruments.piano.camera import HALF_KEYBOARD, KEY_DEPTH, RISE_SHOWN
    from guitar_video_app.integrations import piano_visual as pv
    frame = bpy.data.objects[pv.FRAME_OBJECT].matrix_world
    from mathutils import Vector
    corners = [frame @ Vector((x, y, z)) for x in (-HALF_KEYBOARD, HALF_KEYBOARD) for y in (0.0, KEY_DEPTH)
               for z in (0.0, RISE_SHOWN)]
    return [(p[0], p[1]) for p in (_project(scene, camera, c) for c in corners) if p[2] > 0]


def _hull(points):
    points = sorted(set(points))
    if len(points) < 3:
        return points
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _inside_hull(hull, width, height):
    """Boolean (height, width) image of pixels inside a convex hull given in 0-1 image coordinates."""
    import numpy as np
    ys, xs = np.mgrid[0:height, 0:width]
    u, v = (xs + 0.5) / width, (ys + 0.5) / height
    inside = np.ones((height, width), bool)
    for (x0, y0), (x1, y1) in zip(hull, hull[1:] + hull[:1]):
        inside &= (x1 - x0) * (v - y0) - (y1 - y0) * (u - x0) >= 0
    return inside


def _pixels(path):
    import bpy
    import numpy as np
    image = bpy.data.images.load(str(path), check_existing=False)
    width, height = image.size
    pixels = np.empty(width * height * 4, np.float32)
    image.pixels.foreach_get(pixels)
    return image, pixels.reshape(height, width, 4)


def _save(image, pixels, path):
    image.pixels.foreach_set(pixels.ravel())
    image.filepath_raw = str(path)
    image.file_format = 'PNG'
    image.save()


def _line(pixels, x0, y0, x1, y1, color, thickness=3):
    """Draw a straight line between image points in 0-1 coordinates (y up)."""
    import numpy as np
    height, width = pixels.shape[:2]
    steps = int(max(abs(x1 - x0) * width, abs(y1 - y0) * height)) + 1
    for t in np.linspace(0, 1, steps):
        x, y = int((x0 + (x1 - x0) * t) * width), int((y0 + (y1 - y0) * t) * height)
        if not (0 <= x < width and 0 <= y < height):
            continue
        pixels[max(0, y - thickness // 2):min(height, y + thickness // 2 + 1),
               max(0, x - thickness // 2):min(width, x + thickness // 2 + 1)] = color


def _floor_material(name, grid):
    """Neutral grey floor for reference frames; grid adds light lines every GRID_SPACING metres."""
    import bpy
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new('ShaderNodeOutputMaterial')
    diffuse = nodes.new('ShaderNodeBsdfDiffuse')
    diffuse.inputs['Color'].default_value = (REFERENCE_GREY, REFERENCE_GREY, REFERENCE_GREY, 1)
    if not grid:
        links.new(diffuse.outputs[0], out.inputs['Surface'])
        return mat
    coords = nodes.new('ShaderNodeNewGeometry')
    split = nodes.new('ShaderNodeSeparateXYZ')
    links.new(coords.outputs['Position'], split.inputs[0])
    on_line = None
    for axis in ('X', 'Y'):
        wrap = nodes.new('ShaderNodeMath')
        wrap.operation = 'PINGPONG'
        links.new(split.outputs[axis], wrap.inputs[0])
        wrap.inputs[1].default_value = GRID_SPACING / 2
        near = nodes.new('ShaderNodeMath')
        near.operation = 'LESS_THAN'
        links.new(wrap.outputs[0], near.inputs[0])
        near.inputs[1].default_value = GRID_LINE
        if on_line is None:
            on_line = near.outputs[0]
        else:
            both = nodes.new('ShaderNodeMath')
            both.operation = 'MAXIMUM'
            links.new(on_line, both.inputs[0])
            links.new(near.outputs[0], both.inputs[1])
            on_line = both.outputs[0]
    glow = nodes.new('ShaderNodeEmission')
    glow.inputs['Color'].default_value = (0.9, 0.95, 1.0, 1)
    glow.inputs['Strength'].default_value = 1.5
    mix = nodes.new('ShaderNodeMixShader')
    links.new(on_line, mix.inputs['Fac'])
    links.new(diffuse.outputs[0], mix.inputs[1])
    links.new(glow.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs['Surface'])
    return mat


def reference_frames(scene, path, folder: Path, shots=None, samples=REFERENCE_SAMPLES) -> dict:
    """Per shot, at its first frame: <name>_reference.png (opaque, grey floor and background), <name>_guide.png
    (floor grid, horizon, safe areas, note space), <name>_mask.png (white where the piano and notes go) and
    cameras.json. setup_layers() must have run. Returns the cameras.json data."""
    import bpy
    import numpy as np
    from guitar_video_app.instruments.piano.camera import SAFE_BOX
    from guitar_video_app.integrations import piano_visual as pv

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    render = scene.render
    fps = render.fps / render.fps_base
    floor = bpy.data.objects[f'{pv.PREFIX}_Floor']
    floor_material = floor.data.materials[0]
    world = scene.world
    background = next((n for n in world.node_tree.nodes if n.type == 'BACKGROUND'), None) if world.node_tree else None
    saved = dict(samples=scene.eevee.taa_render_samples, filepath=render.filepath, scale=tuple(floor.scale),
                 depth=render.image_settings.color_depth, color=tuple(background.inputs['Color'].default_value)
                 if background else None)
    plain, grid = _floor_material('PV_Reference_Floor', False), _floor_material('PV_Reference_Grid', True)
    scene.eevee.taa_render_samples = samples
    floor.scale = (saved['scale'][0] * REFERENCE_FLOOR_SCALE, saved['scale'][1] * REFERENCE_FLOOR_SCALE,
                   saved['scale'][2])
    render.image_settings.file_format = 'PNG'
    render.image_settings.color_mode = 'RGBA'
    render.image_settings.color_depth = '8'
    if background:
        background.inputs['Color'].default_value = (REFERENCE_GREY, REFERENCE_GREY, REFERENCE_GREY, 1)
    cameras = []
    spans = shot_frames(scene, path)
    try:
        for index, first, last in spans:
            shot = shots[index] if shots and index < len(shots) else None
            bar = shot['start_bar'] if shot else 1
            name = f'shot_{index + 1:02d}_bar_{bar:03d}'
            scene.frame_set(first)
            camera = scene.camera
            files = {}
            for kind, layer, material in (('reference', 'reference', plain), ('guide', 'reference', grid),
                                          ('alpha', 'instrument', None)):
                use_layer(scene, layer)
                floor.data.materials[0] = material or floor_material
                render.film_transparent = kind == 'alpha'
                render.filepath = str((folder / f'{name}_{kind}.png').resolve())
                bpy.ops.render.render(write_still=True)
                files[kind] = Path(render.filepath)
            floor.data.materials[0] = floor_material
            level = horizon(scene, camera)
            space = _hull(note_space(scene, camera))
            image, alpha = _pixels(files.pop('alpha'))
            height, width = alpha.shape[:2]
            reserved = (alpha[..., 3] > 0.02) | (_inside_hull(space, width, height) if len(space) >= 3 else False)
            mask = np.ones_like(alpha)
            mask[..., :3] = reserved[..., None].astype(np.float32)
            files['mask'] = folder / f'{name}_mask.png'
            _save(image, mask, files['mask'])
            bpy.data.images.remove(image)
            (folder / f'{name}_alpha.png').unlink(missing_ok=True)
            image, guide = _pixels(files['guide'])
            box = SAFE_BOX
            safe = (1.0, 0.85, 0.2, 1.0)
            for a, b in (((box['left'], box['bottom']), (box['right'], box['bottom'])),
                         ((box['right'], box['bottom']), (box['right'], box['top'])),
                         ((box['right'], box['top']), (box['left'], box['top'])),
                         ((box['left'], box['top']), (box['left'], box['bottom']))):
                _line(guide, *a, *b, safe)
            for a, b in zip(space, space[1:] + space[:1]) if len(space) >= 3 else ():
                _line(guide, *a, *b, (0.3, 0.8, 1.0, 1.0))
            if level is not None and 0 <= level <= 1:
                _line(guide, 0, level, 1, level, (1.0, 0.25, 0.25, 1.0), thickness=4)
            _save(image, guide, files['guide'])
            bpy.data.images.remove(image)
            data = camera.data
            vertical = 2 * math.atan(data.sensor_width / 2 / data.lens)      # the 36 mm sensor fits the height
            cameras.append(dict(
                shot=index + 1, start_bar=bar, camera=shot['camera'] if shot else 'wide',
                frame_start=first, frame_end=last, seconds_start=first / fps, seconds_end=(last + 1) / fps,
                lens_mm=data.lens, sensor_mm=data.sensor_width, sensor_fit=data.sensor_fit,
                shift_x=data.shift_x, shift_y=data.shift_y, fov_vertical_degrees=math.degrees(vertical),
                location=list(camera.matrix_world.translation),
                rotation_euler_degrees=[math.degrees(a) for a in camera.matrix_world.to_euler()],
                rotation_quaternion=list(camera.matrix_world.to_quaternion()),
                horizon_from_bottom=level, floor_z=0.0, note_space=space,
                files={k: v.name for k, v in files.items()}))
    finally:
        floor.data.materials[0] = floor_material
        floor.scale = saved['scale']
        for mat in (plain, grid):
            bpy.data.materials.remove(mat)
        scene.eevee.taa_render_samples = saved['samples']
        render.filepath = saved['filepath']
        render.image_settings.color_depth = saved['depth']
        if background:
            background.inputs['Color'].default_value = saved['color']
    result = dict(version=1, fps=fps, resolution=[render.resolution_x * render.resolution_percentage // 100,
                                                  render.resolution_y * render.resolution_percentage // 100],
                  safe_box=SAFE_BOX, shots=cameras)
    (folder / 'cameras.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
