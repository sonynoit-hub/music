# Architecture

## V1 Goal

Generate synchronized short music-lesson videos from a MIDI file and a final WAV master.

The MIDI file provides structured musical data. The WAV file provides the final audio heard in the rendered lesson.

The current project already contains useful V2 lesson tests, dashboard code, Blender bridge code, MIDI/WAV outputs, and reusable `.blend` scenes. Preserve that work while moving the architecture toward the contract below.

## Pipeline

```text
MIDI
  -> MIDI Parser
  -> Music Analyzer
  -> Guitar Mapper
  -> normalized JSON
  -> Blender

Final WAV
  -> Blender audio sync
```

## Component Ownership

### MIDI Parser

The parser extracts MIDI facts without interpreting them for rendering.

It owns:

- PPQ / ticks-per-quarter-note from the MIDI file.
- Raw notes and note events.
- Tempo changes.
- Time-signature changes.
- Track information.

### Music Analyzer

The analyzer turns MIDI facts into musical timing and structure.

It owns:

- PPQ and tick-based timing calculations.
- Tempo map interpretation.
- Time-signature map interpretation.
- Note start and end timing.
- Beat positions.
- Measure boundaries.
- Song duration.
- Tick-to-seconds conversion.

### Guitar Mapper

The guitar mapper turns analyzed pitches into guitar-specific playing positions.

It owns:

- Pitch-to-string mapping.
- Pitch-to-fret mapping.
- Duplicate-position resolution when needed.
- Tab position data for Blender.

### Normalized JSON

The normalized JSON file is the contract between the Python pipeline and Blender.

It must contain enough tick-based and seconds-based data for Blender to render without performing musical analysis.

See `docs/JSON_SCHEMA.md`.

### Blender

Blender renders the lesson.

It owns:

- Loading normalized JSON.
- Loading the final WAV.
- Applying `audio_offset`.
- Converting seconds to frames.
- Creating or updating visual objects, note/tab animations, and audio strips.
- Preserving reusable scene, model, camera, panel, staff, lighting, render, and material setup.

Blender must not own:

- MIDI parsing.
- Beat or measure calculation.
- Tempo-map interpretation.
- Time-signature interpretation.
- Tick-to-seconds conversion.

## New-Song Import Contract

Importing a new song must rebuild all song-specific data:

- Measures.
- Notes.
- Tabs.
- Animations.
- Audio.

Importing a new song must preserve reusable setup:

- Guitar model.
- Scene layout.
- Cameras.
- Materials.
- Staff and tab panel placement.
- Lighting and render configuration unless explicitly changed.

## Current Reusable Files

The latest known Blender scene candidate is:

- `outputs/v3-tests.blend`

Other important reusable files:

- `outputs/reference-guitar.blend`
- `outputs/lesson-v2-tests.blend`
- `outputs/complex_32_measures.mid`
- `outputs/complex_32_measures.wav`
- `data/lesson_tests/`
- `guitar_video_app/core/`
- `guitar_video_app/integrations/`

