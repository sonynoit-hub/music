"""Remove common Basic Pitch artifacts from a transcribed MIDI file before instrument mapping."""
from __future__ import annotations

from bisect import bisect_right
import json
from pathlib import Path

import mido

TOUCH_SECONDS = 0.03
DECAY_RATIO = 0.9
OVERTONE_INTERVALS = (12, 19, 24)
OVERTONE_MIN_PITCH = 72
OVERTONE_WINDOW_SECONDS = 0.08
SHORT_SECONDS = 0.16
PRE_ECHO_SECONDS = 0.2
RECOVER_ONSET_MIN = 0.4
REPEAT_TOLERANCE_SECONDS = 0.05
REPEAT_GAP_SECONDS = (0.2, 1.2)


def clean_transcribed_midi(source: str | Path, target: str | Path, onsets: str | Path | None = None,
                          overtone_min_pitch: int = OVERTONE_MIN_PITCH) -> dict:
    """Write a cleaned copy of source to target and return what changed.

    Overtones: a quieter note exactly 1-2 octaves or an octave and a fifth above a note
    starting within OVERTONE_WINDOW_SECONDS is dropped when it is at overtone_min_pitch or above
    (default C5, fret 8 on a guitar's high E) or shorter than SHORT_SECONDS. Pre-echoes: a short note that runs
    straight into a louder note of the same pitch is dropped. Re-detections: a note that
    starts where the same pitch just ended, and is more than 10% quieter, is joined onto it.
    Recovered repeats: when a pitch has sounded three times at a steady spacing and the model
    saw an onset (strength RECOVER_ONSET_MIN+) exactly where the next (or previous) repeat
    belongs, that note is added. onsets defaults to the .onsets.json written beside source by basic_pitch_runner.
    """
    midi = mido.MidiFile(source)
    seconds, ticks = _tick_clock(midi)
    tracks = []
    notes = []
    for index, track in enumerate(midi.tracks):
        tick, other, open_notes = 0, [], {}
        for message in track:
            tick += message.time
            if message.type == 'note_on' and message.velocity:
                open_notes.setdefault((message.channel, message.note), []).append((tick, message.velocity))
            elif message.type in ('note_on', 'note_off'):
                started = open_notes.get((message.channel, message.note))
                if started:
                    start, velocity = started.pop(0)
                    notes.append(dict(track=index, channel=message.channel, pitch=message.note,
                                      start=start, end=tick, velocity=velocity))
            else:
                other.append((tick, message))
        tracks.append(other)
    for note in notes:
        note['start_s'], note['end_s'] = seconds(note['start']), seconds(note['end'])
    notes.sort(key=lambda n: (n['start'], n['pitch']))
    detected = len(notes)

    overtones = [n for n in notes if _is_overtone(n, notes, overtone_min_pitch)]
    notes = [n for n in notes if not any(n is o for o in overtones)]
    echoes = [n for n in notes if _is_pre_echo(n, notes)]
    notes = [n for n in notes if not any(n is e for e in echoes)]
    kept, last, joined = [], {}, 0
    for note in notes:
        key = (note['track'], note['channel'], note['pitch'])
        previous = last.get(key)
        if (previous and 0 <= note['start_s'] - previous['end_s'] <= TOUCH_SECONDS
                and note['velocity'] < DECAY_RATIO * previous['segment_velocity']):
            previous['end'], previous['end_s'] = note['end'], note['end_s']
            previous['segment_velocity'] = note['velocity']
            joined += 1
            continue
        note['segment_velocity'] = note['velocity']
        kept.append(note)
        last[key] = note

    onsets_path = Path(onsets) if onsets else Path(source).with_suffix('.onsets.json')
    peaks = json.loads(onsets_path.read_text(encoding='utf-8')) if onsets_path.exists() else []
    recovered = _recover_repeats(kept, peaks, ticks)
    kept.extend(recovered)

    for note in kept:
        tracks[note['track']].append((note['start'], mido.Message(
            'note_on', channel=note['channel'], note=note['pitch'], velocity=note['velocity'])))
        tracks[note['track']].append((note['end'], mido.Message(
            'note_off', channel=note['channel'], note=note['pitch'], velocity=0)))
    output = mido.MidiFile(type=midi.type, ticks_per_beat=midi.ticks_per_beat)
    for events in tracks:
        # At one tick: meta first, then note-offs before note-ons; end_of_track stays last.
        order = lambda item: (item[1].type == 'end_of_track', item[0],
                              0 if item[1].is_meta else 1 if item[1].type == 'note_off' else 2)
        track, now = mido.MidiTrack(), 0
        for tick, message in sorted(events, key=order):
            tick = max(tick, now)
            track.append(message.copy(time=tick - now))
            now = tick
        output.tracks.append(track)
    output.save(target)
    return dict(detected=detected, kept=len(kept), overtones_removed=len(overtones),
                echoes_removed=len(echoes), rejoined=joined, recovered=len(recovered))


