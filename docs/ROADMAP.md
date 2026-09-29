# Roadmap

## V1 Scope

Build a reliable MIDI-to-JSON-to-Blender pipeline synchronized to a final WAV master.

V1 includes:

- PPQ.
- Notes.
- Note start and end timing.
- Tempo changes.
- Time signatures.
- Beats.
- Measures.
- Duration.
- Tracks.
- Guitar string and fret mapping.
- WAV offset.
- Blender synchronization.

## V1 Completion Criteria

V1 is complete when:

- A MIDI file can be parsed into raw musical facts.
- The Music Analyzer can produce notes, beats, measures, duration, and seconds-based timing.
- Guitar Mapper can assign string and fret positions.
- A normalized JSON file can be generated.
- Blender can import the JSON without doing musical analysis.
- Blender can load the final WAV as master audio.
- Blender can apply `audio_offset`.
- A new song import rebuilds song-specific notes, tabs, measures, animations, and audio.
- Reusable scene, model, camera, panel, staff, and material setup survives new-song import.

## Existing Assets To Preserve

- Existing V2 lesson tests in `data/lesson_tests/`.
- Dashboard import and audio-offset workflow.
- Existing Blender bridge behavior.
- Existing `.blend` scene files in `outputs/`.

## Active Plan

Use `docs/V1_ADAPTATION_PLAN.md` as the current step-by-step migration plan from the existing V2 lesson/dashboard system toward normalized MIDI-derived song JSON.

## Later Work

After V1 is stable, possible future work includes:

- Velocity-based visual styling.
- Chord detection.
- Key detection.
- Section detection.
- Advanced guitar techniques.
- WAV-to-MIDI or AI transcription workflows.
- Richer visual themes and camera automation.
