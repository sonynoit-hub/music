from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import asyncio
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    with tempfile.TemporaryDirectory() as store:
        os.environ["GUITAR_DASHBOARD_STORE"] = store
        from fastapi import UploadFile
        from guitar_video_app.api.dashboard import SongInput, create, lesson, upload
        from guitar_video_app.core.lesson_v2 import prepare

        created = create(SongInput(name="Normalized import test"))
        song_id = created["id"]

        normalized_path = ROOT / "outputs" / "complex_32_measures.normalized.json"
        upload_file = UploadFile(
            BytesIO(normalized_path.read_bytes()),
            filename="complex_32_measures.normalized.json",
        )
        row = asyncio.run(upload(song_id, "json", upload_file))
        assert row["summary"]["source_format"] == "normalized"
        assert row["summary"]["notes"] == 206
        assert row["summary"]["measures"] == 32
        assert row["summary"]["music_layer"]["format"] == "normalized"
        assert row["summary"]["music_layer"]["tracks"] == 7
        assert row["summary"]["music_layer"]["beats"] == 128
        assert row["summary"]["music_layer"]["tempo_changes"] == 1
        assert row["summary"]["music_layer"]["time_signature_changes"] == 1

        stored = json.loads(lesson(song_id).body)
        assert stored["version"] == 3
        assert stored["music"]["source"]["normalized_schema_version"] == "1.0"
        lesson_data = json.loads(lesson(song_id, part="guitar").body)
        assert lesson_data["version"] == 2
        assert lesson_data["source"]["normalized_schema_version"] == "1.0"
        assert len(prepare(lesson_data)["notes"]) == 206

        print("PASS: dashboard imports normalized JSON and stores a V3 lesson with a valid guitar view.")


if __name__ == "__main__":
    main()
