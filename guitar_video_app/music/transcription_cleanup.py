"""Remove common Basic Pitch artifacts from a transcribed MIDI file before instrument mapping."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import json
from pathlib import Path
from statistics import median

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
LINE_CHORD_SECONDS = 0.04
LINE_FRAGMENT_SECONDS = 0.06
LINE_LEGATO_SECONDS = 0.1
ATTACK_STRENGTH = 0.6
ATTACK_MATCH_SECONDS = 0.06
ATTACK_LAST_SECONDS = 0.5
TWELFTH = 19
FUNDAMENTAL_STRENGTH = 0.3
PITCH_SETTLE_SECONDS = 0.03
PITCH_SPAN_SECONDS = 0.15
PITCH_VOICED = 0.3


def clean_transcribed_midi(source: str | Path, target: str | Path, onsets: str | Path | None = None,
                          overtone_min_pitch: int = OVERTONE_MIN_PITCH, line: dict | None = None) -> dict:
    """Write a cleaned copy of source to target and return what changed.

    Overtones: a quieter note exactly 1-2 octaves or an octave and a fifth above a note
    starting within OVERTONE_WINDOW_SECONDS is dropped when it is at overtone_min_pitch or above
    (default C5, fret 8 on a guitar's high E) or shorter than SHORT_SECONDS. Pre-echoes: a short note that runs
    straight into a louder note of the same pitch is dropped. Re-detections: a note that
    starts where the same pitch just ended, and is more than 10% quieter, is joined onto it.
    Recovered repeats: when a pitch has sounded three times at a steady spacing and the model
    saw an onset (strength RECOVER_ONSET_MIN+) exactly where the next (or previous) repeat
    belongs, that note is added. onsets defaults to the .onsets.json written beside source by basic_pitch_runner.
    line (low, high, line='lowest' or 'highest'), e.g. an instrument's transcription options, then
    keeps one line within that range (keep_line); line='attacks' builds the line of an instrument
    recorded alone from the onset peaks instead (attack_line), or keep_line's lowest line when there
    are no onset peaks; line['attack_strength'] replaces ATTACK_STRENGTH and line['pitch'], the path of a
    pitch track (stem_runner's .pitch.json), gives the attacks their pitches. Without line every note is kept.
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
    line_stats = {}
    if line and line.get('line') == 'attacks' and peaks:
        track = json.loads(Path(line['pitch']).read_text(encoding='utf-8')) if line.get('pitch') else None
        kept, line_stats = attack_line(kept, peaks, line.get('low', 0), line.get('high', 127), ticks,
                                       line.get('attack_strength', ATTACK_STRENGTH), track)
    elif line:
        kept, line_stats = keep_line(kept, line.get('low', 0), line.get('high', 127),
                                     lowest=line.get('line', 'lowest') != 'highest')

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
                echoes_removed=len(echoes), rejoined=joined, recovered=len(recovered), **line_stats)


def keep_line(notes: list[dict], low: int, high: int, lowest: bool = True) -> tuple[list[dict], dict]:
    """One line of a full mix, the way a bass plays it: notes within low..high (MIDI pitches) and
    at least LINE_FRAGMENT_SECONDS long; of notes starting within LINE_CHORD_SECONDS the lowest (or,
    with lowest False, the highest); a note starting while a lower (higher) line note still sounds
    for more than LINE_LEGATO_SECONDS is harmony and is dropped; a line note ends where the next one
    starts. Notes need pitch,
    start/end ticks and start_s/end_s seconds. Returns the line and counts of what was dropped."""
    sign = 1 if lowest else -1
    long_enough = lambda n: n['end_s'] - n['start_s'] >= LINE_FRAGMENT_SECONDS
    in_range = [n for n in notes if low <= n['pitch'] <= high]
    candidates = sorted((n for n in in_range if long_enough(n)), key=lambda n: (n['start_s'], sign * n['pitch']))
    line: list[dict] = []
    for note in candidates:
        current = line[-1] if line else None
        if current and note['start_s'] - current['start_s'] <= LINE_CHORD_SECONDS:
            if sign * (note['pitch'] - current['pitch']) < 0:
                line[-1] = dict(note)
            continue
        if (current and current['end_s'] - note['start_s'] > LINE_LEGATO_SECONDS
                and sign * (note['pitch'] - current['pitch']) > 0):
            continue
        if current and current['end_s'] > note['start_s']:
            current['end'], current['end_s'] = note['start'], note['start_s']
        line.append(dict(note))
    cut = [n for n in line if not long_enough(n)]
    line = [n for n in line if long_enough(n)]
    return line, dict(line_out_of_range=len(notes) - len(in_range),
                      line_dropped=len(in_range) - len(line), line_kept=len(line), line_cut_short=len(cut))


def attack_line(notes: list[dict], peaks: list, low: int, high: int, ticks, min_strength: float = ATTACK_STRENGTH,
                track: dict | None = None) -> tuple[list[dict], dict]:
    """One line of an instrument recorded alone, such as a bass in a tab video: Basic Pitch onset peaks
    (seconds, pitch, strength) within low..high that start within LINE_CHORD_SECONDS of each other are one
    attack, played at the pitch struck hardest (the others are its overtones or the string still ringing),
    when that strength is min_strength or more; attacks closer than LINE_FRAGMENT_SECONDS are one, at
    the first one's time and the stronger one's pitch. A low string whose fundamental the recording lost is
    heard loudest at its third harmonic, an octave and a fifth up: when the attack also has the pitch a
    twelfth below (FUNDAMENTAL_STRENGTH or more) and that pitch and its octave together were struck at
    least as hard as the loudest pitch, the note is the pitch a twelfth below. With a pitch track (times and
    fractional MIDI pitches, None where unvoiced, e.g. pYIN on a separated bass) the twelfth rule is not used:
    an attack takes the tracked pitch (tracked_pitch) when it is within low..high. A note lasts until the next attack, or until its
    transcribed note ends if sooner (a transcribed note of its pitch starting within
    ATTACK_MATCH_SECONDS; ATTACK_LAST_SECONDS for the last note without one) and takes that note's
    velocity. notes are transcribed notes as keep_line takes them; ticks converts seconds to ticks."""
    groups: list[list] = []
    for time, pitch, strength in sorted(p for p in peaks if low <= p[1] <= high):
        if groups and time - groups[-1][0][0] <= LINE_CHORD_SECONDS:
            groups[-1].append((time, pitch, strength))
        else:
            groups.append([(time, pitch, strength)])
    struck, lowered = [], 0
    for group in groups:
        time, pitch, strength = max(group, key=lambda peak: peak[2])
        if strength < min_strength:
            continue
        hit = lambda p: max((s for _, q, s in group if q == p), default=0.0)
        below = pitch - TWELFTH
        if not track and hit(below) >= FUNDAMENTAL_STRENGTH and hit(below) + hit(below + 12) >= strength:
            pitch, lowered = below, lowered + 1
        if struck and time - struck[-1][0] < LINE_FRAGMENT_SECONDS:
            if strength > struck[-1][2]:
                struck[-1] = (struck[-1][0], pitch, strength)
            continue
        struck.append((time, pitch, strength))
    model = notes[0] if notes else dict(track=0, channel=0)
    line, tracked = [], 0
    for index, (time, pitch, strength) in enumerate(struck):
        following = struck[index + 1][0] if index + 1 < len(struck) else None
        heard_pitch = tracked_pitch(track, time, following) if track else None
        if heard_pitch is not None and low <= heard_pitch <= high:
            pitch, tracked = heard_pitch, tracked + 1
        same = [n for n in notes if n['pitch'] == pitch and abs(n['start_s'] - time) <= ATTACK_MATCH_SECONDS]
        heard = min(same, key=lambda n: abs(n['start_s'] - time)) if same else None
        ends = [t for t in (following, heard['end_s'] if heard else None) if t is not None]
        end_s = min(ends) if ends else time + ATTACK_LAST_SECONDS
        if end_s - time < LINE_FRAGMENT_SECONDS:
            end_s = following if following is not None else time + LINE_FRAGMENT_SECONDS
        line.append(dict(track=(heard or model)['track'], channel=(heard or model)['channel'], pitch=pitch,
                         velocity=heard['velocity'] if heard else min(127, round(40 + 80 * strength)),
                         start_s=time, end_s=end_s, start=ticks(time), end=ticks(end_s)))
    stats = dict(line_attacks=len(groups), line_kept=len(line), line_weak=len(groups) - len(struck),
                 line_lowered=lowered)
    return line, dict(stats, line_tracked=tracked) if track else stats


def tracked_pitch(track: dict, start: float, end: float | None) -> int | None:
    """The median tracked pitch of a note from PITCH_SETTLE_SECONDS after start until end, at most
    PITCH_SPAN_SECONDS; None when under PITCH_VOICED of those frames have a pitch."""
    times, pitches = track['times'], track['midi']
    first = start + PITCH_SETTLE_SECONDS
    last = min(end if end is not None else first + PITCH_SPAN_SECONDS, first + PITCH_SPAN_SECONDS)
    window = pitches[bisect_left(times, first):bisect_right(times, last)]
    voiced = [p for p in window if p is not None]
    if not voiced or len(voiced) < PITCH_VOICED * len(window):
        return None
    return round(median(voiced))


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
