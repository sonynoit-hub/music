"""Guitar mapper: string and fret for every note of an analyzed MIDI song.

MIDI -> music.analyzer -> this mapper -> normalized JSON. A track named "... string N ..." puts its
notes on string N when the fret is playable; the other notes are planned by the fingering solver.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re

from guitar_video_app.instruments.guitar.fingering_solver import plan_positions
from guitar_video_app.instruments.guitar.schema import GuitarPosition
from guitar_video_app.instruments.guitar.tuning import MAX_FRET, STANDARD_TUNING
from guitar_video_app.music.analyzer import analyze_midi_file
from guitar_video_app.music.normalized_song import NormalizedNote, NormalizedSong, NormalizedTrack
from guitar_video_app.music.schema import RawNote


def normalize_midi_file(
    midi_path: str | Path,
    *,
    wav_path: str | Path | None = None,
    audio_offset: float = 0.0,
    title: str | None = None,
    tolerate_unplayable: bool = False,
) -> NormalizedSong:
    song = analyze_midi_file(midi_path, wav_path=wav_path, audio_offset=audio_offset, title=title)
    return map_song(song, tolerate_unplayable=tolerate_unplayable)


def map_song(song: NormalizedSong, *, tolerate_unplayable: bool = False) -> NormalizedSong:
    """The song with string and fret on every note the guitar can play; unplayable notes raise
    ValueError unless tolerate_unplayable, which leaves them unmapped."""
    positions = _map_positions(song.notes, song.tracks, tolerate_unplayable=tolerate_unplayable)
    notes = [replace(note, string=positions[index].string, fret=positions[index].fret)
             if positions.get(index) is not None else note
             for index, note in enumerate(song.notes)]
    return replace(song, notes=notes,
                   guitar={"tuning": STANDARD_TUNING, "strings": sorted(STANDARD_TUNING.keys())})


def _map_positions(
    notes: list[NormalizedNote],
    tracks: list[NormalizedTrack],
    *,
    tolerate_unplayable: bool = False,
) -> dict[int, GuitarPosition | None]:
    positions: dict[int, GuitarPosition | None] = {}
    track_strings = _track_string_map(tracks)
    planned: list[int] = []
    for index, note in enumerate(notes):
        position = _position_from_track(note, track_strings)
        if position is None:
            planned.append(index)
        else:
            positions[index] = position

    raw_notes = [
        RawNote(
            pitch=notes[index].pitch,
            start_time=notes[index].start_seconds,
            end_time=notes[index].end_seconds,
            velocity=notes[index].velocity,
            channel=notes[index].channel,
        )
        for index in planned
    ]
    chosen = plan_positions(raw_notes, tolerate_unplayable=tolerate_unplayable)
    for index, position in zip(planned, chosen, strict=True):
        positions[index] = position
    return positions


def _track_string_map(tracks: list[NormalizedTrack]) -> dict[int, int]:
    result: dict[int, int] = {}
    for track in tracks:
        match = re.search(r"\bstring\s+([1-6])\b", track.name, flags=re.IGNORECASE)
        if match:
            result[track.id] = int(match.group(1))
    return result


def _position_from_track(note: NormalizedNote, track_strings: dict[int, int]) -> GuitarPosition | None:
    string = track_strings.get(note.track_id)
    if string is None:
        return None
    fret = note.pitch - STANDARD_TUNING[string]
    if not 0 <= fret <= MAX_FRET:
        return None
    return GuitarPosition(string=string, fret=fret)
