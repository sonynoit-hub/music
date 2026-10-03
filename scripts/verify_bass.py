"""Check the 4-string bass: tuning and range, switching a lesson to bass, muted (x) notes, the four-fret hand box,
the bass-line filter for full mixes, bass tabs and MIDI, and that the guitar still maps the reference lesson as
before.

.venv/bin/python scripts/verify_bass.py
"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

import mido

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REFERENCE_MIDI = ROOT / 'outputs/complex_32_measures.mid'
REFERENCE_VIEW = ROOT / 'outputs/complex_32_measures.v2.json'

# A bass riff over two bars (pitch, start beat, beats): low E to the G string's 5th fret.
RIFF = [(28, 0, 1), (31, 1, 1), (33, 2, 1), (35, 3, 1), (36, 4, 1), (38, 5, 1), (40, 6, 1), (43, 7, 1)]


def write_midi(path, notes, program=33, tempo_bpm=120):
    """notes: (pitch, start beat, beats[, velocity]) on one track."""
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(tempo_bpm), time=0))
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    track.append(mido.Message('program_change', program=program, time=0))
    events = []
    for pitch, start, beats, *velocity in notes:
        events.append((round(start * 480), 1, mido.Message('note_on', note=pitch, velocity=(velocity or [80])[0])))
        events.append((round((start + beats) * 480), 0, mido.Message('note_off', note=pitch, velocity=0)))
    now = 0
    for tick, _, message in sorted(events, key=lambda e: (e[0], e[1])):
        track.append(message.copy(time=tick - now))
        now = tick
    midi.save(path)
    return path


def played(path):
    """(pitch, start seconds, end seconds) of a MIDI file's notes, by start."""
    midi, now, open_notes, notes = mido.MidiFile(path), 0.0, {}, []
    for message in midi:
        now += message.time
        if message.type == 'note_on' and message.velocity:
            open_notes[message.note] = now
        elif message.type in ('note_on', 'note_off') and message.note in open_notes:
            notes.append((message.note, round(open_notes.pop(message.note), 3), round(now, 3)))
    return sorted(notes, key=lambda n: n[1])


