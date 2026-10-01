"""Render a piano view on PIANO_VISUAL with rising musical notes (or glowing plumes), without the Blender UI.

Blender -b outputs/piano-visual.blend --python scripts/render_piano_visual.py -- --json piano_view.json [--wav AUDIO.wav]
    [--camera camera_shots.json] [options]

The .blend is not saved. --stills 4.5,8 renders PNGs at those seconds into --out (a folder) instead of a video.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from guitar_video_app.integrations.piano_visual_particles import COLORS, EFFECTS, install

parser = argparse.ArgumentParser()
parser.add_argument('--json', type=Path, required=True, help='A version 1 piano view.')
parser.add_argument('--wav', type=Path, help='Final WAV master; omitted renders a silent video.')
parser.add_argument('--offset', type=float, default=0.0, help='Audio offset in seconds, same as the dashboard.')
parser.add_argument('--out', type=Path, default=ROOT / 'outputs/piano-visual.mp4')
parser.add_argument('--fps', type=int, default=30, help='Frame rate; timing is in beats, so frames follow this.')
parser.add_argument('--start', type=int, help='First frame; defaults to the lesson start.')
parser.add_argument('--end', type=int, help='Last frame; defaults to when the last note has faded.')
parser.add_argument('--effect', choices=EFFECTS, default='notes', help='Rising note symbols, or particle plumes.')
parser.add_argument('--colors', choices=COLORS, default='blue',
                    help='Colour theme; hands colours right-hand notes orange and left-hand notes blue.')
parser.add_argument('--camera', type=Path,
                    help='A version 1 camera shots file (camera_shots.json); omitted keeps the single wide view.')
parser.add_argument('--scale', type=int, default=100, help='Resolution percentage.')
parser.add_argument('--samples', type=int, help='EEVEE samples; defaults to the scene value.')
parser.add_argument('--stills', help='Comma-separated seconds to render as PNG stills into --out.')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])

scene = bpy.context.scene
data = json.loads(args.json.read_text())
data['fps'] = args.fps
shots = json.loads(args.camera.read_text()) if args.camera else None
print(install(data, effect=args.effect, colors=args.colors, camera=shots), flush=True)

editor = scene.sequence_editor_create()
for strip in [s for s in editor.strips if s.type == 'SOUND']:
    editor.strips.remove(strip)
if args.wav:
    channel = max((s.channel for s in editor.strips), default=0) + 1
    editor.strips.new_sound('Lesson_Piano_Audio', str(args.wav.resolve()), channel=channel,
                            frame_start=round(args.offset * scene.render.fps))

render = scene.render
render.resolution_percentage = args.scale
if args.samples:
    scene.eevee.taa_render_samples = args.samples
if args.start is not None:
    scene.frame_start = args.start
if args.end is not None:
    scene.frame_end = args.end

if args.stills:
    args.out.mkdir(parents=True, exist_ok=True)
    render.image_settings.file_format = 'PNG'
    for seconds in (float(s) for s in args.stills.split(',')):
        frame = round(seconds * scene.render.fps)
        scene.frame_set(frame)
        render.filepath = str((args.out / f'piano_visual_{frame:05d}.png').resolve())
        bpy.ops.render.render(write_still=True)
        print(f'Still written: {render.filepath}', flush=True)
    sys.exit(0)

if hasattr(render.image_settings, 'media_type'):
    render.image_settings.media_type = 'VIDEO'
render.image_settings.file_format = 'FFMPEG'
render.ffmpeg.format = 'MPEG4'
render.ffmpeg.codec = 'H264'
render.ffmpeg.constant_rate_factor = 'HIGH'
render.ffmpeg.audio_codec = 'AAC' if args.wav else 'NONE'
render.ffmpeg.audio_bitrate = 192
render.filepath = str(args.out.resolve())


def report_frame(scene, *_):
    print(f'Frame written: {scene.frame_current}', flush=True)


bpy.app.handlers.render_write.append(report_frame)
print(f'Frame range: {scene.frame_start}-{scene.frame_end}', flush=True)
scene.frame_set(scene.frame_start)
bpy.ops.render.render(animation=True)
print(f'Rendered frames {scene.frame_start}-{scene.frame_end} to {render.filepath}')
