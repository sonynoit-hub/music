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

