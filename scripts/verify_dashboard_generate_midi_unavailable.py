from __future__ import annotations

import asyncio
from io import BytesIO
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    with tempfile.TemporaryDirectory() as store:
        os.environ["GUITAR_DASHBOARD_STORE"] = store
        from fastapi import HTTPException, UploadFile
        from guitar_video_app.api.dashboard import SongInput, create, generate_midi, upload

        created = create(SongInput(name="Generate MIDI unavailable test"))
        song_id = created["id"]
        wav_path = ROOT / "outputs" / "complex_32_measures.wav"
        wav_file = UploadFile(BytesIO(wav_path.read_bytes()), filename=wav_path.name)
        asyncio.run(upload(song_id, "wav", wav_file))

        try:
            generate_midi(song_id)
        except HTTPException as exc:
            assert exc.status_code in (501, 500)
            assert "Basic Pitch" in str(exc.detail) or "MIDI generation failed" in str(exc.detail)
        else:
            raise AssertionError("Expected missing Basic Pitch to prevent local transcription")

        print("PASS: dashboard reports local transcription setup requirement.")


if __name__ == "__main__":
    main()
