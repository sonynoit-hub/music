from __future__ import annotations

import asyncio
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import mido

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    with tempfile.TemporaryDirectory() as store:
        os.environ["GUITAR_DASHBOARD_STORE"] = store
        from fastapi import UploadFile
        from guitar_video_app.api.dashboard import SongInput, TabNoteEdit, create, lesson, update_note, upload
        from guitar_video_app.core.lesson_v2 import prepare

        created = create(SongInput(name="MIDI first import test"))
        song_id = created["id"]

        midi_path = ROOT / "outputs" / "complex_32_measures.mid"
        midi_file = UploadFile(BytesIO(midi_path.read_bytes()), filename=midi_path.name)
        row = asyncio.run(upload(song_id, "midi", midi_file))
        assert row["midi_name"] == midi_path.name
        assert row["json_name"].endswith(".json")
        assert row["summary"]["source_format"] == "midi"
        assert row["summary"]["music_layer"]["format"] == "midi"
        assert row["summary"]["music_layer"]["tracks"] == 7
        assert row["summary"]["music_layer"]["beats"] == 128

        stored = json.loads(lesson(song_id).body)
        assert stored["version"] == 3
        assert len(stored["music"]["notes"]) == len(stored["parts"]["guitar"]["positions"]) == 206
        lesson_data = json.loads(lesson(song_id, part="guitar").body)
        prepared = prepare(lesson_data)
        assert lesson_data["version"] == 2
        assert len(prepared["notes"]) == 206
        first_note = lesson_data["notes"][0]
        edited = update_note(song_id, TabNoteEdit(note_id=first_note["id"], string=2, fret=7))
        assert edited["revision"] == row["revision"] + 1
        edited_lesson = json.loads(lesson(song_id, part="guitar").body)
        edited_note = next(note for note in edited_lesson["notes"] if note["id"] == first_note["id"])
        assert edited_note["string"] == 2
        assert edited_note["fret"] == 7
        edited_music = json.loads(lesson(song_id).body)["music"]
        assert next(note for note in edited_music["notes"] if note["id"] == first_note["id"])["pitch"] == 59 + 7

        wav_path = ROOT / "outputs" / "complex_32_measures.wav"
        wav_file = UploadFile(BytesIO(wav_path.read_bytes()), filename=wav_path.name)
        row = asyncio.run(upload(song_id, "wav", wav_file))
        assert row["wav_name"] == wav_path.name
        assert row["json_name"]
        assert row["summary"]["source_format"] == "midi"

        replacement_wav = ROOT / "data" / "dashboard" / "complex-32-measures" / "audio.wav"
        wav_file = UploadFile(BytesIO(replacement_wav.read_bytes()), filename="replacement.wav")
        row = asyncio.run(upload(song_id, "wav", wav_file))
        assert row["wav_name"] == "replacement.wav"
        assert row["midi_name"] is None
        assert row["json_name"] is None
        assert row["summary"] is None

        repeated_tempo_path = Path(store) / "repeated-tempo.mid"
        _write_repeated_tempo_midi(repeated_tempo_path)
        repeated = create(SongInput(name="Repeated tempo MIDI test"))
        midi_file = UploadFile(BytesIO(repeated_tempo_path.read_bytes()), filename=repeated_tempo_path.name)
        row = asyncio.run(upload(repeated["id"], "midi", midi_file))
        assert row["summary"]["source_format"] == "midi"
        assert row["summary"]["music_layer"]["tempo_changes"] == 1

        dense_path = Path(store) / "dense-unplayable.mid"
        _write_dense_unplayable_midi(dense_path)
        dense = create(SongInput(name="Dense MIDI tolerant import test"))
        midi_file = UploadFile(BytesIO(dense_path.read_bytes()), filename=dense_path.name)
        row = asyncio.run(upload(dense["id"], "midi", midi_file))
        assert row["summary"]["source_format"] == "midi"
        assert row["summary"]["mapping_mode"] == "tolerant"
        assert row["summary"]["notes"] > 0

        # Delete: the song leaves the library and its folder moves to the store's trash with its row.
        from guitar_video_app.api.dashboard import HTTPException, delete_song, song, songs
        reply = delete_song(song_id)
        trash = Path(reply["trash"])
        assert trash.parent == Path(store) / "trash" and not (Path(store) / song_id).exists()
        assert any(trash.glob("*.wav")), list(trash.iterdir())
        assert json.loads((trash / "song.json").read_text())["name"] == "MIDI first import test"
        assert song_id not in [s["id"] for s in songs()]
        try:
            song(song_id)
            raise AssertionError("a deleted song is gone")
        except HTTPException as exc:
            assert exc.status_code == 404
        assert Path(delete_song(repeated["id"])["trash"]).name.startswith(repeated["id"])

        print("PASS: dashboard imports MIDI first, creates lesson JSON, then accepts WAV; deleting a song moves it to the trash.")


def _write_repeated_tempo_midi(path: Path) -> None:
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    tempo = mido.bpm2tempo(120)
    track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=480))
    track.append(mido.Message("program_change", program=24, channel=0, time=0))
    track.append(mido.Message("note_on", note=64, velocity=80, channel=0, time=0))
    track.append(mido.Message("note_off", note=64, velocity=0, channel=0, time=480))
    track.append(mido.MetaMessage("end_of_track", time=0))
    midi.save(path)


def _write_dense_unplayable_midi(path: Path) -> None:
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    track.append(mido.Message("program_change", program=24, channel=0, time=0))
    for index, pitch in enumerate([40, 52, 64, 76, 88, 100, 112]):
        track.append(mido.Message("note_on", note=pitch, velocity=80, channel=0, time=0 if index else 0))
    for index, pitch in enumerate([40, 52, 64, 76, 88, 100, 112]):
        track.append(mido.Message("note_off", note=pitch, velocity=0, channel=0, time=480 if index == 0 else 0))
    track.append(mido.MetaMessage("end_of_track", time=0))
    midi.save(path)


if __name__ == "__main__":
    main()
