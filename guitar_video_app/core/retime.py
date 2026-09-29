"""Move a V2 lesson onto a new beat grid while every note keeps its time in seconds."""
from __future__ import annotations

from bisect import bisect_left
import cmath
from fractions import Fraction
from itertools import count
import math

from guitar_video_app.core.lesson_v2 import beat, beat_at, seconds_at, tempo_at, tempo_map

# Stored beats are rounded to 1/960 beat (well under a millisecond at normal tempos).
RESOLUTION = 960
EARLY_TOLERANCE_SECONDS = Fraction(3, 100)


def _snap(value: Fraction) -> Fraction:
    return Fraction(round(value * RESOLUTION), RESOLUTION)


def retime_lesson(data: dict, tempo_bpm: float, first_beat_seconds: float) -> Fraction:
    """Rewrite data in place so first_beat_seconds (lesson time) becomes a measure start.

    The new tempo replaces any tempo changes.

    Notes before that beat get whole lead-in measures, except notes at most
    EARLY_TOLERANCE_SECONDS early, which move onto it. Returns the old lesson time that
    becomes the new beat 0, so callers can shift the audio offset by the same amount.
    """
    old, new = tempo_map(data), Fraction(str(tempo_bpm))
    if not 20 <= new <= 300:
        raise ValueError('Tempo must be between 20 and 300 BPM.')
    first = Fraction(str(first_beat_seconds))
    measure = Fraction(data['time_signature'][0] * 4, data['time_signature'][1])
    tolerance = EARLY_TOLERANCE_SECONDS * new / 60
    to_beats = lambda old_beats: (seconds_at(old, old_beats) - first) * new / 60
    starts = [to_beats(beat(note['start_beat'])) for note in data['notes']]
    shift = max(0, math.ceil((-min(starts, default=0) - tolerance) / measure)) * measure
    ends = []
    for note, start in zip(data['notes'], starts):
        end = to_beats(beat(note['start_beat']) + beat(note['duration_beats']))
        duration = max(_snap(end - start), Fraction(1, RESOLUTION))
        note['start_beat'] = str(max(Fraction(0), _snap(start + shift)))
        note['duration_beats'] = str(duration)
        ends.append(beat(note['start_beat']) + duration)
    if 'end_beat' in data:
        data['end_beat'] = str(max([_snap(to_beats(beat(data['end_beat'])) + shift), *ends]))
    data['tempo_bpm'] = _number(new)
    data.pop('tempo_changes', None)
    return first - shift * 60 / new


def _number(value: Fraction) -> int | float:
    return int(value) if value.denominator == 1 else float(value)


TEMPO_RANGE = (Fraction(4, 5), Fraction(5, 4))
TEMPO_CHANGE_COST = 2
TEMPO_BEAM = 200
TEMPO_BIN_SECONDS = 0.005


