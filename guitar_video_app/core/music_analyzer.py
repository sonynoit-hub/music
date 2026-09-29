from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import re

import mido

from guitar_video_app.core.fingering_solver import choose_positions
from guitar_video_app.core.normalized_song import (
    SCHEMA_VERSION,
    NormalizedBeat,
    NormalizedMeasure,
    NormalizedNote,
    NormalizedSong,
    NormalizedTrack,
    TempoChange,
    TimeSignatureChange,
)
from guitar_video_app.core.note_mapping import STANDARD_TUNING
from guitar_video_app.core.schema import RawNote


DEFAULT_TEMPO = 500_000
DEFAULT_TIME_SIGNATURE = (4, 4)


@dataclass(frozen=True)
class ParsedMidiNote:
    track_id: int
    pitch: int
    start_tick: int
    end_tick: int
    velocity: int
    channel: int | None


@dataclass(frozen=True)
class ParsedMidi:
    source_midi: str
    ppq: int
    tracks: list[NormalizedTrack]
    notes: list[ParsedMidiNote]
    tempo_changes: list[tuple[int, int]]
    time_signature_changes: list[tuple[int, int, int]]
    end_tick: int


@dataclass(frozen=True)
class _TempoSegment:
    tick: int
    seconds: float
    microseconds_per_quarter: int


def normalize_midi_file(
    midi_path: str | Path,
    *,
    wav_path: str | Path | None = None,
    audio_offset: float = 0.0,
    title: str | None = None,
    tolerate_unplayable: bool = False,
) -> NormalizedSong:
    parsed = parse_midi_facts(midi_path)
    tempo_map = _build_tempo_map(parsed.ppq, parsed.tempo_changes)
    time_signatures = _time_signature_events(parsed.time_signature_changes)
    tick_to_seconds = _make_tick_to_seconds(parsed.ppq, tempo_map)
    duration_seconds = tick_to_seconds(parsed.end_tick)

    measures = _build_measures(
        parsed.ppq,
        parsed.end_tick,
        time_signatures,
        tick_to_seconds,
    )
    beats = _build_beats(
        parsed.ppq,
        parsed.end_tick,
        time_signatures,
        measures,
        tick_to_seconds,
    )
    notes = _build_notes(
        parsed.notes,
        parsed.tracks,
        parsed.ppq,
        measures,
        tick_to_seconds,
        tolerate_unplayable=tolerate_unplayable,
    )

    source_wav = str(wav_path) if wav_path is not None else None
    return NormalizedSong(
        schema_version=SCHEMA_VERSION,
        song={
            "title": title or Path(midi_path).stem,
            "source_midi": str(midi_path),
            "source_wav": source_wav,
            "duration_seconds": duration_seconds,
        },
        timing={
            "ppq": parsed.ppq,
            "tempo_changes": [
                {
                    "tick": event.tick,
                    "seconds": event.seconds,
                    "bpm": event.bpm,
                    "microseconds_per_quarter": event.microseconds_per_quarter,
                }
                for event in _tempo_events_for_json(tempo_map)
            ],
            "time_signature_changes": [
                {
                    "tick": event.tick,
                    "seconds": tick_to_seconds(event.tick),
                    "numerator": event.numerator,
                    "denominator": event.denominator,
                }
                for event in time_signatures
            ],
        },
        tracks=parsed.tracks,
        notes=notes,
        measures=measures,
        beats=beats,
        audio={
            "file": source_wav,
            "audio_offset": audio_offset,
        },
        guitar={
            "tuning": STANDARD_TUNING,
            "strings": sorted(STANDARD_TUNING.keys()),
        },
    )


