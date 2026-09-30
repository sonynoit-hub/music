"""Review existing music against a reference part and the recording.

The reference is fitted to every place the recording plays it (fit_part), and each place is made
to follow the playing (adapt_to_audio). Those bars replace the lesson's notes there; the lesson's
other notes stay. Bar lines and tempo come from the reference where it is played and continue
from its tempo elsewhere, fitted to the lesson's notes. Every kept note keeps its audio time.
How notes are played comes from rules (music.rules): the lesson's rules for the notes it had,
the reference's for the notes it brings.
"""
from __future__ import annotations

from collections import Counter
import copy
from fractions import Fraction
import math

from guitar_video_app.music.alignment import MATCH_SECONDS, _tempo_changes, adapt_to_audio, fit_part
from guitar_video_app.music.retime import RESOLUTION, choose_grid, fit_tempo_map, tidy_lesson, trim_leading_measures
from guitar_video_app.music.rules import PitchRules
from guitar_video_app.music.tempo import beat, beat_at, measure_beats, seconds_at, tempo_map

REPEAT_HEARD = 0.5
REPEAT_RELATIVE = 0.6
MAX_PLACES = 16
MAX_MISSES = 3
MASK_SECONDS = 0.05
COVER_LEAD_SECONDS = 0.07
MOVED_SECONDS = 0.3
MIN_BEAT_RATIO = 0.4
MIN_CLIPPED_BEATS = Fraction(1, 8)


def find_places(tab: dict, onsets: list) -> list[tuple[dict, dict, tuple[float, float]]]:
    """Every place the recording plays the reference, in audio order: (fitted music, fit stats,
    (audio start, audio end)).

    After the best place, the search runs again without the onsets between the first and
    last reference note of the places found. A further place counts when at least REPEAT_HEARD
    of the reference's notes, and REPEAT_RELATIVE of the best place's share, are heard there, and
    its notes overlap no earlier place's by more than a beat. After a place that does not
    count, its first measure is left out too and the search tries again, up to
    MAX_MISSES times.
    """
    lesson, fit = fit_part(tab, onsets)
    places = [(lesson, fit, _span(lesson, fit))]
    need = max(REPEAT_HEARD, REPEAT_RELATIVE * fit['matched'] / fit['notes'])
    anywhere = {k: v for k, v in tab.items() if k != 'audio_start'}
    masked, misses = [_played_span(lesson, fit)], 0
    while len(places) < MAX_PLACES and misses < MAX_MISSES:
        remaining = [o for o in onsets if not any(a - MASK_SECONDS <= o[0] <= b + MASK_SECONDS for a, b in masked)]
        try:
            lesson, found = fit_part(anywhere, remaining, fit['transpose'])
        except ValueError:
            break
        a, b = _played_span(lesson, found)
        slack = 60 / found['tempo_bpm']
        if found['matched'] < need * found['notes'] or any(
                a < y - slack and x + slack < b for x, y in (_played_span(p[0], p[1]) for p in places)):
            misses += 1
            masked.append((a, a + slack * float(measure_beats(tab['time_signature']))))
            continue
        places.append((lesson, found, _span(lesson, found)))
        masked.append((a, b))
    return sorted(places, key=lambda place: place[2][0])