def fit_tempo_map(data: dict, grid: Fraction) -> int:
    """Give a measure its own tempo when that puts clearly more notes on the grid.

    Measure lengths are chosen in order by beam search over whole-BPM tempos within
    TEMPO_RANGE of the first tempo. A note costs 1 when it is further than
    SNAP_TOLERANCE_SECONDS from its measure's grid, plus its distance in seconds; each tempo
    change costs TEMPO_CHANGE_COST, so one only appears when it fixes at least two notes.
    Beat 0 and every note's time in seconds stay put. Returns the number of tempo changes.
    """
    old = tempo_map(data)
    base = old[0][2]
    measure = Fraction(data['time_signature'][0] * 4, data['time_signature'][1])
    onsets = sorted(float(seconds_at(old, beat(n['start_beat']))) for n in data['notes'])
    if not onsets:
        return 0
    tempos = sorted({Fraction(t) for t in range(math.ceil(base * TEMPO_RANGE[0]),
                                                 math.floor(base * TEMPO_RANGE[1]) + 1)} | {base})
    tolerance = float(SNAP_TOLERANCE_SECONDS)
    # Every measure owns the notes from half a base-tempo grid step before its start.
    lead = float(grid) * 30 / float(base)

    def cost(start, bpm):
        step = float(grid) * 60 / float(bpm)
        end = start + float(measure) * 60 / float(bpm)
        total = 0.0
        for t in onsets[bisect_left(onsets, start - lead):bisect_left(onsets, end - lead)]:
            off = abs((t - start) / step - round((t - start) / step)) * step
            total += (off > tolerance) + off
        return total

    beam, finished = [(0.0, 0.0, ())], []
    while beam:
        states = {}
        for total, start, path in beam:
            if start - lead > onsets[-1]:
                finished.append((total, path))
                continue
            for bpm in tempos:
                value = total + cost(start, bpm) + (TEMPO_CHANGE_COST if path and bpm != path[-1] else 0)
                following = start + float(measure) * 60 / float(bpm)
                key = (round(following / TEMPO_BIN_SECONDS), bpm)
                if key not in states or value < states[key][0]:
                    states[key] = (value, following, path + (bpm,))
        beam = sorted(states.values(), key=lambda s: s[0])[:TEMPO_BEAM]
    path = min(finished, key=lambda s: s[0])[1]
    changes = [dict(beat=str(index * measure), bpm=_number(bpm))
               for index, bpm in enumerate(path) if index and bpm != path[index - 1]]
    new = tempo_map(dict(tempo_bpm=path[0], tempo_changes=changes))
    convert = lambda position: _snap(beat_at(new, seconds_at(old, position)))
    for note in data['notes']:
        start = beat(note['start_beat'])
        note['start_beat'] = str(convert(start))
        note['duration_beats'] = str(max(Fraction(1, RESOLUTION),
                                         convert(start + beat(note['duration_beats'])) - convert(start)))
    if 'end_beat' in data:
        data['end_beat'] = str(max([convert(beat(data['end_beat'])),
                                    *(beat(n['start_beat']) + beat(n['duration_beats']) for n in data['notes'])]))
    data['tempo_bpm'] = _number(path[0])
    data.pop('tempo_changes', None)
    if changes:
        data['tempo_changes'] = changes
    return len(changes)


OPEN_STRING_MIDI = {1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40}
GRID = Fraction(1, 4)
EIGHTH = Fraction(1, 2)
SNAP_TOLERANCE_SECONDS = Fraction(45, 1000)
CHORD_TOLERANCE_SECONDS = Fraction(8, 100)
DUPLICATE_SECONDS = Fraction(8, 100)
MAX_HOLD_BEATS = 2
MIN_LENGTH_BEATS = GRID / 2
MAX_OFFBEAT_SIXTEENTHS = Fraction(1, 10)
MAX_REPEAT_BEATS = 2
REPEAT_ONSET_MIN = 0.4
OVERTONE_INTERVALS = (12, 19, 24)


def _pitch(note: dict) -> int:
    return OPEN_STRING_MIDI[note['string']] + note['fret']


def is_bass(note: dict, notes: list[dict], measure: Fraction) -> bool:
    """Strings 5-6, or a string-4 note that is held at least a beat or starts a measure, with
    no lower note from the same measure still sounding.

    Notes need 'start' and 'end' in beats. The dashboard notation uses the same rule.
    """
    if note['string'] >= 5:
        return True
    if note['string'] < 4 or (note['end'] - note['start'] < 1 and note['start'] % measure):
        return False
    pitch, bar = _pitch(note), note['start'] // measure
    return not any(_pitch(other) < pitch and other['start'] // measure == bar
                   and other['start'] <= note['start'] < other['end']
                   for other in notes if other is not note)


def choose_grid(data: dict) -> Fraction:
    """8th notes unless more than a tenth of the notes sit clearly on an in-between 16th."""
    tempos = tempo_map(data)
    starts = [beat(n['start_beat']) for n in data['notes']]
    offbeat = sum(1 for s in starts
                  if abs(s - round(s / GRID) * GRID) <= SNAP_TOLERANCE_SECONDS * tempo_at(tempos, s) / 60
                  and round(s / GRID) % 2)
    return EIGHTH if starts and offbeat <= MAX_OFFBEAT_SIXTEENTHS * len(starts) else GRID