def _is_overtone(note: dict, notes: list[dict], min_pitch: int = OVERTONE_MIN_PITCH) -> bool:
    if note['pitch'] < min_pitch and note['end_s'] - note['start_s'] > SHORT_SECONDS:
        return False
    return any(note['pitch'] - other['pitch'] in OVERTONE_INTERVALS
               and abs(note['start_s'] - other['start_s']) <= OVERTONE_WINDOW_SECONDS
               and other['velocity'] > note['velocity']
               for other in notes)


def _is_pre_echo(note: dict, notes: list[dict]) -> bool:
    if note['end_s'] - note['start_s'] > PRE_ECHO_SECONDS:
        return False
    return any(other['pitch'] == note['pitch'] and other['start_s'] > note['start_s']
               and abs(other['start_s'] - note['end_s']) <= TOUCH_SECONDS
               and note['velocity'] < DECAY_RATIO * other['velocity']
               for other in notes)


def _recover_repeats(notes: list[dict], peaks: list, ticks) -> list[dict]:
    low, high = REPEAT_GAP_SECONDS
    starts: dict[int, list[dict]] = {}
    for note in notes:
        starts.setdefault(note['pitch'], []).append(note)
    for group in starts.values():
        group.sort(key=lambda n: n['start_s'])
    added = []
    for time, pitch, strength in sorted(peaks):
        group = starts.get(pitch)
        if strength < RECOVER_ONSET_MIN or not group:
            continue
        if any(abs(n['start_s'] - time) < low for n in group):
            continue
        before = [n['start_s'] for n in group if n['start_s'] < time][-3:]
        after = [n['start_s'] for n in group if n['start_s'] > time][:3]
        gap = None
        if len(before) == 3 and _steady(before + [time]):
            gap, model = before[2] - before[1], next(n for n in group if n['start_s'] == before[2])
        elif len(after) == 3 and _steady([time] + after):
            gap, model = after[1] - after[0], next(n for n in group if n['start_s'] == after[0])
        if gap is None or not low <= gap <= high:
            continue
        end_s = min([time + gap] + after)
        note = dict(model, start_s=time, end_s=end_s, start=ticks(time), end=ticks(end_s))
        added.append(note)
        group.append(note)
        group.sort(key=lambda n: n['start_s'])
    return added


def _steady(times: list[float]) -> bool:
    gaps = [b - a for a, b in zip(times, times[1:])]
    return max(gaps) - min(gaps) <= REPEAT_TOLERANCE_SECONDS


def _tick_clock(midi: mido.MidiFile):
    changes = sorted((tick, message.tempo) for tick, message in _absolute(midi) if message.type == 'set_tempo')
    points, tick0, time0, tempo = [(0, 0.0, 500000)], 0, 0.0, 500000
    for tick, new_tempo in changes:
        time0 += mido.tick2second(tick - tick0, midi.ticks_per_beat, tempo)
        tick0, tempo = tick, new_tempo
        points.append((tick0, time0, tempo))
    tick_marks = [p[0] for p in points]
    time_marks = [p[1] for p in points]

    def seconds(tick: int) -> float:
        start, at, rate = points[bisect_right(tick_marks, tick) - 1]
        return at + mido.tick2second(tick - start, midi.ticks_per_beat, rate)

    def ticks(time: float) -> int:
        start, at, rate = points[max(0, bisect_right(time_marks, time) - 1)]
        return start + round(mido.second2tick(time - at, midi.ticks_per_beat, rate))

    return seconds, ticks


def _absolute(midi: mido.MidiFile):
    for track in midi.tracks:
        tick = 0
        for message in track:
            tick += message.time
            yield tick, message