def merge_reference(lesson: dict, offset: float, tab: dict, onsets: list, played: list,
                    lesson_rules: PitchRules | None = None, tab_rules: PitchRules | None = None):
    """Return the merged music, its audio start (the dashboard offset is its negative) and the
    review context for review_report.

    lesson sits in the audio by offset (audio seconds = lesson seconds - offset). onsets are
    Basic Pitch onset peaks (audio seconds, pitch, strength) and played the cleaned
    transcription (audio start, audio end, pitch), as for adapt_to_audio. The context's rules
    (context['rules'], empty rules of tab_rules' kind to start with) say how the merged notes
    are played; context['from_tab'] are the ids of the notes the reference brought.
    """
    lesson_rules = lesson_rules or PitchRules()
    tab_rules = tab_rules or PitchRules()
    out = tab_rules.empty()
    places = find_places(tab, onsets)
    transpose = places[0][1]['transpose']
    signature = [int(v) for v in tab['time_signature']]
    measure = measure_beats(signature)
    old_map = tempo_map(lesson)
    audio_at = lambda position: float(seconds_at(old_map, position)) - offset
    old = [dict(n, audio=audio_at(beat(n['start_beat'])),
                audio_end=audio_at(beat(n['start_beat']) + beat(n['duration_beats']))) for n in lesson['notes']]

    passages = []
    for fitted, fit, (start, _) in places:
        adapted = copy.deepcopy(fitted)
        rules = tab_rules.clone()
        counts = adapt_to_audio(adapted, onsets, played, start, transpose, rules)
        fitted_map = tempo_map(adapted)
        length = math.ceil(beat(adapted['end_beat']) / measure) * measure
        passages.append(dict(notes=adapted['notes'], rules=rules, fit=fit, adapted=counts, length=length,
                             times=[start + float(seconds_at(fitted_map, k)) for k in range(int(length) + 1)]))
    covered = lambda t: any(p['times'][0] - COVER_LEAD_SECONDS <= t < p['times'][-1] - COVER_LEAD_SECONDS
                            for p in passages)
    free = [n for n in old if not covered(n['audio'])]

    first, last = passages[0], passages[-1]
    opening = first['times'][0]
    before = [opening - n['audio'] for n in free if n['audio'] < opening]
    backward = _beats_to_reach(before, first['times'][1] - opening, signature)
    timeline = [opening - t for t in reversed(backward)] + first['times']
    bases = [len(backward)]
    for previous, following in zip(passages, passages[1:]):
        end, gap = previous['times'][-1], following['times'][0] - previous['times'][-1]
        pace = ((previous['times'][-1] - previous['times'][-2]) + (following['times'][1] - following['times'][0])) / 2
        inside = [n['audio'] - end for n in free if end <= n['audio'] < following['times'][0]]
        between = _beats_between(inside, gap, pace, signature)
        if between:
            timeline += [end + t for t in between[:-1]]
        else:
            timeline.pop()
        bases.append(len(timeline))
        timeline += following['times']
    closing = last['times'][-1]
    after = [n['audio'] - closing for n in free if n['audio'] >= closing - COVER_LEAD_SECONDS]
    timeline += [closing + t for t in _beats_to_reach(after, closing - last['times'][-2], signature)]
    for k in range(1, len(timeline)):
        timeline[k] = max(timeline[k], timeline[k - 1] + MIN_BEAT_RATIO * (timeline[1] - timeline[0]))

    first_bpm, changes = _tempo_changes(timeline)
    zero = timeline[0]
    result = {k: v for k, v in lesson.items() if k not in ('notes', 'tempo_changes', 'end_beat')}
    result.update(tempo_bpm=first_bpm, time_signature=signature)
    if changes:
        result['tempo_changes'] = changes
    new_map = tempo_map(result)
    to_beat = lambda t: Fraction(round(beat_at(new_map, Fraction(str(round(t - zero, 6)))) * RESOLUTION), RESOLUTION)

    notes = []
    for index, (passage, base) in enumerate(zip(passages, bases)):
        for note in passage['notes']:
            merged = dict(note, id=note['id'] if not index else f"{note['id']}-{index + 1}",
                          start_beat=str(base + beat(note['start_beat'])))
            out.copy(note, merged, passage['rules'])
            notes.append(merged)
    from_tab = {n['id'] for n in notes}
    taken = {(out.slot(n), beat(n['start_beat'])) for n in notes}
    loose = []
    for note in free:
        start = max(Fraction(0), to_beat(note['audio']))
        length = max(to_beat(note['audio_end']) - start, Fraction(1, RESOLUTION))
        identity = note['id'] if note['id'] not in from_tab else f"{note['id']}-lesson"
        kept = dict(id=identity, pitch=note['pitch'] - transpose, start_beat=str(start), duration_beats=str(length))
        if not (out.default(kept) if transpose else out.copy(note, kept, lesson_rules)):
            continue
        loose.append(kept)
    if loose:
        part = dict(result, notes=loose)
        tidy_lesson(part, grid=choose_grid(part), rules=out)
        for note in part['notes']:
            start = beat(note['start_beat'])
            if (out.slot(note), start) in taken:
                continue
            stop = min((b for b in bases if b > start), default=None)
            if stop is not None and start + beat(note['duration_beats']) > stop and stop - start >= MIN_CLIPPED_BEATS:
                note['duration_beats'] = str(stop - start)
            notes.append(note)
    notes.sort(key=lambda n: (beat(n['start_beat']), out.order(n)))
    ends = max(beat(n['start_beat']) + beat(n['duration_beats']) for n in notes)
    result['end_beat'] = str(max(math.ceil(ends / measure) * measure, bases[-1] + last['length']))
    result['notes'] = notes
    shift = min(beat(n['start_beat']) for n in notes) // measure * measure
    zero += float(trim_leading_measures(result))
    bases = [base - shift for base in bases]
    result['source'] = dict(kind='tab_review', written_tempo_bpm=tab['tempo_bpm'], audio_offset=-round(zero, 6))
    context = dict(old=old, passages=passages, bases=bases, measure=measure, transpose=transpose,
                   from_tab=from_tab, rules=out)
    return result, zero, context


