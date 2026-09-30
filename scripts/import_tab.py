"""Fit a tab file to a recording and make it the lesson.

Dashboard song (uses its audio, transcribing it first if needed; a song that already has a
lesson is reviewed with the tab instead, see instruments/guitar/tab.py):
    .venv/bin/python scripts/import_tab.py TAB.json --song SONG_ID
Standalone (writes a version 3 lesson):
    .venv/bin/python scripts/import_tab.py TAB.json --onsets AUDIO_basic_pitch.onsets.json --out lesson.json

The tab file format is described in docs/JSON_SCHEMA.md (Tab file).
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('tab', type=Path)
parser.add_argument('--song', help='dashboard song id')
parser.add_argument('--onsets', type=Path, help='Basic Pitch .onsets.json of the recording')
parser.add_argument('--out', type=Path, help='lesson JSON to write (with --onsets)')
args = parser.parse_args()
if bool(args.song) == bool(args.onsets and args.out):
    parser.error('give either --song, or --onsets with --out')

if args.song:
    from fastapi import HTTPException
    from guitar_video_app.api.dashboard import import_tab
    try:
        result = import_tab(args.song, args.tab.read_bytes(), args.tab.name)
    except HTTPException as exc:
        sys.exit(exc.detail)
    fit = result.get('tab_fit') or {k: v for k, v in result['tab_review'].items() if k not in ('changes', 'removed_notes')}
else:
    import tempfile
    from guitar_video_app.instruments.guitar.tab import import_tab_to_audio, read_tab
    from guitar_video_app.music.alignment import fit_part, played_notes
    from guitar_video_app.music.transcription_cleanup import clean_transcribed_midi
    onsets = json.loads(args.onsets.read_text(encoding='utf-8'))
    tab = read_tab(json.loads(args.tab.read_text(encoding='utf-8')))
    raw = args.onsets.with_name(args.onsets.name.replace('.onsets.json', '.mid'))
    if raw.exists():
        with tempfile.TemporaryDirectory() as scratch:
            clean_transcribed_midi(raw, Path(scratch) / 'clean.mid')
            played = played_notes(Path(scratch) / 'clean.mid')
        lesson, fit = import_tab_to_audio(tab, onsets, played)
    else:
        print(f'{raw} not found: the tab is fitted but not adapted to what is played')
        music, fit = fit_part(tab['music'], onsets)
        lesson = dict({k: v for k, v in tab.items() if k not in ('title', 'artist')}, music=music)
    args.out.write_text(json.dumps(lesson, indent=2) + '\n', encoding='utf-8')
    print(f'wrote {args.out}; dashboard audio offset {-fit["audio_start"]}')
print(json.dumps(fit))
