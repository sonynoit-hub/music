"""Four-string bass in standard tuning (E1 A1 D2 G2): the guitar's positions, fingering, tabs and V2
view on the bass spec (instruments.fretted.BASS_SPEC). The fingering planner keeps the hand in a
four-fret box, one finger per fret, as it does on the guitar."""
from __future__ import annotations

from guitar_video_app.instruments.fretted import BASS_SPEC
from guitar_video_app.instruments.guitar import Guitar

BASS_PROGRAM = BASS_SPEC.program  # General MIDI electric bass (finger)
BASS_LOW, BASS_HIGH = 28, 63  # open low E to fret 20 of the G string


class Bass(Guitar):
    name = 'bass'
    spec = BASS_SPEC
    midi_program = BASS_PROGRAM
    # Basic Pitch hears low-E-string notes of a full mix weakly (note strength about 0.3 to 0.45),
    # so the bass listens with lower thresholds; keep_line removes most of the extra notes.
    transcription = dict(low=BASS_LOW, high=BASS_HIGH, line='lowest', onset_threshold=0.4, frame_threshold=0.25)


BASS = Bass()