def parse_midi_facts(midi_path: str | Path) -> ParsedMidi:
    path = Path(midi_path)
    mid = mido.MidiFile(path)
    tempo_changes: list[tuple[int, int]] = []
    time_signature_changes: list[tuple[int, int, int]] = []
    notes: list[ParsedMidiNote] = []
    tracks: list[NormalizedTrack] = []
    end_tick = 0

    for track_id, track in enumerate(mid.tracks):
        absolute_tick = 0
        track_name = f"Track {track_id}"
        channel: int | None = None
        instrument: int | None = None
        active: dict[tuple[int | None, int], tuple[int, int]] = {}

        for message in track:
            absolute_tick += int(message.time)
            end_tick = max(end_tick, absolute_tick)

            if message.type == "track_name":
                track_name = message.name
            elif message.type == "set_tempo":
                tempo_changes.append((absolute_tick, int(message.tempo)))
            elif message.type == "time_signature":
                time_signature_changes.append(
                    (absolute_tick, int(message.numerator), int(message.denominator))
                )
            elif hasattr(message, "channel"):
                channel = int(message.channel)
                if message.type == "program_change":
                    instrument = int(message.program)

            if message.type == "note_on" and message.velocity > 0:
                active[(getattr(message, "channel", None), int(message.note))] = (
                    absolute_tick,
                    int(message.velocity),
                )
            elif message.type in {"note_off", "note_on"}:
                note_channel = getattr(message, "channel", None)
                key = (note_channel, int(message.note))
                started = active.pop(key, None)
                if started is not None and absolute_tick > started[0]:
                    notes.append(
                        ParsedMidiNote(
                            track_id=track_id,
                            pitch=int(message.note),
                            start_tick=started[0],
                            end_tick=absolute_tick,
                            velocity=started[1],
                            channel=int(note_channel) if note_channel is not None else None,
                        )
                    )

        for (note_channel, pitch), (start_tick, velocity) in active.items():
            if absolute_tick > start_tick:
                notes.append(
                    ParsedMidiNote(
                        track_id=track_id,
                        pitch=pitch,
                        start_tick=start_tick,
                        end_tick=absolute_tick,
                        velocity=velocity,
                        channel=int(note_channel) if note_channel is not None else None,
                    )
                )

        tracks.append(
            NormalizedTrack(
                id=track_id,
                name=track_name,
                channel=channel,
                instrument=instrument,
            )
        )

    note_end_tick = max((note.end_tick for note in notes), default=0)
    return ParsedMidi(
        source_midi=str(path),
        ppq=int(mid.ticks_per_beat),
        tracks=tracks,
        notes=sorted(notes, key=lambda note: (note.start_tick, note.end_tick, note.pitch)),
        tempo_changes=sorted(set(tempo_changes)),
        time_signature_changes=sorted(set(time_signature_changes)),
        end_tick=max(end_tick, note_end_tick),
    )


def _build_tempo_map(
    ppq: int, tempo_changes: list[tuple[int, int]]
) -> list[_TempoSegment]:
    events = sorted(tempo_changes)
    if not events or events[0][0] != 0:
        events.insert(0, (0, DEFAULT_TEMPO))

    segments: list[_TempoSegment] = []
    current_tick = 0
    current_seconds = 0.0
    current_tempo = events[0][1]
    for tick, tempo in events:
        if tick > current_tick:
            current_seconds += mido.tick2second(tick - current_tick, ppq, current_tempo)
        segments.append(
            _TempoSegment(
                tick=tick,
                seconds=current_seconds,
                microseconds_per_quarter=tempo,
            )
        )
        current_tick = tick
        current_tempo = tempo

    deduped: list[_TempoSegment] = []
    for segment in segments:
        if deduped and deduped[-1].tick == segment.tick:
            deduped[-1] = segment
        elif (
            deduped
            and deduped[-1].microseconds_per_quarter == segment.microseconds_per_quarter
        ):
            continue
        else:
            deduped.append(segment)
    return deduped


def _make_tick_to_seconds(ppq: int, tempo_map: list[_TempoSegment]):
    ticks = [segment.tick for segment in tempo_map]

    def tick_to_seconds(tick: int) -> float:
        index = bisect_right(ticks, tick) - 1
        segment = tempo_map[max(index, 0)]
        return segment.seconds + mido.tick2second(
            tick - segment.tick,
            ppq,
            segment.microseconds_per_quarter,
        )

    return tick_to_seconds


