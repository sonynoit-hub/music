"""The piano: keyboard geometry, hands from MIDI tracks, the hand planner on the same notes in one
track, retiming, tidying and MIDI export of a piano lesson, and the dashboard flow (switch a song to
piano, import MIDI, flip a hand, plan again, send, download MIDI, switch to guitar and back).

.venv/bin/python scripts/verify_piano.py [--render-files FOLDER]

With --render-files the test piece is also written there as piano_view.json and a sine-tone WAV
for scripts/render_lesson.py.
"""
import argparse
import asyncio
from dataclasses import asdict
from io import BytesIO
import json
import math
import os
from pathlib import Path
import random
import struct
import sys
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mido

from guitar_video_app.instruments import (activate, active_instrument, check_lesson, get_instrument, lesson_rules,
                                          parts)
from guitar_video_app.instruments.piano import PIANO
from guitar_video_app.instruments.piano.keyboard import (HIGH, LOW, WHITE_MM, WIDTH_MM, is_black, key_x_mm,
                                                         white_keys)
from guitar_video_app.instruments.piano.normalized import lesson_from_normalized
from guitar_video_app.instruments.piano.view import piano_view, prepare
from guitar_video_app.music.analyzer import analyze_midi_file
from guitar_video_app.music.midi_export import music_midi
from guitar_video_app.music.retime import choose_grid, fit_tempo_map, retime_lesson, tidy_lesson
from guitar_video_app.music.tempo import beat, seconds_at, tempo_map

BPM = 100
TPB = 480
CHORDS = [(48, 52, 55), (45, 48, 52), (41, 45, 48), (43, 47, 50)]  # C, Am, F, G around C3


def piece(seed=7):
    """16 bars of 4/4 as (hand, pitch, start tick, length ticks). Bars 1-8: Alberti bass under a
    melody; 9-12: bass octaves under right-hand triads down to F3; 13-16: the left hand climbs an
    octave every other bar while the melody drops to just above it, so the hands share the middle."""
    rng = random.Random(seed)
    notes, bar = [], 4 * TPB
    for index in range(16):
        root, third, fifth = CHORDS[index % 4]
        at = index * bar
        if index < 8 or index >= 12:
            lift = 12 if index >= 12 and index % 2 else 0
            bass = [p + lift for p in (root, fifth, third, fifth) * 2]
            for step, pitch in enumerate(bass):
                notes.append(('left', pitch, at + step * TPB // 2, TPB // 2))
            if index < 8:
                tones = [p + 24 for p in (root, third, fifth)] + [p + 36 for p in (root, third)]
            else:
                tones = [p + o for o in (12, 24) for p in (root, third, fifth) if p + o > max(bass) + 2]
            for step in range(4):
                notes.append(('right', rng.choice(tones), at + step * TPB, TPB))
        else:
            notes.append(('left', root - 12, at, 2 * TPB))
            notes.append(('left', root, at, 2 * TPB))
            notes.append(('left', fifth - 12, at + 2 * TPB, 2 * TPB))
            notes.append(('left', fifth, at + 2 * TPB, 2 * TPB))
            for step in range(2):
                for pitch in (root + 12, third + 12, fifth + 12):
                    notes.append(('right', pitch, at + step * 2 * TPB, 2 * TPB))
    assert len({(p, s) for _, p, s, _ in notes}) == len(notes)
    return notes


def write_midi(path, notes, two_tracks=True):
    midi = mido.MidiFile(ticks_per_beat=TPB)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(BPM), time=0))
    meta.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    midi.tracks.append(meta)
    groups = [('Right Hand', 'right'), ('Left Hand', 'left')] if two_tracks else [('Piano', None)]
    for name, hand in groups:
        track = mido.MidiTrack()
        track.append(mido.MetaMessage('track_name', name=name, time=0))
        track.append(mido.Message('program_change', program=0, channel=0, time=0))
        events = []
        for who, pitch, start, length in notes:
            if hand is None or who == hand:
                events += [(start + length, 0, pitch), (start, 1, pitch)]
        now = 0
        for tick, on, pitch in sorted(events):
            track.append(mido.Message('note_on' if on else 'note_off', note=pitch, velocity=80 if on else 0,
                                      channel=0, time=tick - now))
            now = tick
        midi.tracks.append(track)
    midi.save(path)


def write_pedal_midi(path):
    midi = mido.MidiFile(ticks_per_beat=TPB)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(BPM), time=0))
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    track.append(mido.Message('program_change', program=0, channel=0, time=0))
    track.append(mido.Message('control_change', control=64, value=127, channel=0, time=0))
    track.append(mido.Message('note_on', note=60, velocity=80, channel=0, time=0))
    track.append(mido.Message('note_off', note=60, velocity=0, channel=0, time=TPB))
    track.append(mido.Message('control_change', control=64, value=0, channel=0, time=TPB))
    track.append(mido.MetaMessage('end_of_track', time=0))
    midi.save(path)


