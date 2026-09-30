"""Build the PIANO_VISUAL presentation file: the 88-key stage piano, a floor, three lights and a 3/4 camera.

Blender -b --factory-startup --python scripts/make_piano_visual_scene.py -- --out outputs/piano-visual.blend

To add only the piano to another open scene, run in Blender:
    from guitar_video_app.integrations.piano_visual import build_piano_visual; build_piano_visual()
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from guitar_video_app.integrations.piano_visual import build_piano_visual, build_presentation

parser = argparse.ArgumentParser()
parser.add_argument('--out', type=Path, default=ROOT / 'outputs/piano-visual.blend')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])

scene = bpy.context.scene
for obj in [o for o in scene.objects if o.name in ('Cube', 'Light', 'Camera')]:
    bpy.data.objects.remove(obj, do_unlink=True)
build_piano_visual(scene)
build_presentation(scene)
scene.render.resolution_x, scene.render.resolution_y = 1080, 1920
scene.render.resolution_percentage = 100
scene.render.fps = 60
scene.frame_start, scene.frame_end = 0, 0
try:
    scene.render.engine = 'BLENDER_EEVEE'
except TypeError:
    scene.render.engine = 'BLENDER_EEVEE_NEXT'
scene.eevee.taa_render_samples = 64
if hasattr(scene.eevee, 'use_raytracing'):
    scene.eevee.use_raytracing = True
scene.view_settings.view_transform = 'AgX'
scene.view_settings.exposure = 0
args.out.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.out.resolve()))
print(f'Saved {args.out}')
