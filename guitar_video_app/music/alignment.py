"""Fit a written part (a tab or score) to a recording, then make it follow what the recording plays.

The tempo map and the audio offset come from the recording's note onsets (Basic Pitch onset
peaks), so the cursor follows the player. The part supplies the notes, and through its rules
(music.rules) how they are played; the audio decides which notes are played and, where the
player clearly differs from the part, when. Parts are music dicts (tempo_bpm, time_signature,
end_beat, notes with pitch), optionally with audio_start, the rough audio second of beat 0.
"""
from __future__ import annotations

from bisect import bisect_left
from fractions import Fraction
import math

import mido

from guitar_video_app.music.rules import PitchRules
from guitar_video_app.music.tempo import beat, beat_at, seconds_at, tempo_at, tempo_map

TEMPO_RANGE = (0.7, 1.4)
TEMPO_STEP = 0.25
MATCH_SECONDS = 0.08
SEARCH_NOTES = 24
ANCHOR_NOTES = 3
ANCHOR_STRENGTH = 0.5
AUDIO_START_SECONDS = 3.0
CANDIDATES = 20
TRANSPOSE_BELOW = 0.5
TRANSPOSE_RANGE = range(-5, 7)
WARP_WINDOWS = (0.2, 0.12, MATCH_SECONDS)
WARP_BEATS = 1.5
MIN_BEAT_RATIO = 0.4
TEMPO_TOLERANCE_SECONDS = 0.015
MOVE_BEATS = Fraction(5, 16)
MOVE_SECONDS = 0.07
STRENGTH_PREFERENCE = 0.15
ADD_STRENGTH = 0.6
ADD_ONSET_SECONDS = 0.04
OVERTONE_LEAD_SECONDS = 0.25
OVERTONE_AFTER_SECONDS = 0.08
OVERTONE_INTERVALS = (12, 19, 24)
EXPECTED_SECONDS = 1.5
SAME_ATTACK_SECONDS = 0.05
REPEAT_SECONDS = 0.18
REPEAT_SIXTEENTHS = 0.9
ROLL_GAP_SECONDS = 0.09
ROLL_SPAN_SECONDS = 0.3
MIN_ADDED_BEATS = Fraction(1, 4)
FAST_BPM = 120


def counted_beat(part: dict) -> int:
    """Written beats per counted beat: 1, doubled while the written tempo is above FAST_BPM.
    The beat windows of fitting and adapting are meant for 60-120 beats a minute, so a tab
    written at quarter = 164 (2/2) is fitted counting half notes at 82, then written back."""
    factor = 1
    while float(part['tempo_bpm']) / factor > FAST_BPM and part['time_signature'][1] * factor * 2 <= 16:
        factor *= 2
    return factor


def scale_beats(data: dict, ratio) -> dict:
    """A copy of a music dict with every beat and every tempo multiplied by ratio, so each
    note keeps its time in seconds; the signature denominator is divided by ratio, so each
    measure keeps its notes."""
    ratio = Fraction(ratio)
    scale = lambda value: str(beat(value) * ratio)
    number = lambda value: int(value) if value == int(value) else float(value)
    tempo = lambda bpm: number(beat(bpm) * ratio)
    out = dict(data, tempo_bpm=tempo(data['tempo_bpm']),
               time_signature=[data['time_signature'][0], int(data['time_signature'][1] / ratio)],
               notes=[dict(n, start_beat=scale(n['start_beat']), duration_beats=scale(n['duration_beats']))
                      for n in data['notes']])
    if 'end_beat' in data:
        out['end_beat'] = scale(data['end_beat'])
    if data.get('tempo_changes'):
        out['tempo_changes'] = [dict(c, beat=scale(c['beat']), bpm=tempo(c['bpm'])) for c in data['tempo_changes']]
    if isinstance(data.get('source'), dict) and 'written_tempo_bpm' in data['source']:
        out['source'] = dict(data['source'], written_tempo_bpm=tempo(data['source']['written_tempo_bpm']))
    return out


