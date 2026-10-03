# Music Rules

This document owns timing, beat, and measure rules for the music lesson pipeline.

## Timing Sources

MIDI ticks are the stable musical source. Seconds are derived from ticks using the tempo map.

Blender frames are render-time values derived from seconds. Frames are never the source of musical truth.

## PPQ

PPQ, also called ticks per quarter note, comes from the MIDI file.

All tick-to-beat and tick-to-seconds calculations must use the MIDI file's PPQ value.

## Tempo Map

Tempo changes are MIDI facts extracted by the parser and interpreted by the Music Analyzer.

The Music Analyzer uses the tempo map to convert:

- Tick to seconds.
- Note start and end ticks to seconds.
- Beat and measure boundaries to seconds.
- Total duration to seconds.

## Time-Signature Map

Time-signature changes are MIDI facts extracted by the parser and interpreted by the Music Analyzer.

The Music Analyzer uses the time-signature map to determine:

- Beats per measure.
- Measure boundaries.
- Beat positions within measures.
- The measure number for each note.

A lesson has one time signature for the whole song. The dashboard can change it (`set_time_signature`):
notes keep their quarter-note beats and seconds, tempo changes stay at their beats, and only measure
boundaries move; the end moves to a measure boundary. A 6/8 measure is three quarter-note beats.

## Timing A Transcription

Generate MIDI fits one tempo and a measure start to the transcribed note times (`suggest_grid`), then
gives a measure its own tempo only when that puts clearly more notes on the grid (`fit_tempo_map`).
The measure start is the beat nearest the first note, except for an instrument transcribed as one line
(a bass): its measures start where its long, low notes (its roots) land, so a pickup stays a pickup,
and a tempo change must fix at least six notes (`root_downbeat`, `LINE_TEMPO_CHANGE_COST`, decision 47).
First beat and Apply timing still move bar 1 by hand.

## Notes

Each note must preserve:

- Pitch.
- Track identity.
- Start tick.
- End tick.
- Duration in ticks.
- Start seconds.
- End seconds.
- Duration in seconds.
- Beat and measure placement.

## Pedals

Sustain pedal events are extracted from MIDI CC64 and stored separately from notes.

Each pedal event must preserve:

- Type.
- Track identity.
- Start tick.
- End tick.
- Duration in ticks.
- Start seconds.
- End seconds.
- Duration in seconds.
- Beat and measure placement.
- Raw MIDI value.

Pedal events must not be baked into note end times. Piano rendering may later use them to show sound sustain separately from physical key release.

## Measures

Measures are generated from PPQ, tempo-map context, and time-signature-map context.

Measures must be rebuilt when importing a new song.

## Audio Sync

The final WAV is the master audio source for Blender playback and rendering.

`audio_offset` adjusts the relationship between the WAV and the visual timeline. The value is measured in seconds.

## V1 Non-Goals

V1 does not interpret expressive or higher-level musical meaning.

Out of scope:

- WAV-to-MIDI.
- Velocity interpretation.
- Chord detection.
- Key detection.
- Section detection.
- AI transcription.
- Advanced guitar techniques.
