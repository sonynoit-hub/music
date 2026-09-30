"""Which hand plays each piano note.

hands_from_tracks reads them from a MIDI file whose notes are split into a left- and a right-hand
track (or channel). plan_hands chooses them for the whole song at once: notes starting within
CHORD_SECONDS form a group, and each group is split into a lower part for the left hand and an
upper part for the right. The cheapest path through all groups wins, where cost comes from

- moving a hand: each hand covers an octave around its position (REACH on each side) and only
  moves, at MOVE per semitone, when a note falls outside it;
- stretching: a hand's notes (with the notes it still holds) spanning more than COMFORT_SPAN
  semitones, and much more above MAX_SPAN (a 10th) or MAX_NOTES notes;
- crossing: the right hand's position below the left's;
- register: a slight preference for the left hand below middle C and the right hand above it.

Notes whose hand is fixed (chosen in the dashboard, or read from MIDI tracks) keep it and only the
other notes are split. Hand position depends on earlier choices, so each split keeps the positions
of the best path that reaches it (a Viterbi search with path state).
"""
from __future__ import annotations

from collections import defaultdict
import re

from guitar_video_app.instruments.piano.keyboard import MIDDLE_C
from guitar_video_app.music.tempo import beat, seconds_at, tempo_map

CHORD_SECONDS = 0.04
REACH = 6
MOVE = 1.0
CENTER_PULL = 0.1
COMFORT_SPAN = 12
MAX_SPAN = 16
MAX_NOTES = 5
STRETCH = 3.0
OVER_STRETCH = 50.0
OVER_NOTES = 50.0
HELD_WEIGHT = 0.5
CROSS = 5.0
CROSS_GAP = 3
REGISTER = 0.2
START = {'left': 48, 'right': 72}
HELD_EPSILON = 0.05

# At least this share of each track's chords must fit one hand to trust the tracks as hands.
TRACK_FIT = 0.9
MIN_TRACK_GAP = 3
LEFT_NAMES = re.compile(r'\b(left|lh|l\.h\.|bass)\b', re.IGNORECASE)
RIGHT_NAMES = re.compile(r'\b(right|rh|r\.h\.|treble|melody)\b', re.IGNORECASE)


def _groups(items, start):
    """Consecutive items (sorted by start) whose starts are within CHORD_SECONDS of the group's first."""
    groups = []
    for item in sorted(items, key=lambda i: (start(i), i['pitch'])):
        if groups and start(item) - start(groups[-1][0]) <= CHORD_SECONDS:
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


def _hand_cost(pitches, held, position):
    """Cost of one hand playing pitches while holding held, and its new position."""
    if not pitches:
        return 0.0, position
    low, high = min(pitches), max(pitches)
    cost = MOVE * (max(0, high - (position + REACH)) + max(0, (position - REACH) - low))
    center = (low + high) / 2
    cost += CENTER_PULL * abs(center - position)
    span = high - low
    cost += STRETCH * max(0, span - COMFORT_SPAN) + OVER_STRETCH * max(0, span - MAX_SPAN)
    if held:
        wide = max(high, *held) - min(low, *held)
        cost += HELD_WEIGHT * (STRETCH * max(0, wide - COMFORT_SPAN) + OVER_STRETCH / 10 * max(0, wide - MAX_SPAN))
    cost += OVER_NOTES * max(0, len(pitches) + len(held) - MAX_NOTES)
    # The hand moves just enough to cover its notes; a stretch wider than an octave centers it.
    if span <= 2 * REACH:
        new = min(max(position, high - REACH), low + REACH)
    else:
        new = center
    return cost, new


