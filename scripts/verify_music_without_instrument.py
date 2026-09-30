"""The music layer works with no instrument: MIDI analysis, V3 lesson, retiming, tidying, fitting a
reference to onsets, merging, and MIDI export, all with pitch-only rules.

.venv/bin/python scripts/verify_music_without_instrument.py
"""
import ast
import copy
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mido

from guitar_video_app.instruments import check_lesson, lesson_rules
from guitar_video_app.music.alignment import fit_part
from guitar_video_app.music.analyzer import analyze_midi_file
from guitar_video_app.music.midi_export import music_midi
from guitar_video_app.music.normalized import normalized_to_lesson
from guitar_video_app.music.retime import choose_grid, fit_tempo_map, retime_lesson, tidy_lesson
from guitar_video_app.music.review import merge_reference, review_report
from guitar_video_app.music.rules import PitchRules
from guitar_video_app.music.tempo import beat, seconds_at, tempo_map


def music_imports_no_instrument():
    for path in (ROOT / 'guitar_video_app/music').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [node.module or ''] if isinstance(node, ast.ImportFrom) else \
                [a.name for a in node.names] if isinstance(node, ast.Import) else []
            assert not any('instruments' in name or 'guitar_video_app.core' in name for name in names), (path.name, names)


def main():
    music_imports_no_instrument()

    song = analyze_midi_file(ROOT / 'outputs/complex_32_measures.mid')
    assert all(note.string is None and note.fret is None for note in song.notes)
    lesson = normalized_to_lesson(asdict(song), name='No instrument')
    assert lesson['version'] == 3 and lesson['parts'] == {}
    assert isinstance(lesson_rules(lesson), PitchRules) and type(lesson_rules(lesson)) is PitchRules
    played = check_lesson(lesson)
    assert len(played['notes']) == len(song.notes) == 206

    music = lesson['music']
    reference = copy.deepcopy(music)
    tempos = tempo_map(music)
    starts = sorted(float(seconds_at(tempos, beat(n['start_beat']))) for n in music['notes'])
    retime_lesson(music, 90, starts[0])
    fit_tempo_map(music, choose_grid(music))
    stats = tidy_lesson(music, rules=lesson_rules(lesson))
    assert stats['removed'] == 0
    check_lesson(lesson)

    midi = mido.MidiFile(file=BytesIO(_bytes(music_midi(music, lesson['fps']))))
    assert sum(1 for m in midi.tracks[1] if m.type == 'note_on' and m.velocity) == 206

    # The recording is the reference itself, 2.5 s in: the fit finds that offset and tempo.
    audio_start = 2.5
    onsets = [(audio_start + float(seconds_at(tempo_map(reference), beat(n['start_beat']))), n['pitch'], 1.0)
              for n in reference['notes']]
    played_notes = [(t, t + 0.3, p) for t, p, _ in onsets]
    fitted, fit = fit_part(dict(reference, end_beat='32'), onsets)
    assert abs(fit['audio_start'] - audio_start) < 0.01 and fit['matched'] == fit['notes'], fit
    assert abs(fit['tempo_bpm'] - 90) < 0.5, fit

    part = dict(reference, notes=[n for n in reference['notes'] if beat(n['start_beat']) < 32], end_beat='32')
    merged, zero, context = merge_reference(reference, -audio_start, part, onsets, played_notes)
    report = review_report(context, merged, zero)
    assert abs(zero - audio_start) < 0.02, zero
    assert report['places'] and report['moved'] == 0 and report['fingering'] == 0, report
    assert report['notes_after'] >= report['notes_before'] - 2, report
    print(f"PASS: music without an instrument: 206 notes analyzed, retimed, tidied and exported; "
          f"reference fitted at {fit['audio_start']} s, {fit['tempo_bpm']} BPM; review kept {report['kept']} "
          f"of {report['notes_before']} notes over {len(report['places'])} places.")


def _bytes(midi):
    buffer = BytesIO()
    midi.save(file=buffer)
    return buffer.getvalue()


if __name__ == '__main__':
    main()