def normalized(path):
    return json.loads(json.dumps(asdict(analyze_midi_file(path, title=path.stem))))


def truth(lesson, notes):
    """{note id: hand} from the piece, matched by pitch and start."""
    known = {(pitch, start / TPB): hand for hand, pitch, start, _ in notes}
    return {n['id']: known[(n['pitch'], float(beat(n['start_beat'])))] for n in lesson['music']['notes']}


def geometry_checks():
    whites = white_keys()
    assert len(whites) == 52 and HIGH - LOW + 1 - len(whites) == 36
    assert abs(key_x_mm(LOW) - WHITE_MM / 2) < 1e-9 and abs(key_x_mm(HIGH) - (WIDTH_MM - WHITE_MM / 2)) < 1e-9
    assert abs(WIDTH_MM - 1222) < 1e-9
    for pitch in range(LOW + 1, HIGH):
        if is_black(pitch):
            assert key_x_mm(pitch - 1) < key_x_mm(pitch) < key_x_mm(pitch + 1), pitch
    xs = [key_x_mm(p) for p in whites]
    assert all(abs((b - a) - WHITE_MM) < 1e-9 for a, b in zip(xs, xs[1:]))


def sine_wav(path, view, rate=22050):
    tempos = tempo_map(view)
    notes = [(float(seconds_at(tempos, beat(n['start_beat']))),
              float(seconds_at(tempos, beat(n['start_beat']) + beat(n['duration_beats']))), n['pitch'])
             for n in view['notes']]
    total = int((max(end for _, end, _ in notes) + 1) * rate)
    samples = [0.0] * total
    for start, end, pitch in notes:
        freq = 440 * 2 ** ((pitch - 69) / 12)
        first, last = int(start * rate), min(total, int((end + 0.25) * rate))
        for i in range(first, last):
            t = (i - first) / rate
            samples[i] += 0.12 * math.sin(2 * math.pi * freq * t) * math.exp(-3 * t)
    peak = max(1.0, max(abs(s) for s in samples))
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b''.join(struct.pack('<h', int(32000 * s / peak)) for s in samples))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--render-files', type=Path)
    args = parser.parse_args()
    geometry_checks()
    notes = piece()
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        two, one = folder / 'two-hands.mid', folder / 'one-track.mid'
        pedal = folder / 'sustain.mid'
        write_midi(two, notes)
        write_midi(one, notes, two_tracks=False)
        write_pedal_midi(pedal)

        lesson = lesson_from_normalized(normalized(two), name='Two hands')
        part = lesson['parts']['piano']
        expected = truth(lesson, notes)
        assert part['hands_from'] == 'midi_tracks'
        assert all(part['notes'][i] == dict(hand=h, by='midi') for i, h in expected.items())
        assert len(expected) == len(notes)

        merged = lesson_from_normalized(normalized(one), name='One track')
        assert merged['parts']['piano']['hands_from'] == 'planned'
        planned = {i: e['hand'] for i, e in merged['parts']['piano']['notes'].items()}
        known = truth(merged, notes)
        right = sum(planned[i] == h for i, h in known.items())
        accuracy = right / len(known)
        assert accuracy >= 0.9, accuracy

        check_lesson(lesson)
        view = piano_view(lesson, 'piano')
        played = prepare(view)
        assert len(played['notes']) == len(notes)
        assert {n['hand'] for n in view['notes']} == {'left', 'right'}
        pedal_lesson = lesson_from_normalized(normalized(pedal), name='Sustain')
        pedal_view = piano_view(pedal_lesson, 'piano')
        assert pedal_lesson['music']['pedal_events'] == [
            {'id': 'p0001', 'type': 'sustain', 'start_beat': 0, 'duration_beats': 2, 'value': 127,
             'channel': 0, 'track_id': 0}
        ]
        assert pedal_view['pedal_events'] == pedal_lesson['music']['pedal_events']
        if args.render_files:
            args.render_files.mkdir(parents=True, exist_ok=True)
            (args.render_files / 'piano_view.json').write_text(json.dumps(dict(view, fps=30), indent=2))
            sine_wav(args.render_files / 'piano.wav', view)

        music = lesson['music']
        starts = sorted(float(seconds_at(tempo_map(music), beat(n['start_beat']))) for n in music['notes'])
        retime_lesson(music, 92, starts[0])
        fit_tempo_map(music, choose_grid(music))
        stats = tidy_lesson(music, rules=lesson_rules(lesson))
        check_lesson(lesson)
        _, piano_part, instrument = parts(lesson)[0]
        midi = music_midi(music, lesson['fps'], lesson_rules(lesson), instrument.midi_tracks(piano_part, 'Test'),
                          instrument.midi_program)
        counts = [sum(1 for m in t if m.type == 'note_on' and m.velocity) for t in midi.tracks[1:]]
        hands = [sum(1 for e in piano_part['notes'].values() if e['hand'] == h) for h in ('right', 'left')]
        assert counts == hands and sum(counts) == len(music['notes']), (counts, hands)

        low = lesson_from_normalized(normalized(two), name='Too low for guitar')
        try:
            activate(low, 'guitar')
            raise AssertionError('Bass below E2 cannot be played on the guitar.')
        except ValueError:
            assert list(low['parts']) == ['piano']

        # The same piece without the notes beyond the guitar (bass octaves below low E, top melody notes).
        guitar_range = [note for note in notes if get_instrument('guitar').playable(note[1])]
        guitar_midi = folder / 'guitar-range.mid'
        write_midi(guitar_midi, guitar_range)
        switched = lesson_from_normalized(normalized(guitar_midi), name='Switch')
        hands_before = json.loads(json.dumps(switched['parts']['piano']['notes']))
        changed = activate(switched, 'guitar')
        assert active_instrument(switched) == 'guitar' and changed > 0
        activate(switched, 'piano')
        assert switched['parts']['piano']['notes'] == hands_before

        flow = dashboard_flow(guitar_midi)
    print(f'PASS: piano geometry; hands from MIDI tracks for all {len(notes)} notes; planner on one track '
          f'{right}/{len(known)} ({accuracy:.0%}) hands right; retime and tidy (removed {stats["removed"]}); '
          f'MIDI export right/left {counts[0]}/{counts[1]}; dashboard: {flow}.')


