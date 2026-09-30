"""MIDI analysis plus guitar mapping; moved, see the modules below. Kept so older scripts and saved scenes still import."""
from guitar_video_app.music.analyzer import analyze_midi_file, parse_midi_facts  # noqa: F401
from guitar_video_app.instruments.guitar.mapper import normalize_midi_file  # noqa: F401
