"""Note dataclasses; moved, see the modules below. Kept so older scripts and saved scenes still import."""
from guitar_video_app.music.schema import RawNote, RawSong, TempoEvent, dataclass_to_json  # noqa: F401
from guitar_video_app.instruments.guitar.schema import ChartEvent, ChartNote, GuitarPosition  # noqa: F401
