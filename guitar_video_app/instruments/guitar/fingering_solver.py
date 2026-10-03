from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from guitar_video_app.instruments.fretted import GUITAR_SPEC, Fretted
from guitar_video_app.instruments.guitar.schema import GuitarPosition
from guitar_video_app.instruments.guitar.tuning import possible_positions
from guitar_video_app.music.schema import RawNote


def choose_positions(
    notes: list[RawNote],
    previous: list[GuitarPosition] | None = None,
    max_fret_span: int = 5,
    max_fret: int = 20,
) -> list[GuitarPosition]:
    candidates = [possible_positions(note.pitch, max_fret=max_fret) for note in notes]
    if any(not item for item in candidates):
        missing = [note.pitch for note, item in zip(notes, candidates) if not item]
        raise ValueError(f"Unplayable note(s) for standard guitar tuning: {missing}")

    best: tuple[float, tuple[GuitarPosition, ...]] | None = None
    for combo in product(*candidates):
        strings = [pos.string for pos in combo]
        if len(strings) != len(set(strings)):
            continue
        fretted = [pos.fret for pos in combo if pos.fret > 0]
        if fretted and max(fretted) - min(fretted) > max_fret_span:
            continue
        score = _score_combo(combo, previous)
        if best is None or score < best[0]:
            best = (score, combo)

    if best is None:
        raise ValueError("No playable fingering found within span/string constraints")
    return list(best[1])


def _score_combo(combo: tuple[GuitarPosition, ...], previous: list[GuitarPosition] | None) -> float:
    frets = [pos.fret for pos in combo]
    open_strings = sum(1 for fret in frets if fret == 0)
    high_fret_cost = sum(frets) * 0.8
    span_cost = (max(frets) - min(frets)) * 2.0 if len(frets) > 1 else 0.0
    open_string_cost = open_strings * 0.25

    movement_cost = 0.0
    if previous:
        prev_fretted = [pos.fret for pos in previous if pos.fret > 0]
        curr_fretted = [pos.fret for pos in combo if pos.fret > 0]
        if prev_fretted and curr_fretted:
            movement_cost = abs(_center(prev_fretted) - _center(curr_fretted)) * 3.0

    return high_fret_cost + span_cost + open_string_cost + movement_cost


def _center(values: list[int]) -> float:
    return sum(values) / len(values)


CHORD_TOLERANCE_SECONDS = 0.04
RING_GRACE_SECONDS = 0.05
HAND_SPAN = 3
COMFORT_FRET = 7
BEAM_WIDTH = 48
OPTIONS_PER_GROUP = 40
DROP_COST = 40.0


@dataclass(frozen=True)
class _Path:
    cost: float
    hand: int | None
    ringing: tuple[tuple[int, float, int], ...]
    pitch_strings: tuple[tuple[int, int], ...]
    choice: tuple[GuitarPosition | None, ...] | None
    parent: _Path | None


def choose_song_positions(
    notes: list[RawNote],
    fixed: dict[int, GuitarPosition] | None = None,
    *,
    max_fret: int = 20,
    max_fret_span: int = 5,
    tolerate_unplayable: bool = False,
) -> list[GuitarPosition | None]:
    """Choose positions for a whole song at once.

    Notes starting within CHORD_TOLERANCE_SECONDS form one chord. A beam search keeps the
    hand in one position, avoids strings that are still ringing, and keeps repeated pitches
    on the same string. Unplayable notes become None when tolerate_unplayable is set.
    """
    fixed = fixed or {}
    groups: list[list[int]] = []
    for index in sorted(range(len(notes)), key=lambda i: (notes[i].start_time, notes[i].pitch)):
        if groups and notes[index].start_time - notes[groups[-1][0]].start_time <= CHORD_TOLERANCE_SECONDS:
            groups[-1].append(index)
        else:
            groups.append([index])

    beam = [_Path(0.0, None, (), (), None, None)]
    for group in groups:
        options = _group_options(notes, group, fixed, max_fret, max_fret_span, tolerate_unplayable)
        start = min(notes[index].start_time for index in group)
        best: dict[tuple, _Path] = {}
        for path in beam:
            ringing = {string: (end, fret) for string, end, fret in path.ringing if end > start}
            pitch_strings = dict(path.pitch_strings)
            for static_cost, combo in options:
                cost, hand = _transition_cost(combo, group, notes, path.hand, ringing, pitch_strings, start)
                new_ringing = dict(ringing)
                new_pitch_strings = dict(pitch_strings)
                for index, position in zip(group, combo):
                    if position is not None:
                        new_ringing[position.string] = (notes[index].end_time, position.fret)
                        new_pitch_strings[notes[index].pitch] = position.string
                candidate = _Path(
                    path.cost + static_cost + cost,
                    hand,
                    tuple(sorted((string, end, fret) for string, (end, fret) in new_ringing.items())),
                    tuple(sorted(new_pitch_strings.items())),
                    combo,
                    path,
                )
                key = (hand, tuple((string, fret) for string, _, fret in candidate.ringing), candidate.pitch_strings)
                if key not in best or candidate.cost < best[key].cost:
                    best[key] = candidate
        beam = sorted(best.values(), key=lambda item: item.cost)[:BEAM_WIDTH]

    result: list[GuitarPosition | None] = [None] * len(notes)
    path = beam[0]
    for group in reversed(groups):
        for index, position in zip(group, path.choice):
            result[index] = position
        path = path.parent
    return result


