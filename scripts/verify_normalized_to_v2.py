from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from guitar_video_app.core.lesson_v2 import prepare
from guitar_video_app.core.normalized_to_lesson_v2 import convert_normalized_file_to_lesson_v2


INPUT_PATH = ROOT / "outputs" / "complex_32_measures.normalized.json"
OUTPUT_PATH = ROOT / "outputs" / "complex_32_measures.v2.json"
REFERENCE_PATH = ROOT / "data" / "lesson_tests" / "12_complex_32_measures.json"


def main() -> None:
    lesson = convert_normalized_file_to_lesson_v2(
        INPUT_PATH,
        OUTPUT_PATH,
        fps=60,
        name="Complex 32 Measures From Normalized JSON",
    )
    prepared = prepare(lesson)
    data = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    reference_prepared = prepare(reference)

    assert data["version"] == 2
    assert data["tempo_bpm"] == 90
    assert data["time_signature"] == [4, 4]
    assert data["end_beat"] == 128
    assert len(data["notes"]) == 206
    assert prepared["frame_end"] == 5120
    assert data["source"]["source_wav"].endswith("complex_32_measures.wav")
    assert data["source"]["audio_offset"] == 0.0

    for note in data["notes"]:
        assert 1 <= note["string"] <= 6
        assert 0 <= note["fret"] <= 20

    assert _prepared_note_keys(prepared) == _prepared_note_keys(reference_prepared)

    print(
        "PASS: normalized JSON converts to valid V2 lesson JSON "
        "with 206 notes, 90 BPM, 4/4, 128 beats, and matching prepared playback."
    )
    print(OUTPUT_PATH)


def _prepared_note_keys(prepared: dict) -> list[tuple]:
    return sorted(
        (note["string"], note["fret"], note["start"], note["end"])
        for note in prepared["notes"]
    )


if __name__ == "__main__":
    main()
