"""Render a piano view on PIANO_VISUAL with rising musical notes (or glowing plumes), without the Blender UI.

Blender -b outputs/piano-visual.blend --python scripts/render_piano_visual.py -- --json piano_view.json [--wav AUDIO.wav]
    [--camera camera_shots.json] [options]

The .blend is not saved. By default this writes an H.264 MP4 preview with the WAV. Other outputs, into --out as a
folder:
  --stills 4.5,8         PNG stills at those seconds.
  --layers [NAMES]       transparent 16-bit RGBA PNG sequences per compositing layer (instrument, notes, shadow, fx;
                         all that the effect fills when no names are given) plus composite.json, for compositing over
                         a background made elsewhere. Every shot is held static (camera.locked).
  --reference-frames     per shot: an opaque reference, a guide (floor grid, horizon, safe areas, note space), a
                         mask and cameras.json, for making a matching background. Shots are held static too.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from guitar_video_app.instruments.piano.camera import locked
from guitar_video_app.integrations import compositing
from guitar_video_app.integrations import piano_visual_camera as shot_camera
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
outputs = parser.add_mutually_exclusive_group()
outputs.add_argument('--stills', help='Comma-separated seconds to render as PNG stills into --out.')
outputs.add_argument('--layers', nargs='*', choices=compositing.LAYERS,
                     help='Compositing layers to render as RGBA PNG sequences into --out; none named means all.')
outputs.add_argument('--reference-frames', action='store_true',
                     help='One reference, guide and mask per shot plus cameras.json into --out.')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
compositing_run = args.layers is not None or args.reference_frames

scene = bpy.context.scene
data = json.loads(args.json.read_text())
data['fps'] = args.fps
shots = json.loads(args.camera.read_text()) if args.camera else None
if shots and compositing_run:
    shots = locked(shots)
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


def report_frame(scene, *_):
    print(f'Frame written: {scene.frame_current}', flush=True)


if args.reference_frames:
    compositing.setup_layers(scene, args.effect)
    try:
        cameras = compositing.reference_frames(scene, shot_camera._path if shots else None, args.out,
                                               shots['shots'] if shots else None)
    finally:
        compositing.teardown(scene)
    for shot in cameras['shots']:
        print(f"Reference written: shot {shot['shot']} (bar {shot['start_bar']}, {shot['camera']})", flush=True)
    sys.exit(0)

if args.layers is not None:
    args.out.mkdir(parents=True, exist_ok=True)
    available = compositing.setup_layers(scene, args.effect)
    names = [n for n in (args.layers or available) if n in available]
    first, last = scene.frame_start, scene.frame_end
    pattern = '{0}/{0}_####.png'
    manifest = dict(
        version=1, fps=args.fps, resolution=[render.resolution_x * args.scale // 100,
                                             render.resolution_y * args.scale // 100],
        frame_start=first, frame_end=last, effect=args.effect, colors=args.colors,
        layers=[dict(name=n, pattern=pattern.format(n), engine='CYCLES' if n == 'shadow' else render.engine)
                for n in names],
        stack_bottom_to_top=['background'] + [n for n in ('shadow', 'instrument', 'fx', 'notes') if n in names],
        color=dict(view_transform=scene.view_settings.view_transform, png_alpha='straight', depth=16),
        audio=dict(wav=str(args.wav.resolve()) if args.wav else None, offset_seconds=args.offset,
                   start_frame=round(args.offset * args.fps)),
        shots=[dict(shot=i + 1, start_bar=shots['shots'][i]['start_bar'] if shots else 1,
                    camera=shots['shots'][i]['camera'] if shots else 'wide', frame_start=a, frame_end=b)
               for i, a, b in compositing.shot_frames(scene, shot_camera._path if shots else None)])
    (args.out / 'composite.json').write_text(json.dumps(manifest, indent=2) + '\n')
    bpy.app.handlers.render_write.append(report_frame)
    print(f'Frame range: {first}-{last}', flush=True)
    try:
        for number, name in enumerate(names, 1):
            compositing.use_layer(scene, name)
            compositing.configure_rgba_sequence(scene, args.out / name / f'{name}_', args.fps, scale=args.scale)
            print(f'Layer {number}/{len(names)}: {name}', flush=True)
            scene.frame_set(first)
            bpy.ops.render.render(animation=True)
    finally:
        compositing.teardown(scene)
    print(f'Rendered layers {", ".join(names)}, frames {first}-{last}, to {args.out}')
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

bpy.app.handlers.render_write.append(report_frame)
print(f'Frame range: {scene.frame_start}-{scene.frame_end}', flush=True)
scene.frame_set(scene.frame_start)
bpy.ops.render.render(animation=True)
print(f'Rendered frames {scene.frame_start}-{scene.frame_end} to {render.filepath}')
