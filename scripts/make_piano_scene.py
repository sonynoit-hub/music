"""Build the 9:16 piano scene from nothing: 88 real-size keys, case, background and camera.

Blender -b --factory-startup --python scripts/make_piano_scene.py -- --out outputs/piano-vertical.blend
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from guitar_video_app.integrations.piano_scene import build_scene

parser = argparse.ArgumentParser()
parser.add_argument('--out', type=Path, default=ROOT / 'outputs/piano-vertical.blend')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])

scene = build_scene()
scene.view_settings.view_transform = 'Standard'
scene.view_settings.exposure = 0.4
scene.frame_start, scene.frame_end = 0, 240
scene.render.fps = 30
args.out.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.out.resolve()))
print(f'Saved {args.out}')