def review_report(context: dict, lesson: dict, zero: float, same=None, ghost=None) -> dict:
    """Pair old and new notes of the same sounding pitch, closest in time first: within
    MATCH_SECONDS they are kept, or 'fingering' when same(old note, new note) says they are
    played differently; within MOVED_SECONDS moved. Unpaired new notes were added, unpaired old
    notes removed, drawn at their place in the new lesson with the fields ghost(old note) gives
    (default: pitch). Adds where each reference place landed."""
    same = same or (lambda old, new: True)
    ghost = ghost or (lambda old: dict(pitch=old['pitch']))
    old, transpose, measure = context['old'], context['transpose'], context['measure']
    new_map = tempo_map(lesson)
    new = [(float(seconds_at(new_map, beat(n['start_beat']))) + zero, n['pitch'] + transpose, n) for n in lesson['notes']]
    pairs = sorted((abs(t - o['audio']), i, j) for i, (t, pitch, _) in enumerate(new)
                   for j, o in enumerate(old) if o['pitch'] == pitch and abs(t - o['audio']) <= MOVED_SECONDS)
    paired, used = {}, set()
    for gap, i, j in pairs:
        if i not in paired and j not in used:
            paired[i] = (j, gap)
            used.add(j)
    changes, counts = {}, Counter(kept=0, fingering=0, moved=0, added=0, removed=0)
    for i, (_, _, note) in enumerate(new):
        if i not in paired:
            kind = 'added'
        else:
            j, gap = paired[i]
            kind = 'moved' if gap > MATCH_SECONDS else ('kept' if same(old[j], note) else 'fingering')
        counts[kind] += 1
        if kind != 'kept':
            changes[note['id']] = kind
    end = beat(lesson['end_beat'])
    removed = []
    for j, o in enumerate(old):
        if j in used:
            continue
        counts['removed'] += 1
        position = beat_at(new_map, Fraction(str(round(o['audio'] - zero, 6))))
        if 0 <= position < end:
            removed.append(dict(start_beat=str(Fraction(round(position * RESOLUTION), RESOLUTION)), **ghost(o)))
    places = [dict(bars=[int(base // measure) + 1, int((base + p['length']) // measure)],
                   heard=p['fit']['matched'], notes=p['fit']['notes'],
                   audio_start=round(p['times'][0], 3), **p['adapted'])
              for p, base in zip(context['passages'], context['bases'])]
    return dict(counts, changes=changes, removed_notes=removed, notes_before=len(old), notes_after=len(new),
                places=places, transpose=transpose, tempo_bpm=lesson['tempo_bpm'],
                tempo_changes=len(lesson.get('tempo_changes', [])))


def _span(lesson: dict, fit: dict) -> tuple[float, float]:
    start = fit['audio_start']
    return start, start + float(seconds_at(tempo_map(lesson), beat(lesson['end_beat'])))


def _played_span(lesson: dict, fit: dict) -> tuple[float, float]:
    """Audio seconds of the first and last note start of fitted music."""
    fitted = tempo_map(lesson)
    starts = [fit['audio_start'] + float(seconds_at(fitted, beat(n['start_beat']))) for n in lesson['notes']]
    return min(starts), max(starts)


def _fitted_map(offsets: list[float], pace: float, signature: list[int]) -> list:
    """Tempo map of per-measure tempos fitted to note times (seconds after beat 0), starting
    from one beat every pace seconds."""
    bpm = Fraction(str(round(60 / pace, 3)))
    part = dict(tempo_bpm=bpm, time_signature=signature,
                notes=[dict(start_beat=str(Fraction(str(round(max(t, 0.0), 4))) * bpm / 60), duration_beats='1/4')
                       for t in offsets])
    if offsets:
        fit_tempo_map(part, choose_grid(part))
    return tempo_map(part)


def _beats_to_reach(offsets: list[float], pace: float, signature: list[int]) -> list[float]:
    """Seconds after the start of beats 1, 2, ... up to the bar line past the last offset."""
    if not offsets:
        return []
    measure = measure_beats(signature)
    fitted = _fitted_map(offsets, pace, signature)
    reach = beat_at(fitted, Fraction(str(round(max(offsets), 4))))
    count = int(max(1, math.ceil((reach + Fraction(1, 8)) / measure)) * measure)
    return [float(seconds_at(fitted, k)) for k in range(1, count + 1)]


def _beats_between(offsets: list[float], gap: float, pace: float, signature: list[int]) -> list[float]:
    """Seconds after the start of the whole measures filling gap seconds, beats 1.. up to
    and including the end; fitted to the offsets, then scaled to end exactly at gap. Empty
    when the gap is under half a measure."""
    measure = measure_beats(signature)
    fitted = _fitted_map(offsets, pace, signature)
    count = int(round(beat_at(fitted, Fraction(str(round(max(gap, 0.0), 4)))) / measure) * measure)
    if count <= 0:
        return []
    span = float(seconds_at(fitted, count))
    return [float(seconds_at(fitted, k)) * gap / span for k in range(1, count + 1)]