def restore_repeats(data: dict, onsets: list, grid: Fraction) -> int:
    """Add the notes a steady on-grid repeat predicts where the audio has their onset.

    When a pitch starts on two grid lines up to MAX_REPEAT_BEATS apart, the next (and the
    previous) repeat at that spacing is added on the same string and fret if the model saw
    an onset of that pitch (strength REPEAT_ONSET_MIN+) within SNAP_TOLERANCE_SECONDS of
    it, no other note of that pitch starts between, and nothing starting there uses that
    string or explains the onset as an overtone (OVERTONE_INTERVALS below). Onsets are
    (lesson seconds, MIDI pitch, strength). Run on a fitted tempo map, before tidy_lesson.
    Returns the number of notes added.
    """
    tempos = tempo_map(data)
    tolerance = SNAP_TOLERANCE_SECONDS
    end = beat(data['end_beat']) if 'end_beat' in data else max(
        beat(n['start_beat']) + beat(n['duration_beats']) for n in data['notes'])
    peaks: dict[int, list[Fraction]] = {}
    for seconds, pitch, strength in onsets:
        if strength >= REPEAT_ONSET_MIN:
            peaks.setdefault(pitch, []).append(Fraction(str(seconds)))

    def grid_line(note):
        start = beat(note['start_beat'])
        target = round(start / grid) * grid
        return target if abs(start - target) <= tolerance * tempo_at(tempos, target) / 60 else None

    added, found = 0, True
    while found:
        found = False
        starts: dict[int, list[Fraction]] = {}
        for note in data['notes']:
            starts.setdefault(_pitch(note), []).append(beat(note['start_beat']))
        lines: dict[int, dict[Fraction, dict]] = {}
        for note in data['notes']:
            line = grid_line(note)
            if line is not None:
                lines.setdefault(_pitch(note), {})[line] = note
        for pitch, by_line in lines.items():
            positions = sorted(by_line)
            for a, b in zip(positions, positions[1:]):
                spacing = b - a
                if spacing > MAX_REPEAT_BEATS:
                    continue
                for model, candidate, lo, hi in ((by_line[b], b + spacing, b + grid / 2, b + spacing * 3 / 2),
                                                 (by_line[a], a - spacing, a - spacing * 3 / 2, a - grid / 2)):
                    at = seconds_at(tempos, candidate)
                    nearby = [n for n in data['notes'] if abs(beat(n['start_beat']) - candidate) < grid]
                    if (not 0 <= candidate < end
                            or any(lo < s < hi for s in starts[pitch])
                            or not any(abs(t - at) <= tolerance for t in peaks.get(pitch, ()))
                            or any(n['string'] == model['string'] or pitch - _pitch(n) in OVERTONE_INTERVALS
                                   for n in nearby)):
                        continue
                    added += 1
                    ids = {n['id'] for n in data['notes']}
                    identity = next(f'restored-{i:03d}' for i in count(1) if f'restored-{i:03d}' not in ids)
                    data['notes'].append(dict(model, id=identity, start_beat=str(candidate),
                                              duration_beats=str(min(spacing, end - candidate))))
                    found = True
                    break
                if found:
                    break
            if found:
                break
    return added