def dashboard_flow(midi_path):
    with tempfile.TemporaryDirectory() as store:
        os.environ['GUITAR_DASHBOARD_STORE'] = store
        from fastapi import UploadFile
        from guitar_video_app.api import dashboard
        from guitar_video_app.api.dashboard import (HandInput, InstrumentInput, SongInput, create, lesson, midi,
                                                    plan_song_hands, send, update_hand, update_instrument, upload)

        song_id = create(SongInput(name='Piano test'))['id']
        row = update_instrument(song_id, InstrumentInput(instrument='piano'))
        assert row['changed'] == 0
        row = asyncio.run(upload(song_id, 'midi', UploadFile(BytesIO(midi_path.read_bytes()), filename='hands.mid')))
        assert row['summary']['piano']['hands_from'] == 'midi_tracks', row['summary']
        view = json.loads(lesson(song_id, part='piano').body)
        assert view['instrument'] == 'piano'
        first = view['notes'][0]
        other = 'left' if first['hand'] == 'right' else 'right'
        update_hand(song_id, HandInput(note_id=first['id'], hand=other))
        planned = plan_song_hands(song_id)
        stored = json.loads(lesson(song_id).body)
        assert stored['parts']['piano']['notes'][first['id']] == dict(hand=other, by='user')
        assert planned['summary']['piano']['chosen'] == 1

        wav = Path(store) / 'tone.wav'
        with wave.open(str(wav), 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(8000)
            out.writeframes(b'\0\0' * 8000)
        asyncio.run(upload(song_id, 'wav', UploadFile(BytesIO(wav.read_bytes()), filename='tone.wav')))
        sent = []
        real_bridge = dashboard.bridge
        dashboard.bridge = lambda command, port=8765: sent.append(command) or dict(ok=True)
        try:
            send(song_id)
        finally:
            dashboard.bridge = real_bridge
        command = sent[0]
        assert command['instrument'] == 'piano' and command['json_path'].endswith('piano_view.json')
        prepare(json.loads(Path(command['json_path']).read_text()))

        midi_file = mido.MidiFile(file=BytesIO(midi(song_id).body))
        names = [next((m.name for m in t if m.type == 'track_name'), '') for t in midi_file.tracks]
        assert any(n.endswith('right hand') for n in names) and any(n.endswith('left hand') for n in names), names

        to_guitar = update_instrument(song_id, InstrumentInput(instrument='guitar'))
        assert to_guitar['instrument'] is None and json.loads(lesson(song_id, part='guitar').body)['version'] == 2
        update_instrument(song_id, InstrumentInput(instrument='piano'))
        back = json.loads(lesson(song_id).body)
        assert list(back['parts'])[0] == 'piano'
        assert back['parts']['piano']['notes'][first['id']] == dict(hand=other, by='user')
        return (f"imported {row['summary']['notes']} notes with MIDI-track hands, flip kept through planning, "
                f"sent piano_view.json, 2-hand MIDI, guitar and back ({to_guitar['changed']} notes fingered)")


if __name__ == '__main__':
    main()
