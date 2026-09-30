"""Render a dashboard lesson from the terminal, without the Blender UI.

Blender -b outputs/v4-vertical.blend --python scripts/render_lesson.py -- --json LESSON.json --wav AUDIO.wav [options]
Blender -b outputs/piano-vertical.blend --python scripts/render_lesson.py -- --json piano_view.json --wav AUDIO.wav [options]
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from guitar_video_app.instruments import as_lesson
from guitar_video_app.instruments.guitar.view import guitar_view
from guitar_video_app.integrations.lesson_setup import install_v2
from guitar_video_app.integrations.guitar_style import STYLES, install_style
from guitar_video_app.integrations.title_overlay import install_title

parser = argparse.ArgumentParser()
parser.add_argument('--json', type=Path, required=True)
parser.add_argument('--wav', type=Path, required=True)
parser.add_argument('--offset', type=float, default=0.0, help='Audio offset in seconds, same as the dashboard.')
parser.add_argument('--out', type=Path, default=ROOT / 'outputs/lesson.mp4')
parser.add_argument('--title', default='', help='Song title above the guitar; empty hides it.')
parser.add_argument('--subtitle', default='', help='Artist or songwriter line under the title; empty hides it.')
parser.add_argument('--style', choices=tuple(STYLES), default='natural', help='Guitar colors and background.')
parser.add_argument('--start', type=int, help='First frame; defaults to the lesson start.')
parser.add_argument('--end', type=int, help='Last frame; defaults to the lesson end.')
parser.add_argument('--scale', type=int, default=100, help='Resolution percentage.')
parser.add_argument('--fps', type=int, default=30, help='Lesson frame rate; timing is in beats, so frames follow this.')
parser.add_argument('--exposure', type=float,
                    help='Color management exposure; defaults to 0.8 for guitar (the scene file uses -0.6) and the '
                         'scene value for piano.')
parser.add_argument('--engine', choices=['workbench', 'eevee', 'cycles'], default='workbench',
                    help='Lesson colors, tab numbers and markers use viewport display colors, so only workbench shows them.')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])

scene = bpy.context.scene
data = json.loads(args.json.read_text())
piano = data.get('instrument') == 'piano'
if piano:
    from guitar_video_app.integrations.piano_lesson import install_piano
    from guitar_video_app.integrations.piano_scene import KEYBOARD

    data['fps'] = args.fps
    install_piano(data)
    install_title(args.title, args.subtitle, anchor=KEYBOARD)
else:
    if data.get('version') != 2:
        data = guitar_view(as_lesson(data))
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
if args.exposure is not None or not piano:
    scene.view_settings.exposure = 0.8 if args.exposure is None else args.exposure
if not piano:
    install_style(args.style)
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
