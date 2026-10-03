"""Run every verify script and print one line per check; exits 1 when any fails.

.venv/bin/python scripts/verify_all.py [--only NAME ...]

Blender checks run in background Blender (BLENDER, default /Applications/Blender.app) on the scene they test; none
writes a scene you work in (verify_lesson_v2.py regenerates its samples outputs/lesson-v2-tests.blend and
outputs/lesson-v2-chords.png). Not run here: verify_dashboard.cjs (needs Playwright and a running dashboard with Blender) and
verify_piano.py --render-files (needs rendered stills).
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BLENDER = os.environ.get('BLENDER', '/Applications/Blender.app/Contents/MacOS/Blender')

# (script, how to run it): None is plain Python; 'factory' is Blender with factory settings and no file; otherwise
# the .blend Blender opens.
CHECKS = [
    ('verify_music_without_instrument.py', None),
    ('verify_normalized_song.py', None),
    ('verify_normalized_to_v2.py', None),
    ('verify_lesson_audio.py', None),
    ('verify_dashboard_midi_import.py', None),
    ('verify_dashboard_normalized_import.py', None),
    ('verify_dashboard_generate_midi_unavailable.py', None),
    ('verify_piano.py', None),
    ('verify_piano_performance.py', None),
    ('verify_piano_camera.py', None),
    ('verify_dashboard_piano_visual.py', None),
    ('verify_bass.py', None),
    ('verify_dashboard_bass.py', None),
    ('verify_time_signature.py', None),
    ('verify_lesson_v2.py', 'outputs/reference-guitar.blend'),
    ('verify_saved_lesson.py', 'outputs/reference-guitar.blend'),
    ('verify_dashboard_reload.py', 'factory'),
    ('verify_bass_scene.py', 'outputs/bass-vertical.blend'),
    ('verify_piano_visual.py', 'outputs/piano-visual.blend'),
    ('verify_piano_visual_notes.py', 'outputs/piano-visual.blend'),
    ('verify_piano_visual_particles.py', 'outputs/piano-visual.blend'),
    ('verify_piano_visual_camera.py', 'outputs/piano-visual.blend'),
    ('verify_piano_visual_layers.py', 'outputs/piano-visual.blend'),
]


def command(script, scene):
    path = str(ROOT / 'scripts' / script)
    if scene is None:
        return [sys.executable, path]
    opening = ['--factory-startup'] if scene == 'factory' else [str(ROOT / scene)]
    return [BLENDER, '-b', *opening, '--python-exit-code', '1', '--python', path]


def summary(output):
    """The PASS line, or the last error line."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    passed = [line for line in lines if line.startswith('PASS') or line.startswith('BLENDER PASS')]
    if passed:
        return passed[-1]
    errors = [line for line in lines if 'Error' in line and '_RestrictData' not in line]
    return (errors or lines or ['no output'])[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only', nargs='+', help='Run only checks whose name contains one of these.')
    args = parser.parse_args()
    checks = [c for c in CHECKS if not args.only or any(o in c[0] for o in args.only)]
    failed = []
    for script, scene in checks:
        start = time.time()
        result = subprocess.run(command(script, scene), cwd=ROOT, capture_output=True, text=True)
        ok = result.returncode == 0
        if not ok:
            failed.append(script)
        print(f"{'ok  ' if ok else 'FAIL'} {script:<48} {time.time() - start:5.1f} s  "
              f"{summary(result.stdout + result.stderr)[:110]}", flush=True)
    print(f'\n{len(checks) - len(failed)} of {len(checks)} checks passed' + (f'; failed: {", ".join(failed)}' if failed else ''))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
