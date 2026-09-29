from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from guitar_video_app.core.music_analyzer import normalize_midi_file
from guitar_video_app.core.normalized_song import write_normalized_song

MIDI_PATH = ROOT / "outputs" / "complex_32_measures.mid"
WAV_PATH = ROOT / "outputs" / "complex_32_measures.wav"
OUTPUT_PATH = ROOT / "outputs" / "complex_32_measures.normalized.json"


def main() -> None:
    song = normalize_midi_file(
        MIDI_PATH,
        wav_path=WAV_PATH,
        audio_offset=0.0,
        title="Complex 32 Measures",
    )
    write_normalized_song(song, OUTPUT_PATH)
    data = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))

    assert data["schema_version"] == "1.0"
    assert data["timing"]["ppq"] > 0
    assert data["timing"]["tempo_changes"]
    assert data["timing"]["time_signature_changes"]
    assert data["song"]["source_midi"] == str(MIDI_PATH)
    assert data["song"]["source_wav"] == str(WAV_PATH)
    assert data["audio"]["file"] == str(WAV_PATH)
    assert data["audio"]["audio_offset"] == 0.0

    notes = data["notes"]
    measures = data["measures"]
    beats = data["beats"]
    assert len(notes) == 206, f"expected 206 notes, got {len(notes)}"
    assert len(measures) == 32, f"expected 32 measures, got {len(measures)}"
    assert len(beats) == 128, f"expected 128 beats, got {len(beats)}"
    assert abs(data["song"]["duration_seconds"] - 85.3333333333) < 0.001

    previous_start_tick = -1
    for note in notes:
        assert note["start_tick"] >= previous_start_tick
        assert note["end_tick"] > note["start_tick"]
        assert note["duration_ticks"] == note["end_tick"] - note["start_tick"]
        assert note["end_seconds"] > note["start_seconds"]
        assert note["duration_seconds"] == note["end_seconds"] - note["start_seconds"]
        assert 1 <= note["measure"] <= 32
        assert 1 <= note["string"] <= 6
        assert 0 <= note["fret"] <= 20
        previous_start_tick = note["start_tick"]

    first_measure = measures[0]
    last_measure = measures[-1]
    assert first_measure["number"] == 1
    assert first_measure["start_tick"] == 0
    assert last_measure["number"] == 32
    assert last_measure["end_tick"] > last_measure["start_tick"]

    print(
        "PASS: normalized song JSON includes 206 notes, 32 measures, "
        "128 beats, tick timing, seconds timing, guitar mapping, and WAV sync."
    )
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
