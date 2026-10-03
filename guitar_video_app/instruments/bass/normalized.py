"""Bass lessons from normalized song JSON (music.analyzer output): the music layer, then strings and frets
planned by the bass (Bass.assign). Guitar string/fret mapping in the file is not used."""
from __future__ import annotations

from typing import Any

from guitar_video_app.instruments.bass import BASS
from guitar_video_app.music.normalized import normalized_to_lesson


def lesson_from_normalized(normalized: dict[str, Any], *, fps: int = 60, name: str | None = None,
                           skip_unplayable: bool = False) -> dict[str, Any]:
    """A V3 lesson with a bass part. A note outside the bass's range raises ValueError, or with
    skip_unplayable is left out of the lesson."""
    if not skip_unplayable:
        outside = [n for n in normalized.get('notes', []) if not BASS.playable(int(n['pitch']))]
        if outside:
            raise ValueError(f"{len(outside)} note{'s' if len(outside) > 1 else ''} cannot be played on the bass "
                             f"(MIDI {BASS.spec.tuning[-1]}-{BASS.spec.tuning[0] + BASS.spec.max_fret}).")
    lesson = normalized_to_lesson(normalized, fps=fps, name=name, keep=lambda n: BASS.playable(int(n['pitch'])))
    part = BASS.new_part()
    lesson['parts'][BASS.name] = part
    BASS.assign(lesson, part)
    return lesson