def import_to_audio(part: dict, onsets: list, played: list, rules: PitchRules | None = None) -> tuple[dict, dict]:
    """fit_part, then adapt_to_audio (its counts in stats['adapted']), counting beats as
    counted_beat says; the music is in the part's written beats and meter."""
    factor = counted_beat(part)
    music, stats = fit_part(scale_beats(part, Fraction(1, factor)), onsets)
    stats['adapted'] = adapt_to_audio(music, onsets, played, stats['audio_start'], stats['transpose'], rules)
    music = scale_beats(music, factor)
    stats['tempo_bpm'] = round(stats['tempo_bpm'] * factor, 1)
    return music, stats


def fit_part(tab: dict, onsets: list, transpose: int | None = None) -> tuple[dict, dict]:
    """Return the music (the part's beats on a fitted tempo map) and fit statistics.

    onsets are (audio seconds, MIDI pitch, strength). The music starts at audio second
    stats['audio_start'], so the dashboard offset is its negative. transpose fixes the
    audio's semitone shift instead of searching for one.
    """
    exact = sorted((beat(n['start_beat']), n['pitch']) for n in tab['notes'])
    notes = [(float(position), pitch) for position, pitch in exact]
    peaks: dict[int, list[float]] = {}
    strong: dict[int, list[float]] = {}
    for seconds, pitch, strength in onsets:
        peaks.setdefault(int(pitch), []).append(float(seconds))
        if strength >= ANCHOR_STRENGTH:
            strong.setdefault(int(pitch), []).append(float(seconds))
    for times in (*peaks.values(), *strong.values()):
        times.sort()
    written, near = float(tab['tempo_bpm']), tab.get('audio_start')
    search = transpose is None
    transpose = transpose or 0
    score, bpm, start = _search(notes, peaks, strong, written, transpose, near)
    if search and score < TRANSPOSE_BELOW * min(len(notes), SEARCH_NOTES):
        tries = {shift: _search(notes, peaks, strong, written, shift, near) for shift in TRANSPOSE_RANGE if shift}
        best = max(tries, key=lambda shift: tries[shift][0], default=0)
        if best and tries[best][0] > 1.5 * score:
            transpose, (score, bpm, start) = best, tries[best]
    if score <= 0:
        raise ValueError('No notes of the tab were found in the audio.')
    bpm, start = _refine(notes, peaks, transpose, bpm, start)
    end = beat(tab['end_beat'])
    times = _warp(notes, peaks, transpose, bpm, start, math.ceil(end))
    first, changes = _tempo_changes(times)
    lesson = {k: v for k, v in tab.items() if k != 'audio_start'}
    lesson['tempo_bpm'] = first
    if changes:
        lesson['tempo_changes'] = changes
    lesson['source'] = dict(kind='tab', written_tempo_bpm=tab['tempo_bpm'], audio_offset=-round(times[0], 6))
    tempos = tempo_map(lesson)
    errors = []
    for position, pitch in exact:
        predicted = times[0] + float(seconds_at(tempos, position))
        gap = _gap(peaks.get(pitch + transpose, ()), predicted)
        if gap <= MATCH_SECONDS:
            errors.append(gap)
    stats = dict(tempo_bpm=round(bpm, 1), tempo_changes=len(changes), audio_start=round(times[0], 3),
                 matched=len(errors), notes=len(notes), transpose=transpose,
                 mean_error_ms=round(1000 * sum(errors) / len(errors)) if errors else None)
    return lesson, stats


