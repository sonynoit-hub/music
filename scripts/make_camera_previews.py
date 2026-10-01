"""Render one vertical still per PIANO_VISUAL camera preset: the dashboard's shot thumbnails, and a contact sheet.

Blender -b outputs/piano-visual.blend --python scripts/make_camera_previews.py -- --json piano_view.json --seconds 4.6
    [--out guitar_video_app/ui/cameras] [--sheet sheet.png] [--scale 20]

Each preset is shown with a drift shot starting on the bar that holds --seconds. --sheet also writes the stills side
by side with the short-video overlay zones (captions, buttons, top edge) tinted red. The .blend is not saved.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
import numpy as np
from guitar_video_app.instruments.piano.camera import CAMERAS, SAFE_BOX, bar_count, bar_seconds
from guitar_video_app.instruments.piano.view import prepare
from guitar_video_app.integrations import piano_visual_camera as shot_camera
from guitar_video_app.integrations.piano_visual_particles import install

GAP = 12
TINT = np.array([0.9, 0.1, 0.1])

parser = argparse.ArgumentParser()
parser.add_argument('--json', type=Path, required=True, help='A version 1 piano view.')
parser.add_argument('--seconds', type=float, required=True, help='A busy moment to show.')
parser.add_argument('--out', type=Path, default=ROOT / 'guitar_video_app/ui/cameras')
parser.add_argument('--sheet', type=Path, help='Also write a contact sheet with the safe zones here.')
parser.add_argument('--scale', type=int, default=20, help='Resolution percentage.')
parser.add_argument('--samples', type=int, default=16)
parser.add_argument('--fps', type=int, default=30)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])

scene = bpy.context.scene
data = json.loads(args.json.read_text())
data['fps'] = args.fps
lesson = prepare(data)
install(data)
bar = max(b for b in range(1, bar_count(lesson) + 1) if bar_seconds(lesson, b) <= args.seconds)
render = scene.render
render.resolution_percentage = args.scale
render.image_settings.file_format = 'PNG'
render.image_settings.color_mode = 'RGBA'
scene.eevee.taa_render_samples = args.samples
args.out.mkdir(parents=True, exist_ok=True)

stills = []
for camera in CAMERAS:
    shots = [dict(start_bar=bar, camera=camera, move='drift' if camera != 'wide' else 'static')]
    if bar > 1:
        shots.insert(0, dict(start_bar=1, camera='wide' if camera != 'wide' else 'hero'))
    shot_camera.install(data, dict(version=1, shots=shots))
    scene.frame_set(round(args.seconds * args.fps))
    render.filepath = str((args.out / f'{camera}.png').resolve())
    bpy.ops.render.render(write_still=True)
    print(f'Preview written: {render.filepath}', flush=True)
    stills.append(render.filepath)
shot_camera.uninstall()

if args.sheet:
    tiles = []
    for path in stills:
        image = bpy.data.images.load(path)
        width, height = image.size
        pixels = np.array(image.pixels[:], dtype=np.float32).reshape(height, width, 4)
        bpy.data.images.remove(image)
        rows, cols = np.arange(height)[:, None] / height, np.arange(width)[None, :] / width
        unsafe = (rows < SAFE_BOX['bottom']) | (rows > SAFE_BOX['top']) | (cols > SAFE_BOX['right'])
        unsafe = np.broadcast_to(unsafe, (height, width))
        pixels[unsafe, :3] = pixels[unsafe, :3] * 0.55 + TINT * 0.45
        pixels[..., 3] = 1
        tiles.append(pixels)
    height, width = tiles[0].shape[:2]
    sheet = np.ones((height, len(tiles) * width + (len(tiles) - 1) * GAP, 4), dtype=np.float32)
    for i, tile in enumerate(tiles):
        sheet[:, i * (width + GAP):i * (width + GAP) + width] = tile
    image = bpy.data.images.new('PV_Camera_Sheet', sheet.shape[1], sheet.shape[0], alpha=True)
    image.pixels[:] = sheet.ravel()
    image.filepath_raw = str(args.sheet.resolve())
    image.file_format = 'PNG'
    image.save()
    print(f'Sheet written: {args.sheet} ({", ".join(CAMERAS)})', flush=True)
