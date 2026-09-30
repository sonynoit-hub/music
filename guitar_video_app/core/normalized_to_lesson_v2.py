"""Normalized JSON to lessons; moved, see the modules below. Kept so older scripts and saved scenes still import."""
from guitar_video_app.music.normalized import load_normalized_song, normalized_to_lesson  # noqa: F401
from guitar_video_app.instruments.guitar.normalized import convert_normalized_file_to_lesson_v2, lesson_from_normalized, normalized_to_lesson_v2  # noqa: F401