def _tempo_events_for_json(tempo_map: list[_TempoSegment]) -> list[TempoChange]:
    return [
        TempoChange(
            tick=segment.tick,
            seconds=segment.seconds,
            bpm=mido.tempo2bpm(segment.microseconds_per_quarter),
            microseconds_per_quarter=segment.microseconds_per_quarter,
        )
        for segment in tempo_map
    ]


def _time_signature_events(
    time_signature_changes: list[tuple[int, int, int]]
) -> list[TimeSignatureChange]:
    events = sorted(time_signature_changes)
    if not events or events[0][0] != 0:
        events.insert(0, (0, *DEFAULT_TIME_SIGNATURE))
    result: list[TimeSignatureChange] = []
    for tick, numerator, denominator in events:
        if (
            result
            and result[-1].numerator == numerator
            and result[-1].denominator == denominator
        ):
            continue
        result.append(
            TimeSignatureChange(
                tick=tick,
                seconds=0.0,
                numerator=numerator,
                denominator=denominator,
            )
        )
    return result


def _build_measures(
    ppq: int,
    end_tick: int,
    time_signatures: list[TimeSignatureChange],
    tick_to_seconds,
) -> list[NormalizedMeasure]:
    measures: list[NormalizedMeasure] = []
    measure_number = 1
    signature_bounds = [
        (event, time_signatures[index + 1].tick if index + 1 < len(time_signatures) else end_tick)
        for index, event in enumerate(time_signatures)
    ]

    for event, segment_end_tick in signature_bounds:
        beat_unit_ticks = Fraction(ppq * 4, event.denominator)
        measure_ticks = beat_unit_ticks * event.numerator
        cursor = Fraction(event.tick, 1)
        segment_end = Fraction(max(segment_end_tick, event.tick), 1)
        while cursor < segment_end:
            next_cursor = min(cursor + measure_ticks, segment_end)
            start_tick = _fraction_to_tick(cursor)
            measure_end_tick = _fraction_to_tick(next_cursor)
            if measure_end_tick <= start_tick:
                break
            measures.append(
                NormalizedMeasure(
                    number=measure_number,
                    start_tick=start_tick,
                    end_tick=measure_end_tick,
                    start_seconds=tick_to_seconds(start_tick),
                    end_seconds=tick_to_seconds(measure_end_tick),
                    time_signature=f"{event.numerator}/{event.denominator}",
                )
            )
            measure_number += 1
            cursor = next_cursor

    if not measures:
        measures.append(
            NormalizedMeasure(
                number=1,
                start_tick=0,
                end_tick=end_tick,
                start_seconds=0.0,
                end_seconds=tick_to_seconds(end_tick),
                time_signature=f"{DEFAULT_TIME_SIGNATURE[0]}/{DEFAULT_TIME_SIGNATURE[1]}",
            )
        )
    return measures


def _build_beats(
    ppq: int,
    end_tick: int,
    time_signatures: list[TimeSignatureChange],
    measures: list[NormalizedMeasure],
    tick_to_seconds,
) -> list[NormalizedBeat]:
    beats: list[NormalizedBeat] = []
    beat_index = 0
    for measure in measures:
        numerator, denominator = (int(part) for part in measure.time_signature.split("/"))
        beat_unit_ticks = Fraction(ppq * 4, denominator)
        cursor = Fraction(measure.start_tick, 1)
        for beat_in_measure in range(1, numerator + 1):
            tick = _fraction_to_tick(cursor)
            if tick >= end_tick and end_tick > 0:
                break
            beats.append(
                NormalizedBeat(
                    index=beat_index,
                    measure=measure.number,
                    beat_in_measure=beat_in_measure,
                    tick=tick,
                    seconds=tick_to_seconds(tick),
                )
            )
            beat_index += 1
            cursor += beat_unit_ticks
    return beats