def _group_options(
    notes: list[RawNote],
    group: list[int],
    fixed: dict[int, GuitarPosition],
    max_fret: int,
    max_fret_span: int,
    tolerate_unplayable: bool,
) -> list[tuple[float, tuple[GuitarPosition | None, ...]]]:
    candidates: list[list[GuitarPosition | None]] = []
    for index in group:
        if index in fixed:
            options: list[GuitarPosition | None] = [fixed[index]]
        else:
            options = list(possible_positions(notes[index].pitch, max_fret=max_fret))
        if tolerate_unplayable:
            options.append(None)
        candidates.append(options)
    if not tolerate_unplayable and any(not item for item in candidates):
        missing = [notes[index].pitch for index, item in zip(group, candidates) if not item]
        raise ValueError(f"Unplayable note(s) for standard guitar tuning: {missing}")

    scored: list[tuple[float, tuple[GuitarPosition | None, ...]]] = []
    for combo in product(*candidates):
        placed = [position for position in combo if position is not None]
        if len({position.string for position in placed}) != len(placed):
            continue
        fretted = [position.fret for position in placed if position.fret > 0]
        if fretted and max(fretted) - min(fretted) > max_fret_span:
            continue
        cost = DROP_COST * (len(combo) - len(placed))
        cost += sum(0.3 * fret + 1.5 * max(0, fret - COMFORT_FRET) for fret in fretted)
        if len(fretted) > 1:
            cost += 0.8 * (max(fretted) - min(fretted))
        scored.append((cost, combo))
    if not scored:
        raise ValueError("No playable fingering found within span/string constraints")
    scored.sort(key=lambda item: item[0])
    return scored[:OPTIONS_PER_GROUP]


def _transition_cost(
    combo: tuple[GuitarPosition | None, ...],
    group: list[int],
    notes: list[RawNote],
    hand: int | None,
    ringing: dict[int, tuple[float, int]],
    pitch_strings: dict[int, int],
    start: float,
) -> tuple[float, int | None]:
    cost = 0.0
    for index, position in zip(group, combo):
        if position is None:
            continue
        held = ringing.get(position.string)
        if held is not None and held[1] != position.fret:
            remaining = held[0] - start
            if remaining > RING_GRACE_SECONDS:
                cost += 3.0 + 6.0 * min(remaining, 1.0)
        previous_string = pitch_strings.get(notes[index].pitch)
        if previous_string is not None and previous_string != position.string:
            cost += 0.8

    fretted = [position.fret for position in combo if position is not None and position.fret > 0]
    if not fretted:
        return cost, hand
    low, high = min(fretted), max(fretted)
    if hand is None:
        return cost, low
    if hand <= low and high <= hand + HAND_SPAN:
        return cost, hand
    target = low if high - HAND_SPAN > low else min(max(hand, high - HAND_SPAN), low)
    return cost + 1.0 + 0.7 * abs(target - hand), target


GROUP_SECONDS = 0.04
BEAM_WIDTH = 64
COMBOS_PER_GROUP = 48
HAND_WIDTH = 3
MAX_SPAN = 4
COMFORT_FRET = 7
RING_GRACE_SECONDS = 0.05
RING_WEIGHT = 5.0
OPEN_STRING_COST = 0.6
OPEN_POSITION_LIMIT = 3