def raises(call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except ValueError as exc:
        return str(exc)
    raise AssertionError(f'{call.__name__} accepted {args}')


def spec_checks():
    from guitar_video_app.instruments import get_instrument
    from guitar_video_app.instruments.bass import BASS
    from guitar_video_app.instruments.fretted import BASS_SPEC, GUITAR_SPEC, spec_for_numbering, spec_of
    assert get_instrument('bass') is BASS and BASS.spec is BASS_SPEC
    assert BASS_SPEC.tuning == (43, 38, 33, 28) and BASS_SPEC.strings == 4 and BASS_SPEC.program == 33
    assert GUITAR_SPEC.tuning == (64, 59, 55, 50, 45, 40) and GUITAR_SPEC.program == 24
    assert [BASS.playable(p) for p in (27, 28, 63, 64)] == [False, True, True, False]
    assert [(p.string, p.fret) for p in BASS_SPEC.positions(28)] == [(4, 0)]
    assert [(p.string, p.fret) for p in BASS_SPEC.positions(43)] == [(1, 0), (2, 5), (3, 10), (4, 15)]
    assert BASS_SPEC.positions(27) == [] and BASS_SPEC.positions(64) == []
    assert spec_of({'instrument': 'bass'}) is BASS_SPEC and spec_of({}) is GUITAR_SPEC
    assert spec_for_numbering('1=high G, 4=low E') is BASS_SPEC
    from guitar_video_app.music.audio_transcription import SETTINGS, band_settings
    assert BASS.transcription == dict(low=28, high=63, line='lowest', onset_threshold=0.4, frame_threshold=0.25)
    assert band_settings() == SETTINGS, 'guitar and piano transcribe with the default settings'
    bass = band_settings(28, 63, 0.4, 0.25)
    assert (bass['onset_threshold'], bass['frame_threshold'], bass['minimum_frequency']) == (0.4, 0.25, 40.03), bass


def lesson_checks(scratch):
    """A MIDI bass line becomes a bass lesson; a guitar lesson switches to bass and back; notes the bass cannot
    play are refused; the bass view, tab and MIDI carry four strings."""
    from guitar_video_app.instruments import activate, as_lesson, part_view
    from guitar_video_app.instruments.bass.normalized import lesson_from_normalized as bass_lesson
    from guitar_video_app.instruments.fretted import BASS_SPEC
    from guitar_video_app.instruments.guitar.midi import lesson_midi
    from guitar_video_app.instruments.guitar.normalized import lesson_from_normalized as guitar_lesson
    from guitar_video_app.instruments.guitar.tab import read_tab
    from guitar_video_app.instruments.guitar.view import prepare
    from guitar_video_app.music.analyzer import analyze_midi_file

    def normalized(notes, name):
        song = analyze_midi_file(write_midi(Path(scratch) / f'{name}.mid', notes), title=name)
        return json.loads(json.dumps({key: getattr(song, key) for key in ('schema_version', 'song', 'timing', 'audio')}
                                     | {key: [item.__dict__ for item in getattr(song, key)]
                                        for key in ('tracks', 'notes', 'measures', 'beats')}))

    riff = normalized(RIFF, 'riff')
    lesson = bass_lesson(riff, fps=60, name='riff')
    view = part_view(lesson, 'bass')
    assert list(lesson['parts']) == ['bass'] and view['instrument'] == 'bass', view.keys()
    assert view['tuning'] == [43, 38, 33, 28] and view['string_numbering'] == '1=high G, 4=low E'
    assert [BASS_SPEC.pitch_of(n['string'], n['fret']) for n in view['notes']] == [p for p, _, _ in RIFF]
    assert all(1 <= n['string'] <= 4 for n in view['notes'])
    assert len(prepare(view)['notes']) == len(RIFF)

    high = normalized(RIFF + [(64, 8, 1), (76, 9, 1)], 'high')
    assert 'cannot be played on the bass' in raises(bass_lesson, high)
    assert len(bass_lesson(high, skip_unplayable=True)['music']['notes']) == len(RIFF)

    octave_up = [(p + 12, s, b) for p, s, b in RIFF]  # the guitar's range starts at its low E (MIDI 40)
    both = bass_lesson(normalized(octave_up, 'octave_up'), fps=60, name='octave up')
    activate(both, 'guitar')
    guitar_positions = copy.deepcopy(both['parts']['guitar']['positions'])
    assert activate(both, 'bass') == 0 and list(both['parts']) == ['bass', 'guitar'], 'bass becomes the active part'
    bass_view = part_view(both, 'bass')
    assert [BASS_SPEC.pitch_of(n['string'], n['fret']) for n in bass_view['notes']] == [p for p, _, _ in octave_up]
    assert activate(both, 'guitar') == 0 and both['parts']['guitar']['positions'] == guitar_positions, \
        'switching back finds the guitar strings and frets'
    reference = as_lesson(json.loads(REFERENCE_VIEW.read_text()))
    assert 'cannot be played on the bass' in raises(activate, reference, 'bass')
    assert list(reference['parts']) == ['guitar'], 'a refused switch leaves the lesson alone'

    tab = read_tab(dict(instrument='bass', tempo_bpm=100, notes=[
        dict(string=4, fret=0, start_beat=0, duration_beats=1), dict(string=1, fret=5, start_beat=1, duration_beats=1)]))
    assert list(tab['parts']) == ['bass'] and part_view(tab, 'bass')['instrument'] == 'bass'
    assert sorted(n['pitch'] for n in tab['music']['notes']) == [28, 48]
    raises(read_tab, dict(instrument='bass', tempo_bpm=100, notes=[dict(string=5, fret=0, start_beat=0, duration_beats=1)]))

    midi = lesson_midi(lesson)
    programs = {m.program for t in midi.tracks for m in t if m.type == 'program_change'}
    names = [m.name for t in midi.tracks for m in t if m.type == 'track_name']
    assert programs == {33}, programs
    assert [n for n in names if 'string' in n] == [f'Bass string {s}' for s in range(1, 5)], names


def muted_checks(scratch):
    """A muted (dead) note keeps its string and fret, survives the view round trip and note Undo, and plays as
    a short soft click in the MIDI and the audio manifest; other notes are written as before."""
    from guitar_video_app.instruments import part_view
    from guitar_video_app.instruments.fretted import BASS_SPEC
    from guitar_video_app.instruments.guitar.midi import export_lesson, lesson_midi
    from guitar_video_app.instruments.guitar.view import from_v2, prepare, set_muted, set_notes
    from guitar_video_app.music.midi_export import MUTED_VELOCITY, TICKS_PER_BEAT, VELOCITY
    notes = [dict(id=f'm{i}', string=BASS_SPEC.positions(p)[0].string, fret=BASS_SPEC.positions(p)[0].fret,
                  start_beat=str(s), duration_beats=str(b)) for i, (p, s, b) in enumerate(RIFF)]
    view = dict(version=2, name='muted', tempo_bpm=120, fps=60, time_signature=[4, 4],
                string_numbering=BASS_SPEC.numbering, instrument='bass', tuning=list(BASS_SPEC.tuning),
                end_beat='8', notes=[dict(n, muted=True) if n['id'] == 'm2' else n for n in notes])
    lesson = from_v2(view)
    assert [n.get('muted') for n in lesson['music']['notes']] == [None, None, True] + [None] * 5
    again = part_view(lesson, 'bass')
    assert again['notes'][2] == view['notes'][2] and 'muted' not in again['notes'][0], again['notes'][:3]
    raises(prepare, dict(view, notes=[dict(notes[0], muted=False)]))
    set_notes(lesson, again['notes'], 'bass')
    assert [n.get('muted') for n in lesson['music']['notes']].count(True) == 1, 'note Undo keeps the muted note'
    note = lesson['music']['notes'][3]
    set_muted(note, True)
    set_muted(note, False)
    assert 'muted' not in note

    velocities, lengths = {}, {}  # by pitch; every riff pitch is played once
    for track in lesson_midi(lesson).tracks:
        tick, starts = 0, {}
        for m in track:
            tick += m.time
            if m.type == 'note_on' and m.velocity:
                starts[m.note], velocities[m.note] = tick, m.velocity
            elif m.type in ('note_on', 'note_off') and m.note in starts:
                lengths[m.note] = tick - starts.pop(m.note)
    assert velocities[33] == MUTED_VELOCITY and all(v == VELOCITY for p, v in velocities.items() if p != 33), velocities
    assert lengths[33] == round(0.05 * 2 * TICKS_PER_BEAT), 'a muted note sounds 50 ms (0.1 beat at 120 bpm)'
    assert lengths[28] == TICKS_PER_BEAT

    source = Path(scratch) / 'muted.json'
    source.write_text(json.dumps(view))
    manifest = json.loads(export_lesson(source, Path(scratch) / 'muted.mid').read_text())
    played = {n['id']: n for n in manifest['notes']}
    assert played['m2']['velocity'] == MUTED_VELOCITY
    assert abs(played['m2']['end_seconds'] - played['m2']['start_seconds'] - 0.05) < 1e-9
    assert 'velocity' not in played['m0'] and played['m0']['end_seconds'] - played['m0']['start_seconds'] == 0.5
    muted_tab_checks()


def muted_tab_checks():
    """A tab file may mark dead notes (fret optional); fitting the tab to a recording ignores them and keeps
    them where the tab writes them, since they have no pitch to hear."""
    from guitar_video_app.instruments import part_view
    from guitar_video_app.instruments.fretted import BASS_SPEC
    from guitar_video_app.instruments.guitar.tab import import_tab_to_audio, read_tab
    from guitar_video_app.music.tempo import beat
    pitched = [(p, s) for p, s, _ in RIFF]
    tab = read_tab(dict(instrument='bass', tempo_bpm=120, notes=[
        *(dict(string=BASS_SPEC.positions(p)[0].string, fret=BASS_SPEC.positions(p)[0].fret, start_beat=s,
               duration_beats='1/2') for p, s in pitched),
        dict(string=2, start_beat='5/2', duration_beats='1/4', muted=True)]))
    muted = [n for n in tab['music']['notes'] if n.get('muted')]
    assert len(muted) == 1 and muted[0]['pitch'] == BASS_SPEC.pitch_of(2, 0), muted
    raises(read_tab, dict(instrument='bass', tempo_bpm=120, notes=[dict(string=2, start_beat=0, duration_beats=1)]))
    start = 1.0  # audio second of beat 0; 120 bpm is 0.5 s a beat
    onsets = [[start + s * 0.5, p, 0.8] for p, s in pitched]
    played = [(start + s * 0.5, start + s * 0.5 + 0.25, p) for p, s in pitched]
    lesson, stats = import_tab_to_audio(tab, onsets, played)
    assert stats['matched'] == stats['notes'] == len(pitched), stats
    kept = [n for n in part_view(lesson, 'bass')['notes'] if n.get('muted')]
    assert len(kept) == 1 and beat(kept[0]['start_beat']) == beat('5/2') and kept[0]['string'] == 2, kept


def box_checks():
    """In a chosen position a one-octave scale stays in a four-fret box, one finger per fret; the bass cannot
    finger a five-note chord."""
    from guitar_video_app.instruments.fretted import BASS_SPEC
    from guitar_video_app.instruments.guitar.fingering_solver import plan_positions
    from guitar_video_app.music.schema import RawNote
    major = (0, 2, 4, 5, 7, 9, 11, 12)
    for root, position in ((31, 3), (33, 5), (35, 7)):
        notes = [RawNote(pitch=root + step, start_time=i / 2, end_time=i / 2 + 0.5) for i, step in enumerate(major)]
        frets = [p.fret for p in plan_positions(notes, spec=BASS_SPEC, position=position)]
        fretted = [f for f in frets if f]
        assert max(fretted) - min(fretted) <= BASS_SPEC.hand_frets - 1, (root, position, frets)
        assert all(BASS_SPEC.pitch_of(p.string, p.fret) == n.pitch
                   for p, n in zip(plan_positions(notes, spec=BASS_SPEC, position=position), notes))
    chord = [RawNote(pitch=p, start_time=0, end_time=1) for p in (28, 33, 38, 43, 47)]
    raises(plan_positions, chord, spec=BASS_SPEC)
    assert 'standard bass tuning' in raises(plan_positions, [RawNote(pitch=64, start_time=0, end_time=1)], spec=BASS_SPEC)


def line_checks(scratch):
    """keep_line (via clean_transcribed_midi with the bass's transcription options) keeps the bass line of a
    synthetic full mix: lowest of a chord, harmony above a ringing bass note dropped, a slight legato overlap
    kept, out-of-range and fragment notes dropped, each line note cut where the next starts."""
    from guitar_video_app.instruments.bass import BASS
    from guitar_video_app.music.transcription_cleanup import clean_transcribed_midi
    beat = 0.5  # seconds at 120 bpm
    mix = [
        (36, 0, 2, 90), (60, 0, 2, 70), (64, 0, 2, 70), (67, 0, 2, 70),  # C2 under a C chord
        (31, 0.02, 2, 90),                     # G1 10 ms later: the lowest of the chord
        (43, 2, 1, 90), (48, 2, 1, 80),        # G2 with C3 above at the same time: G2
        (50, 2.4, 0.4, 80),                    # D3 starts while G2 rings: harmony
        (41, 3, 2, 90), (38, 3.6, 1.28, 90),   # F2, then D2 below it: F2 ends where D2 starts
        (45, 4.8, 1, 90),                      # A2 overlaps D2 by 40 ms (legato): kept
        (24, 6, 1, 90), (46, 6.2, 0.1, 90),    # below the low E; a 50 ms fragment
        (70, 7, 1, 90),                        # above the bass's range
    ]
    source = write_midi(Path(scratch) / 'mix.mid', mix, program=0)
    target = Path(scratch) / 'line.mid'
    stats = clean_transcribed_midi(source, target, onsets=Path(scratch) / 'none.json', line=BASS.transcription)
    line = played(target)
    assert [p for p, _, _ in line] == [31, 43, 41, 38, 45], line
    assert line[0][1] == 0.01 and line[0][2] == 2 * beat, 'G1 is cut where G2 starts'
    assert line[2][2] == 3.6 * beat, 'F2 ends where D2 starts'
    assert line[3][2] == 4.8 * beat, 'D2 ends where the legato A2 starts'
    assert stats['line_out_of_range'] == 4 and stats['line_kept'] == 5, stats  # E4, G4, C1, A#4
    unfiltered = played(write_midi(Path(scratch) / 'copy.mid', mix, program=0))
    clean_transcribed_midi(source, target, onsets=Path(scratch) / 'none.json')
    assert len(played(target)) == len(unfiltered), 'without line options every note is kept'

    # The bass alone: each attack is played at the pitch struck hardest, so a high note over the ringing open
    # string is kept and a louder octave overtone wins over the weak string below it only when struck harder.
    alone = dict(BASS.transcription, line='attacks')
    riff = [(48, 0, 0.25, 90), (50, 0.25, 0.25, 90), (38, 0.5, 1.5, 90), (50, 1.0, 0.5, 40), (38, 2, 1, 90)]
    source = write_midi(Path(scratch) / 'alone.mid', riff, program=33)
    peaks = [[0.0, 48, 0.9], [0.0, 60, 0.6], [0.125, 50, 0.92], [0.13, 38, 0.45], [0.25, 38, 0.8],
             [0.26, 50, 0.5], [0.5, 50, 0.94], [0.51, 38, 0.6], [0.75, 38, 0.3], [1.0, 38, 0.85], [1.0, 26, 0.9]]
    onsets = Path(scratch) / 'alone.onsets.json'
    onsets.write_text(json.dumps(peaks))
    stats = clean_transcribed_midi(source, target, onsets=onsets, line=alone)
    line = played(target)
    assert [p for p, _, _ in line] == [48, 50, 38, 50, 38], line
    assert [s for _, s, _ in line] == [0, 0.125, 0.25, 0.5, 1.0], 'notes start at their attacks'
    assert line[2][2] == 0.5 and line[4][2] == 1.5, 'a note lasts until the next attack or its transcribed end'
    assert stats['line_weak'] == 1 and stats['line_kept'] == 5, stats
    stats = clean_transcribed_midi(source, target, onsets=Path(scratch) / 'none.json', line=alone)
    assert 'line_attacks' not in stats and stats['line_kept'] >= 1, 'without onset peaks the lowest line is kept'

    # A low string heard loudest at its third harmonic (a twelfth up) is played at the twelfth below when that
    # pitch and its octave together were struck at least as hard; a weak twelfth below does not count.
    from guitar_video_app.music.transcription_cleanup import attack_line
    peaks = [[0.0, 50, 0.78], [0.0, 31, 0.39], [0.0, 43, 0.63],   # D3 loudest over G1 and G2: G1
             [0.5, 55, 0.91], [0.5, 36, 0.38], [0.5, 48, 0.48]]   # G3 loudest, C2 + C3 weaker than G3: G3
    line, stats = attack_line([], peaks, 28, 63, lambda seconds: round(seconds * 960))
    assert [n['pitch'] for n in line] == [31, 55] and stats['line_lowered'] == 1, (line, stats)
    # Attacks 11 ms apart (the second just past the 40 ms chord window) are one note, never a sliver.
    peaks = [[0.07, 45, 0.7], [0.105, 48, 0.75], [0.116, 60, 0.8], [0.4, 50, 0.9]]
    line, _ = attack_line([], peaks, 28, 63, lambda seconds: round(seconds * 960))
    assert [(n['start_s'], n['pitch']) for n in line] == [(0.105, 60), (0.4, 50)], line
    assert min(n['end_s'] - n['start_s'] for n in line) >= 0.06

    # With a pitch track (a separated bass), attacks from min_strength take the tracked pitch over the loudest
    # peak; the twelfth rule is off; an unvoiced or out-of-range stretch keeps the loudest peak's pitch.
    frames = [round(i * 0.01, 2) for i in range(150)]
    pitch = lambda t: 38.2 if t < 0.5 else None if t < 1.0 else 70.0
    track = dict(times=frames, midi=[pitch(t) for t in frames])
    peaks = [[0.0, 50, 0.45], [0.0, 31, 0.39], [0.0, 43, 0.44], [0.25, 50, 0.35],
             [0.5, 45, 0.5], [1.0, 55, 0.6]]
    line, stats = attack_line([], peaks, 28, 63, lambda seconds: round(seconds * 960), 0.4, track)
    assert [(n['start_s'], n['pitch']) for n in line] == [(0.0, 38), (0.5, 45), (1.0, 55)], line
    assert stats['line_tracked'] == 1 and stats['line_lowered'] == 0 and stats['line_weak'] == 1, stats


def timing_checks():
    """A bass line starting with a pickup on beat 3 and popping on 16th offbeats gets its measures
    started on its long low roots, not on its first note."""
    from guitar_video_app.music.retime import root_downbeat, suggest_grid
    period, bar = 0.6, 2.4
    notes = [(0.0, 49, 0.12), (0.15, 51, 0.12), (0.3, 49, 0.25), (0.6, 47, 0.25), (0.9, 46, 0.25)]
    for start in (1.2, 3.6, 6.0, 8.4):
        notes += [(start, 39, 0.45), (start + 0.45, 51, 0.12), (start + 0.75, 49, 0.12), (start + 0.9, 51, 0.25),
                  (start + 1.2, 37, 0.12), (start + 1.35, 49, 0.12), (start + 1.65, 51, 0.12), (start + 1.8, 34, 0.3)]
    tempo, first = suggest_grid([n[0] for n in notes])
    assert abs(tempo - 100) < 0.6, tempo
    downbeat = root_downbeat(notes, tempo, first, 4)
    assert abs((downbeat - 1.2 + bar / 2) % bar - bar / 2) < 0.03, (first, downbeat)
    assert root_downbeat([], tempo, first, 4) == first


def guitar_reference_checks():
    """The guitar maps the 206-note reference MIDI to the same strings and frets as the stored reference view."""
    from guitar_video_app.api.dashboard import analyze_dashboard_midi
    from guitar_video_app.instruments import part_view
    _, lesson, _ = analyze_dashboard_midi(REFERENCE_MIDI, 'reference')
    mapped = [(n['string'], n['fret']) for n in part_view(lesson, 'guitar')['notes']]
    stored = [(n['string'], n['fret']) for n in json.loads(REFERENCE_VIEW.read_text())['notes']]
    assert len(mapped) == 206 and mapped == stored, sum(a != b for a, b in zip(mapped, stored))
    assert 'instrument' not in part_view(lesson, 'guitar'), 'the guitar view has no instrument or tuning key'


def main():
    with tempfile.TemporaryDirectory() as scratch:
        os.environ['GUITAR_DASHBOARD_STORE'] = str(Path(scratch) / 'store')
        spec_checks()
        lesson_checks(scratch)
        muted_checks(scratch)
        box_checks()
        line_checks(scratch)
        timing_checks()
        guitar_reference_checks()
    print('PASS: bass tuning and range, switching to bass, muted notes, four-fret box, bass-line filter, measures '
          'on the roots, bass tab and MIDI; guitar reference unchanged.')


if __name__ == '__main__':
    main()
