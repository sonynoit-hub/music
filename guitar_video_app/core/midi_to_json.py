from __future__ import annotations

import json
from pathlib import Path

from guitar_video_app.core.schema import RawNote, RawSong, TempoEvent, dataclass_to_json


def midi_to_raw_song(midi_path: str | Path) -> RawSong:
    try:
        import mido
    except ImportError as exc:
        raise RuntimeError("Install mido to parse MIDI files: python -m pip install mido") from exc

    mid = mido.MidiFile(midi_path)
    ticks_per_beat = mid.ticks_per_beat
    tempo = 500000
    bpm = 120.0
    current_time = 0.0
    active: dict[tuple[int, int], tuple[float, int, int | None]] = {}
    notes: list[RawNote] = []
    tempo_events: list[TempoEvent] = []
    time_signature: tuple[int, int] | None = None

    merged = mido.merge_tracks(mid.tracks)
    for msg in merged:
        current_time += mido.tick2second(msg.time, ticks_per_beat, tempo)
        if msg.type == "set_tempo":
            tempo = msg.tempo
            bpm = mido.tempo2bpm(tempo)
            beat = mido.second2tick(current_time, ticks_per_beat, tempo) / ticks_per_beat
            tempo_events.append(TempoEvent(time=current_time, beat=beat, bpm=float(bpm)))
        elif msg.type == "time_signature":
            time_signature = (msg.numerator, msg.denominator)
        elif msg.type == "note_on" and msg.velocity > 0:
            active[(msg.channel, msg.note)] = (current_time, msg.velocity, msg.channel)
        elif msg.type in {"note_off", "note_on"}:
            key = (msg.channel, msg.note)
            if key in active:
                start, velocity, channel = active.pop(key)
                notes.append(RawNote(msg.note, start, current_time, velocity, channel))

    return RawSong(
        source=str(midi_path),
        bpm=float(bpm),
        ticks_per_beat=ticks_per_beat,
        notes=notes,
        tempo_events=tempo_events,
        time_signature=time_signature,
    )


def write_raw_json(midi_path: str | Path, json_path: str | Path) -> None:
    song = midi_to_raw_song(midi_path)
    Path(json_path).write_text(json.dumps(dataclass_to_json(song), indent=2), encoding="utf-8")