def adapt_to_audio(lesson: dict, onsets: list, played: list, audio_start: float, transpose: int = 0,
                   rules: PitchRules | None = None) -> dict:
    """Make fitted music follow what the recording plays, in place; returns counts.

    played are transcribed notes (audio start, audio end, MIDI pitch). A written note is played
    as written and is removed when no onset of its pitch is within MOVE_BEATS (strong
    onsets preferred). A played note the tab lacks is added when it starts with an onset of
    ADD_STRENGTH+, is not a re-strike of the same pitch within about a 16th (onsets closer than
    SAME_ATTACK_SECONDS are one attack), and is not an octave, twelfth or double octave of a
    note struck just before, unless the tab has that pitch within EXPECTED_SECONDS.

    Attacks chained by gaps of at most ROLL_GAP_SECONDS (strong onsets count as links) over at
    most ROLL_SPAN_SECONDS are one rolled chord. It sits on the earliest written beat of its tab
    notes when that is within MOVE_SECONDS of the roll, else on the grid point of its first
    attack; the grid is 16ths, plus 8th-note triplets in beats where the tab has them. rules
    decide how an added note is played (rules.place); a note it cannot play is left out, and so
    is a second note in one slot at one beat.
    """
    rules = rules or PitchRules()
    tempos = tempo_map(lesson)
    end = beat(lesson['end_beat'])
    to_beat = lambda seconds: beat_at(tempos, Fraction(str(round(seconds - audio_start, 4))))
    to_audio = lambda position: float(seconds_at(tempos, position)) + audio_start
    pitch_of = lambda note: note['pitch']
    tab = sorted(lesson['notes'], key=lambda n: (beat(n['start_beat']), rules.order(n)))
    triplets = {beat(n['start_beat']) // 1 for n in tab if beat(n['start_beat']).denominator % 3 == 0}

    def grid(position):
        steps = (Fraction(1, 4), Fraction(1, 3)) if position // 1 in triplets else (Fraction(1, 4),)
        return min((round(position / step) * step for step in steps), key=lambda q: abs(q - position))

    candidates = sorted((float(abs(to_beat(o[0]) - beat(n['start_beat']))) - STRENGTH_PREFERENCE * o[2], i, j)
                        for i, n in enumerate(tab) for j, o in enumerate(onsets)
                        if o[1] == pitch_of(n) + transpose and abs(to_beat(o[0]) - beat(n['start_beat'])) <= MOVE_BEATS)
    match, used = {}, set()
    for _, i, j in candidates:
        if i not in match and j not in used:
            match[i] = j
            used.add(j)
    events = [dict(time=onsets[j][0], note=tab[i], written=beat(tab[i]['start_beat'])) for i, j in match.items()]
    heard = [(onsets[j][0], onsets[j][1]) for j in used]
    for start_s, end_s, pitch in played:
        if any(abs(t - start_s) < MOVE_SECONDS and p == pitch for t, p in heard):
            continue
        expected = any(pitch_of(n) + transpose == pitch and abs(to_audio(beat(n['start_beat'])) - start_s) <= EXPECTED_SECONDS
                       for n in tab)
        if not expected and any(start_s - OVERTONE_LEAD_SECONDS <= s <= start_s + OVERTONE_AFTER_SECONDS
                                and pitch - p in OVERTONE_INTERVALS for s, _, p in played):
            continue
        attacks = [t for t, p, strength in onsets if abs(t - start_s) < ADD_ONSET_SECONDS and p == pitch and strength >= ADD_STRENGTH]
        if not attacks:
            continue
        attack = min(attacks, key=lambda t: abs(t - start_s))
        strong = sorted((t for t, p, strength in onsets if p == pitch and strength >= ADD_STRENGTH and t < attack), reverse=True)
        for t in strong:
            if attack - t > SAME_ATTACK_SECONDS:
                break
            attack = t
        if not 0 <= grid(to_beat(attack)) < end:
            continue
        repeat = min(REPEAT_SECONDS, REPEAT_SIXTEENTHS * 15 / float(tempo_at(tempos, to_beat(attack))))
        if any(abs(t - attack) < repeat and p == pitch for t, p in heard) or \
                any(0 < attack - t < repeat and p == pitch and strength >= ADD_STRENGTH for t, p, strength in onsets):
            continue
        heard.append((attack, pitch))
        events.append(dict(time=attack, pitch=pitch - transpose, end=end_s))
    marks = sorted([(ev['time'], k, ev) for k, ev in enumerate(events)] +
                   [(t, len(events) + k, None) for k, (t, _, strength) in enumerate(onsets) if strength >= ADD_STRENGTH])
    groups, previous = [], None
    for t, _, ev in marks:
        if groups and t - previous <= ROLL_GAP_SECONDS and t - groups[-1][0] <= ROLL_SPAN_SECONDS:
            groups[-1][1].append(ev)
        else:
            groups.append((t, [ev]))
        previous = t
    chords = [[ev for ev in members if ev] for _, members in groups]
    kept, extra, moved = [], [], 0
    for chord in filter(None, chords):
        first, last = chord[0]['time'], chord[-1]['time']
        written = sorted(ev['written'] for ev in chord if 'note' in ev
                         and first - MOVE_SECONDS <= to_audio(ev['written']) <= last + MOVE_SECONDS)
        start = min(written[0] if written else grid(to_beat(first)), end - MIN_ADDED_BEATS)
        for ev in chord:
            if 'note' not in ev:
                extra.append((start, ev))
                continue
            moved += start != ev['written']
            kept.append(dict(ev['note'], start_beat=str(start),
                             duration_beats=str(min(beat(ev['note']['duration_beats']), end - start))))
    added = []
    for start, ev in extra:
        written_pitch, end_s = ev['pitch'], ev['end']
        notes = kept + added
        if not 0 <= start < end or any(beat(n['start_beat']) == start and pitch_of(n) == written_pitch for n in notes):
            continue
        note = dict(id=f'p{len(added) + 1:03d}', pitch=written_pitch, start_beat=str(start))
        if not rules.place(note, notes, tab):
            continue
        length = max(MIN_ADDED_BEATS, grid(to_beat(end_s)) - start)
        added.append(dict(note, duration_beats=str(min(length, end - start))))
    placed, notes = set(), []
    for note in kept + added:
        key = (rules.slot(note), beat(note['start_beat']))
        if key not in placed:
            placed.add(key)
            notes.append(note)
    lesson['notes'] = sorted(notes, key=lambda n: (beat(n['start_beat']), rules.order(n)))
    return dict(moved=moved, added=len(notes) - len(kept), removed=len(tab) - len(kept))


def played_notes(midi_path) -> list[tuple[float, float, int]]:
    """(start seconds, end seconds, pitch) of every note in a MIDI file."""
    midi = mido.MidiFile(midi_path)
    now, opened, notes = 0.0, {}, []
    for message in midi:
        now += message.time
        if message.type == 'note_on' and message.velocity:
            opened.setdefault(message.note, []).append(now)
        elif message.type in ('note_on', 'note_off') and opened.get(message.note):
            notes.append((opened[message.note].pop(0), now, message.note))
    return sorted(notes)


def _gap(times, target: float) -> float:
    index = bisect_left(times, target)
    return min((abs(times[i] - target) for i in (index - 1, index) if 0 <= i < len(times)), default=math.inf)


def _score(notes, peaks, shift, bpm, start, window=MATCH_SECONDS) -> float:
    return sum(max(0.0, 1 - _gap(peaks.get(pitch + shift, ()), start + position * 60 / bpm) / window)
               for position, pitch in notes)


def _search(notes, peaks, strong, written, shift, near=None):
    """Best (score, bpm, start) on the first SEARCH_NOTES notes; starts come from lining up
    one of the first ANCHOR_NOTES notes with a strong onset of its pitch, within
    AUDIO_START_SECONDS of near when it is given."""
    head = notes[:SEARCH_NOTES]
    anchors = []
    for position, pitch in notes:
        if all(p != pitch for _, p in anchors):
            anchors.append((position, pitch))
        if len(anchors) == ANCHOR_NOTES:
            break
    quick = head[:8]
    found = []
    steps = int((TEMPO_RANGE[1] - TEMPO_RANGE[0]) * written / TEMPO_STEP)
    for step in range(steps + 1):
        bpm = TEMPO_RANGE[0] * written + step * TEMPO_STEP
        starts = {round(t - position * 60 / bpm, 3) for position, pitch in anchors for t in strong.get(pitch + shift, ())
                  if near is None or abs(t - position * 60 / bpm - near) <= AUDIO_START_SECONDS}
        found.extend((_score(quick, peaks, shift, bpm, start), bpm, start) for start in starts)
    found.sort(reverse=True)
    scored = [(_score(head, peaks, shift, bpm, start), bpm, start) for _, bpm, start in found[:CANDIDATES * 10]]
    # A repeated section scores the same; the earliest one wins.
    return max(scored, key=lambda s: (round(s[0], 1), -s[2]), default=(0.0, written, 0.0))


def _refine(notes, peaks, shift, bpm, start):
    options = ((bpm + db / 20, start + ds / 500) for db in range(-20, 21) for ds in range(-20, 21))
    return max(options, key=lambda option: _score(notes, peaks, shift, *option))


def _warp(notes, peaks, shift, bpm, start, beats):
    """Audio time of every whole beat 0..beats: the fitted line, moved by the weighted median
    offset of matched onsets within WARP_BEATS, interpolated where no note was matched."""
    times = [start + k * 60 / bpm for k in range(beats + 1)]
    for window in WARP_WINDOWS:
        pairs = []
        for position, pitch in notes:
            predicted = _at(times, position)
            candidates = peaks.get(pitch + shift, ())
            index = bisect_left(candidates, predicted)
            near = [candidates[i] for i in (index - 1, index) if 0 <= i < len(candidates)]
            onset = min(near, key=lambda t: abs(t - predicted), default=None)
            if onset is not None and abs(onset - predicted) <= window:
                pairs.append((position, onset - predicted))
        offsets = {}
        for k in range(beats + 1):
            near = [(offset, WARP_BEATS - abs(position - k)) for position, offset in pairs if abs(position - k) < WARP_BEATS]
            if near:
                offsets[k] = _weighted_median(near)
        known = sorted(offsets)
        if not known:
            break
        moved = []
        for k in range(beats + 1):
            below = max((i for i in known if i <= k), default=None)
            above = min((i for i in known if i >= k), default=None)
            if below is None or above is None or below == above:
                offset = offsets[below if above is None else above if below is None else below]
            else:
                offset = offsets[below] + (offsets[above] - offsets[below]) * (k - below) / (above - below)
            moved.append(times[k] + offset)
        for k in range(1, len(moved)):
            moved[k] = max(moved[k], moved[k - 1] + MIN_BEAT_RATIO * 60 / bpm)
        times = moved
    return times


def _at(times, position):
    k = min(int(position), len(times) - 2)
    return times[k] + (times[k + 1] - times[k]) * (position - k)


def _weighted_median(values):
    values = sorted(values)
    half, total = sum(w for _, w in values) / 2, 0.0
    for value, weight in values:
        total += weight
        if total >= half:
            return value
    return values[-1][0]


def _tempo_changes(times):
    """Fewest constant-tempo stretches between whole beats that stay within
    TEMPO_TOLERANCE_SECONDS of every beat time; returns the first tempo and the changes."""
    points, a, reached = [], 0, times[0]
    while a < len(times) - 1:
        e = a + 1
        while e + 1 < len(times):
            length = (times[e + 1] - reached) / (e + 1 - a)
            if any(abs(reached + (k - a) * length - times[k]) > TEMPO_TOLERANCE_SECONDS for k in range(a + 1, e + 2)):
                break
            e += 1
        bpm = round(60 * (e - a) / (times[e] - reached), 3)
        points.append((a, bpm))
        reached += (e - a) * 60 / bpm
        a = e
    merged = [point for i, point in enumerate(points) if not i or point[1] != points[i - 1][1]]
    number = lambda v: int(v) if v == int(v) else v
    return number(merged[0][1]), [dict(beat=str(position), bpm=number(bpm)) for position, bpm in merged[1:]]