def plan_positions(
    notes: list[RawNote],
    *,
    tolerate_unplayable: bool = False,
    max_fret: int = 20,
    position: int | None = None,
    fixed: dict[int, GuitarPosition] | None = None,
    spec: Fretted = GUITAR_SPEC,
) -> list[GuitarPosition | None]:
    """Choose string/fret for every note over the whole song on spec's strings.

    Notes starting within GROUP_SECONDS are fingered together. A beam search keeps
    the hand in one position when possible, prefers low frets (or, with position, frets
    position..position+width, width being spec.hand_frets - 1), and avoids cutting strings
    that are still ringing. fixed maps note indexes to a position they must keep.
    """
    width = spec.hand_frets - 1
    order = sorted(range(len(notes)), key=lambda i: (notes[i].start_time, notes[i].pitch))
    groups: list[list[int]] = []
    for index in order:
        if groups and notes[index].start_time - notes[groups[-1][0]].start_time <= GROUP_SECONDS:
            groups[-1].append(index)
        else:
            groups.append([index])

    # (cost, hand, ringing {string: (end_time, pitch)}, path (previous_path, members, combo))
    beam: list[tuple[float, int | None, dict[int, tuple[float, int]], tuple | None]] = [(0.0, None, {}, None)]
    for group in groups:
        members, combos = _group_options(notes, group, tolerate_unplayable, max_fret, position, fixed, spec)
        if not members:
            continue
        start = min(notes[i].start_time for i in members)
        best: dict[tuple, tuple] = {}
        for cost, hand, ringing, path in beam:
            for static_cost, combo in combos:
                new_hand, move_cost = _move_hand(hand, [pos.fret for pos in combo if pos.fret > 0], width)
                total = cost + static_cost + move_cost
                for index, pos in zip(members, combo):
                    held = ringing.get(pos.string)
                    if held and held[1] != notes[index].pitch:
                        remaining = held[0] - start
                        if remaining > RING_GRACE_SECONDS:
                            total += RING_WEIGHT * min(remaining, 1.0)
                key = (new_hand, combo)
                if key in best and best[key][0] <= total:
                    continue
                next_ringing = {string: held for string, held in ringing.items() if held[0] > start}
                for index, pos in zip(members, combo):
                    next_ringing[pos.string] = (notes[index].end_time, notes[index].pitch)
                best[key] = (total, new_hand, next_ringing, (path, members, combo))
        beam = sorted(best.values(), key=lambda item: item[0])[:BEAM_WIDTH]

    result: list[GuitarPosition | None] = [None] * len(notes)
    path = beam[0][3]
    while path is not None:
        path, members, combo = path
        for index, pos in zip(members, combo):
            result[index] = pos
    return result


def _group_options(
    notes: list[RawNote],
    group: list[int],
    tolerate_unplayable: bool,
    max_fret: int,
    position: int | None = None,
    fixed: dict[int, GuitarPosition] | None = None,
    spec: Fretted = GUITAR_SPEC,
) -> tuple[list[int], list[tuple[float, tuple[GuitarPosition, ...]]]]:
    fixed = fixed or {}
    candidates = {i: [fixed[i]] if i in fixed else possible_positions(notes[i].pitch, max_fret=max_fret, spec=spec)
                  for i in group}
    missing = [notes[i].pitch for i in group if not candidates[i]]
    if missing and not tolerate_unplayable:
        raise ValueError(f"Unplayable note(s) for standard {spec.name} tuning: {missing}")
    members = sorted((i for i in group if candidates[i]), key=lambda i: -notes[i].velocity)
    if len(members) > spec.strings and not tolerate_unplayable:
        raise ValueError("No playable fingering found within span/string constraints")
    members = members[:spec.strings]
    while members:
        combos = [
            (_static_cost(combo, position, spec.hand_frets - 1), combo)
            for combo in product(*(candidates[i] for i in members))
            if _playable(combo)
        ]
        if combos:
            combos.sort(key=lambda item: item[0])
            return members, combos[:COMBOS_PER_GROUP]
        if not tolerate_unplayable:
            raise ValueError("No playable fingering found within span/string constraints")
        members = members[:-1]
    return [], []


def _playable(combo: tuple[GuitarPosition, ...]) -> bool:
    if len({pos.string for pos in combo}) != len(combo):
        return False
    fretted = [pos.fret for pos in combo if pos.fret > 0]
    return not fretted or max(fretted) - min(fretted) <= MAX_SPAN


def _static_cost(combo: tuple[GuitarPosition, ...], position: int | None = None, width: int = HAND_WIDTH) -> float:
    fretted = [pos.fret for pos in combo if pos.fret > 0]
    opens = (len(combo) - len(fretted)) * OPEN_STRING_COST if position and position >= OPEN_POSITION_LIMIT else 0.0
    if not fretted:
        return opens
    if position:
        outside = lambda fret: max(0, position - fret, fret - position - width)
        height = sum(0.3 * abs(fret - position - 1) + 2.0 * outside(fret) for fret in fretted) + opens
    else:
        height = sum(0.3 * fret + 2.0 * max(0, fret - COMFORT_FRET) for fret in fretted)
    stretch = 3.0 * max(0, max(fretted) - min(fretted) - width)
    return height + stretch


def _move_hand(hand: int | None, fretted: list[int], width: int = HAND_WIDTH) -> tuple[int | None, float]:
    if not fretted:
        return hand, 0.0
    low, high = min(fretted), max(fretted)
    if hand is None:
        return low, 0.0
    if low < hand:
        new_hand = low
    elif high > hand + width:
        new_hand = high - width
    else:
        new_hand = hand
    shift = abs(new_hand - hand)
    return new_hand, (1.5 + shift) if shift else 0.0
