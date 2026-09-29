"""Run with Blender --python scripts/install_saved_lesson.py -- [options]."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import bpy
    from guitar_video_app.integrations.lesson_setup import install_lesson

    parser = argparse.ArgumentParser(description='Install the external lesson controller in the open guitar scene.')
    parser.add_argument('--chart', type=Path, default=ROOT / 'data/demo_16_note_lesson.json')
    parser.add_argument('--save', action='store_true', help='Save changes to the currently open blend file.')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    print(install_lesson(args.chart))
    if args.save:
        if not bpy.data.filepath:
            raise ValueError('Open a saved guitar scene before using --save.')
        versions = bpy.context.preferences.filepaths.save_version
        try:
            bpy.context.preferences.filepaths.save_version = 0
            bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
        finally:
            bpy.context.preferences.filepaths.save_version = versions


if __name__ == '__main__':
    main()