def plan_hands(music: dict, fixed: dict[str, str] | None = None) -> dict[str, str]:
    """{note id: 'left' | 'right'} for every note of a music layer; fixed notes keep their hand."""
    fixed = fixed or {}
    tempos = tempo_map(music)
    timed = []
    for note in music['notes']:
        start = beat(note['start_beat'])
        timed.append(dict(id=note['id'], pitch=note['pitch'], start=float(seconds_at(tempos, start)),
                          end=float(seconds_at(tempos, start + beat(note['duration_beats'])))))
    groups = _groups(timed, lambda n: n['start'])
    # A state is the best path ending in one split of the group: (cost, index of the previous
    # group's state, hands chosen in this group, hand positions, held notes as (end, pitch, hand)).
    states = [(0.0, None, {}, dict(START), [])]
    history = []
    for group in groups:
        now = group[0]['start']
        locked = [n for n in group if n['id'] in fixed]
        free = sorted((n for n in group if n['id'] not in fixed), key=lambda n: n['pitch'])
        best = {}
        for index, (cost, _, _, positions, held) in enumerate(states):
            held = [h for h in held if h[0] > now + HELD_EPSILON]
            for split in range(len(free) + 1):
                chosen = {n['id']: fixed[n['id']] for n in locked}
                chosen.update((n['id'], 'left') for n in free[:split])
                chosen.update((n['id'], 'right') for n in free[split:])
                total, moved = cost, {}
                for hand in ('left', 'right'):
                    pitches = [n['pitch'] for n in group if chosen[n['id']] == hand]
                    step, moved[hand] = _hand_cost(pitches, [p for _, p, h in held if h == hand], positions[hand])
                    total += step
                    side = (lambda p: p > MIDDLE_C) if hand == 'left' else (lambda p: p < MIDDLE_C)
                    total += REGISTER * sum(abs(p - MIDDLE_C) for p in pitches if side(p))
                left = [n['pitch'] for n in group if chosen[n['id']] == 'left']
                right = [n['pitch'] for n in group if chosen[n['id']] == 'right']
                if left and right:
                    total += CROSS * max(0, max(left) - min(right) + 1)
                total += CROSS * max(0, moved['left'] + CROSS_GAP - moved['right'])
                if split not in best or total < best[split][0]:
                    best[split] = (total, index, chosen, moved,
                                   held + [(n['end'], n['pitch'], chosen[n['id']]) for n in group])
        history.append(states)
        states = list(best.values())
    hands = {}
    state = min(states, key=lambda s: s[0])
    for previous in reversed(history):
        hands.update(state[2])
        if state[1] is None:
            break
        state = previous[state[1]]
    return hands


def hands_from_tracks(notes: list[dict], tracks: list[dict] | None = None) -> dict[int, str] | None:
    """{note index: hand} when the notes come in two tracks (or two channels) that look like a left
    and a right hand, else None. Track names like "Left Hand" or "RH" decide which is which;
    otherwise the higher track is the right hand."""
    names = {t.get('id'): t.get('name') or '' for t in (tracks or [])}
    for field in ('track_id', 'channel'):
        by = defaultdict(list)
        for index, note in enumerate(notes):
            by[note.get(field)].append(index)
        if len(by) != 2 or None in by:
            continue
        (a, first), (b, second) = sorted(by.items(), key=lambda kv: sum(notes[i]['pitch'] for i in kv[1]) / len(kv[1]))
        side = {}
        if field == 'track_id':
            for key in (a, b):
                name = names.get(key, '')
                if LEFT_NAMES.search(name):
                    side[key] = 'left'
                elif RIGHT_NAMES.search(name):
                    side[key] = 'right'
        if len(side) == 2 and side[a] != side[b]:
            left, right = (a, b) if side[a] == 'left' else (b, a)
        elif len(side) == 1:
            known, hand = next(iter(side.items()))
            other = b if known == a else a
            left, right = (known, other) if hand == 'left' else (other, known)
        else:
            mean = lambda indices: sum(notes[i]['pitch'] for i in indices) / len(indices)
            if mean(second) - mean(first) < MIN_TRACK_GAP:
                continue
            left, right = a, b
        if all(_fits_one_hand([notes[i] for i in by[key]]) for key in (left, right)):
            return {i: 'left' for i in by[left]} | {i: 'right' for i in by[right]}
    return None


def _fits_one_hand(notes):
    chords = _groups(notes, lambda n: float(n['start_seconds']))
    fitting = sum(1 for chord in chords
                  if len(chord) <= MAX_NOTES and max(n['pitch'] for n in chord) - min(n['pitch'] for n in chord) <= MAX_SPAN)
    return fitting >= TRACK_FIT * len(chords)
