"""Normalized song schema; moved, see the modules below. Kept so older scripts and saved scenes still import."""
from guitar_video_app.music.normalized_song import SCHEMA_VERSION, NormalizedBeat, NormalizedMeasure, NormalizedNote, NormalizedSong, NormalizedTrack, TempoChange, TimeSignatureChange, normalized_song_to_dict, write_normalized_song  # noqa: F401