def _build_notes(
    parsed_notes: list[ParsedMidiNote],
    tracks: list[NormalizedTrack],
    ppq: int,
    measures: list[NormalizedMeasure],
    tick_to_seconds,
    *,
    tolerate_unplayable: bool = False,
) -> list[NormalizedNote]:
    mapped_positions = _map_guitar_positions(
        parsed_notes,
        tracks,
        tick_to_seconds,
        tolerate_unplayable=tolerate_unplayable,
    )
    normalized: list[NormalizedNote] = []
    for index, note in enumerate(parsed_notes, start=1):
        start_seconds = tick_to_seconds(note.start_tick)
        end_seconds = tick_to_seconds(note.end_tick)
        position = mapped_positions.get(id(note))
        normalized.append(
            NormalizedNote(
                id=f"n{index:04d}",
                track_id=note.track_id,
                pitch=note.pitch,
                start_tick=note.start_tick,
                end_tick=note.end_tick,
                duration_ticks=note.end_tick - note.start_tick,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                duration_seconds=end_seconds - start_seconds,
                start_beat=note.start_tick / ppq,
                end_beat=note.end_tick / ppq,
                measure=_measure_for_tick(note.start_tick, measures),
                velocity=note.velocity,
                channel=note.channel,
                string=position.string if position is not None else None,
                fret=position.fret if position is not None else None,
            )
        )
    return normalized


def _map_guitar_positions(
    parsed_notes: list[ParsedMidiNote],
    tracks: list[NormalizedTrack],
    tick_to_seconds,
    *,
    tolerate_unplayable: bool = False,
) -> dict[int, object]:
    positions: dict[int, object] = {}
    track_strings = _track_string_map(tracks)
    previous = None
    index = 0
    while index < len(parsed_notes):
        start_tick = parsed_notes[index].start_tick
        group: list[ParsedMidiNote] = []
        while index < len(parsed_notes) and parsed_notes[index].start_tick == start_tick:
            group.append(parsed_notes[index])
            index += 1

        explicit_positions = [_position_from_track(note, track_strings) for note in group]
        if all(position is not None for position in explicit_positions):
            chosen = explicit_positions
            for note, position in zip(group, chosen, strict=True):
                positions[id(note)] = position
            previous = list(chosen)
            continue

        raw_group = [
            RawNote(
                pitch=note.pitch,
                start_time=tick_to_seconds(note.start_tick),
                end_time=tick_to_seconds(note.end_tick),
                velocity=note.velocity,
                channel=note.channel,
            )
            for note in group
        ]
        try:
            chosen = choose_positions(raw_group, previous=previous)
        except ValueError:
            if not tolerate_unplayable:
                raise
            chosen = _choose_tolerant_positions(group, raw_group, previous)
        for note, position in zip(group, chosen, strict=True):
            if position is not None:
                positions[id(note)] = position
        if chosen:
            previous = [position for position in chosen if position is not None]
    return positions


def _choose_tolerant_positions(
    group: list[ParsedMidiNote],
    raw_group: list[RawNote],
    previous: list[object] | None,
) -> list[object | None]:
    chosen: list[object | None] = []
    used_strings: set[int] = set()
    current_previous = previous
    for note, raw_note in zip(group, raw_group, strict=True):
        try:
            options = choose_positions([raw_note], previous=current_previous)
        except ValueError:
            chosen.append(None)
            continue
        position = options[0]
        if position.string in used_strings:
            chosen.append(None)
            continue
        chosen.append(position)
        used_strings.add(position.string)
        current_previous = [position]
    return chosen


def _track_string_map(tracks: list[NormalizedTrack]) -> dict[int, int]:
    result: dict[int, int] = {}
    for track in tracks:
        match = re.search(r"\bstring\s+([1-6])\b", track.name, flags=re.IGNORECASE)
        if match:
            result[track.id] = int(match.group(1))
    return result


def _position_from_track(note: ParsedMidiNote, track_strings: dict[int, int]):
    string = track_strings.get(note.track_id)
    if string is None:
        return None
    fret = note.pitch - STANDARD_TUNING[string]
    if not 0 <= fret <= 20:
        return None
    from guitar_video_app.core.schema import GuitarPosition

    return GuitarPosition(string=string, fret=fret)


def _measure_for_tick(tick: int, measures: list[NormalizedMeasure]) -> int:
    for measure in measures:
        if measure.start_tick <= tick < measure.end_tick:
            return measure.number
    return measures[-1].number


def _fraction_to_tick(value: Fraction) -> int:
    return int(value) if value.denominator == 1 else round(float(value))