def tidy_lesson(data: dict, snap: bool = True, duplicates: bool = True, lengths: bool = True,
                grid: Fraction | None = None) -> dict:
    """Clean transcribed timing in place on an 8th or 16th grid; returns counts.

    grid: None picks one with choose_grid. duplicates: a note repeating the same pitch
    within DUPLICATE_SECONDS is merged into the earlier one. snap: starts within
    SNAP_TOLERANCE_SECONDS of a grid line move onto it, unless another note on that string
    already starts there. lengths: each note lasts until the next note in its voice
    (bass, see is_bass, or melody), at most MAX_HOLD_BEATS for melody and one measure for
    bass; the last note of a voice keeps its length rounded to the grid, except that the
    last bass note rings to its bar line once it already lasts half the rest of the measure.
    """
    tempos = tempo_map(data)
    per_second = lambda position: tempo_at(tempos, position) / 60
    grid = grid or choose_grid(data)
    measure = Fraction(data['time_signature'][0] * 4, data['time_signature'][1])
    notes = [dict(n, start=beat(n['start_beat']), end=beat(n['start_beat']) + beat(n['duration_beats']))
             for n in data['notes']]
    notes.sort(key=lambda n: (n['start'], n['string']))
    stats = dict(grid=str(grid), removed=0, snapped=0, not_snapped=0, max_shift_ms=0, lengthened=0, shortened=0)
    if duplicates:
        kept = []
        for note in notes:
            twin = next((k for k in reversed(kept) if note['start'] - k['start'] <= DUPLICATE_SECONDS * per_second(k['start'])
                         and _pitch(k) == _pitch(note)), None)
            if twin:
                twin['end'] = max(twin['end'], note['end'])
                stats['removed'] += 1
            else:
                kept.append(note)
        notes = kept
    if snap:
        taken = set()
        for note in notes:
            target = round(note['start'] / grid) * grid
            shift = abs(note['start'] - target)
            if shift and shift <= SNAP_TOLERANCE_SECONDS * per_second(target) and (note['string'], target) not in taken:
                duration = note['end'] - note['start']
                note['start'], note['end'] = target, target + duration
                stats['snapped'] += 1
                stats['max_shift_ms'] = max(stats['max_shift_ms'], round(float(shift / per_second(target)) * 1000))
            elif shift:
                stats['not_snapped'] += 1
            taken.add((note['string'], note['start']))
        # A note slightly behind a chord (thumb after fingers) joins that chord's grid line.
        onsets = {start for _, start in taken if start % grid == 0}
        for note in notes:
            target = round(note['start'] / grid) * grid
            shift = abs(note['start'] - target)
            if (shift and shift <= CHORD_TOLERANCE_SECONDS * per_second(target) and target in onsets
                    and (note['string'], target) not in taken):
                duration = note['end'] - note['start']
                note['start'], note['end'] = target, target + duration
                taken.add((note['string'], target))
                stats['snapped'] += 1
                stats['not_snapped'] -= 1
                stats['max_shift_ms'] = max(stats['max_shift_ms'], round(float(shift / per_second(target)) * 1000))
        notes.sort(key=lambda n: (n['start'], n['string']))
    if lengths:
        bass = [is_bass(n, notes, measure) for n in notes]
        for voice, hold in ((True, measure), (False, MAX_HOLD_BEATS)):
            part = [n for n, low in zip(notes, bass) if low is voice]
            starts = sorted({n['start'] for n in part})
            for note in part:
                later = [s for s in starts if s > note['start']]
                if later and later[0] - note['start'] <= hold:
                    end = later[0]
                else:
                    end = note['start'] + max(grid, round((note['end'] - note['start']) / grid) * grid)
                    bar = (note['start'] // measure + 1) * measure
                    if later:
                        end = min(end, later[0])
                    elif voice and 2 * (end - note['start']) >= bar - note['start']:
                        end = max(end, bar)
                end = max(end, note['start'] + MIN_LENGTH_BEATS)
                if end > note['end']:
                    stats['lengthened'] += 1
                elif end < note['end']:
                    stats['shortened'] += 1
                note['end'] = end
    for note in notes:
        note['start_beat'] = str(note['start'])
        note['duration_beats'] = str(note['end'] - note['start'])
    data['notes'] = [{k: v for k, v in n.items() if k not in ('start', 'end')} for n in notes]
    if 'end_beat' in data:
        data['end_beat'] = str(max([beat(data['end_beat']), *(n['end'] for n in notes)]))
    return stats


def suggest_grid(onsets: list[float]) -> tuple[float, float]:
    """Best-fitting tempo and a beat near the first onset, from note start times in seconds.

    Onsets are scored against a 16th-note grid for tempos from 60 to 180 BPM; a slower
    tempo wins ties because its grid is coarser.
    """
    onsets = sorted(set(onsets))
    if len(onsets) < 4:
        raise ValueError('At least four notes are needed to suggest a tempo.')

    def fit(tempo: float, divisions: int) -> complex:
        period = 60 / tempo / divisions
        return sum(cmath.exp(2j * math.pi * t / period) for t in onsets) / len(onsets)

    tempo = max((step / 2 for step in range(120, 361)), key=lambda t: (round(abs(fit(t, 4)), 3), -t))
    period = 60 / tempo
    sixteenth = cmath.phase(fit(tempo, 4)) / (2 * math.pi) * period / 4
    # Of the four 16th positions, the beat is the one most notes land on.
    phase = max((sixteenth + k * period / 4 for k in range(4)),
                key=lambda p: sum(math.cos(2 * math.pi * (t - p) / period) for t in onsets))
    first = phase + round((onsets[0] - phase) / period) * period
    return tempo, round(first, 3)
