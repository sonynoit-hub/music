"""Render a dashboard lesson from the terminal, without the Blender UI.

Blender -b outputs/v4-vertical.blend --python scripts/render_lesson.py -- --json LESSON.json --wav AUDIO.wav [options]
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from guitar_video_app.integrations.lesson_setup import install_v2
from guitar_video_app.integrations.title_overlay import install_title

parser = argparse.ArgumentParser()
parser.add_argument('--json', type=Path, required=True)
parser.add_argument('--wav', type=Path, required=True)
parser.add_argument('--offset', type=float, default=0.0, help='Audio offset in seconds, same as the dashboard.')
parser.add_argument('--out', type=Path, default=ROOT / 'outputs/lesson.mp4')
parser.add_argument('--title', default='', help='Song title above the guitar; empty hides it.')
parser.add_argument('--subtitle', default='', help='Artist or songwriter line under the title; empty hides it.')
parser.add_argument('--start', type=int, help='First frame; defaults to the lesson start.')
parser.add_argument('--end', type=int, help='Last frame; defaults to the lesson end.')
parser.add_argument('--scale', type=int, default=100, help='Resolution percentage.')
parser.add_argument('--fps', type=int, default=30, help='Lesson frame rate; timing is in beats, so frames follow this.')
parser.add_argument('--exposure', type=float, default=0.8, help='Color management exposure; the scene file uses -0.6.')
parser.add_argument('--engine', choices=['workbench', 'eevee', 'cycles'], default='workbench',
                    help='Lesson colors, tab numbers and markers use viewport display colors, so only workbench shows them.')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])

scene = bpy.context.scene
data = json.loads(args.json.read_text())
data['fps'] = args.fps
install_v2(data)
install_title(args.title, args.subtitle)

editor = scene.sequence_editor_create()
for strip in [s for s in editor.strips if s.type == 'SOUND']:
    editor.strips.remove(strip)
channel = max((s.channel for s in editor.strips), default=0) + 1
editor.strips.new_sound('Lesson_JSON_Guitar_Audio', str(args.wav.resolve()), channel=channel,
                        frame_start=round(args.offset * scene.render.fps))

render = scene.render
if args.engine == 'workbench':
    render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'MATERIAL'
elif args.engine == 'eevee':
    try:
        render.engine = 'BLENDER_EEVEE'
    except TypeError:
        render.engine = 'BLENDER_EEVEE_NEXT'
else:
    render.engine = 'CYCLES'
if hasattr(render.image_settings, 'media_type'):
    render.image_settings.media_type = 'VIDEO'
render.image_settings.file_format = 'FFMPEG'
render.ffmpeg.format = 'MPEG4'
render.ffmpeg.codec = 'H264'
render.ffmpeg.constant_rate_factor = 'HIGH'
render.ffmpeg.audio_codec = 'AAC'
render.ffmpeg.audio_bitrate = 192
render.resolution_percentage = args.scale
scene.view_settings.exposure = args.exposure
render.filepath = str(args.out.resolve())
if args.start is not None:
    scene.frame_start = args.start
if args.end is not None:
    scene.frame_end = args.end

def report_frame(scene, *_):
    print(f'Frame written: {scene.frame_current}', flush=True)


bpy.app.handlers.render_write.append(report_frame)
scene.frame_set(scene.frame_start)
bpy.ops.render.render(animation=True)
print(f'Rendered frames {scene.frame_start}-{scene.frame_end} to {render.filepath}')
