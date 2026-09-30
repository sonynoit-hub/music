"""Guitar lessons from normalized song JSON whose notes carry string and fret (instruments.guitar.mapper)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from guitar_video_app.instruments.guitar.view import PART, guitar_view, new_part
from guitar_video_app.music.normalized import load_normalized_song, normalized_to_lesson, note_id


def _mapped(note: dict[str, Any]) -> bool:
    return note.get("string") is not None and note.get("fret") is not None


def lesson_from_normalized(
    normalized: dict[str, Any],
    *,
    fps: int = 60,
    name: str | None = None,
    skip_unmapped: bool = False,
) -> dict[str, Any]:
    """A V3 lesson with a guitar part. A note without string and fret raises ValueError, or with
    skip_unmapped is left out of the lesson."""
    if not skip_unmapped:
        for index, note in enumerate(normalized.get("notes", []), start=1):
            if not _mapped(note):
                raise ValueError(f"Normalized note {note.get('id', index)} is missing guitar mapping.")
    lesson = normalized_to_lesson(normalized, fps=fps, name=name, keep=_mapped)
    part = new_part()
    for index, note in enumerate(normalized["notes"], start=1):
        if _mapped(note):
            part["positions"][note_id(note, index)] = dict(string=int(note["string"]), fret=int(note["fret"]))
    lesson["parts"][PART] = part
    return lesson


def normalized_to_lesson_v2(normalized: dict[str, Any], *, fps: int = 60, name: str | None = None,
                            skip_unmapped: bool = False) -> dict[str, Any]:
    return guitar_view(lesson_from_normalized(normalized, fps=fps, name=name, skip_unmapped=skip_unmapped))


def convert_normalized_file_to_lesson_v2(
    input_path: str | Path,
    output_path: str | Path,
    *,
    fps: int = 60,
    name: str | None = None,
) -> dict[str, Any]:
    lesson = normalized_to_lesson_v2(load_normalized_song(input_path), fps=fps, name=name)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lesson, indent=2) + "\n", encoding="utf-8")
    return lesson
