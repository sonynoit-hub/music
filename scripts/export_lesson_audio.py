"""Export a guitar or bass lesson to MIDI and optionally macOS sampled audio (one sampler per string)."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from guitar_video_app.core.lesson_midi import export_lesson

parser=argparse.ArgumentParser()
parser.add_argument('json',type=Path)
parser.add_argument('midi',type=Path)
parser.add_argument('--wav',type=Path)
args=parser.parse_args()
manifest=export_lesson(args.json,args.midi)
print('MIDI:',args.midi,flush=True)
if args.wav:
    subprocess.run(['xcrun','swift',str(ROOT/'scripts/render_guitar_audio.swift'),
                    str(manifest.resolve()),str(args.wav.resolve())],check=True)
