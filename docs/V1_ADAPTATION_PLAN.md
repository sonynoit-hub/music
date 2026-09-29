# V1 Adaptation Plan

This plan adapts the existing guitar project toward the target normalized MIDI-to-JSON-to-Blender architecture without breaking the current V2 lesson tests, dashboard workflow, or saved Blender scenes.

## Baseline Verified

Verified on 2026-09-28:

- `outputs/v3-tests.blend` exists and is the latest known scene candidate.
- `outputs/v3-tests.backup-before-v1.blend` was created as a backup copy.
- Python source compiles successfully.
- `scripts/build_lesson_tests.py` completes successfully.
- `scripts/verify_lesson_audio.py` passes:
  - 206 MIDI notes match JSON pitches/start/end.
  - WAV is stereo, 85.333 seconds.
  - Rests verified.
- `scripts/verify_dashboard_reload.py` passes under Blender:
  - `outputs/v3-tests.blend` loads.
  - Embedded loader works.
  - Single handler and single audio strip are preserved.
  - All 13 playback checkpoints pass.
- `scripts/verify_saved_lesson.py` passes under Blender:
  - 64 frame checks.
  - Six active string colors.
  - Open/fretted markers.
  - String vibration.
  - Two tab pages.
  - Bar lines.
  - Fixed transforms.
  - Repeat install.
  - Embedded reload.
- `scripts/verify_lesson_v2.py` passes under Blender:
  - All lesson fixtures pass.
  - 1713 frame checks pass.
  - Invalid inputs are rejected.
  - Retrigger and triplet assertions pass.
  - Preserve-listed transforms stay fixed.
  - `outputs/lesson-v2-tests.blend` and `outputs/lesson-v2-chords.png` are regenerated.

## Current Architecture Observed

The repository currently has two useful layers.

### Older MIDI-To-Chart Path

Files:

- `guitar_video_app/core/midi_to_json.py`
- `guitar_video_app/core/schema.py`
- `guitar_video_app/core/chart_builder.py`
- `guitar_video_app/core/timing.py`
- `guitar_video_app/api/service.py`
- `guitar_video_app/cli.py`

Current behavior:

- Parses MIDI with `mido`.
- Produces a seconds-based raw song.
- Groups notes into chart events.
- Maps pitches to guitar positions.
- Converts seconds to frames.

Gap:

- Original start/end ticks are not preserved in `RawNote`.
- Tempo changes are recorded as seconds/beat/BPM but not as a full tick-aware tempo map.
- Time signatures are only stored as the last seen time signature.
- Measures and beats are not generated as normalized output.

### Stronger V2 Lesson Path

Files:

- `guitar_video_app/core/lesson_v2.py`
- `guitar_video_app/core/lesson_midi.py`
- `guitar_video_app/integrations/lesson_setup.py`
- `guitar_video_app/integrations/lesson_controller_v2.py`
- `guitar_video_app/api/dashboard.py`
- `data/lesson_tests/`
- `scripts/verify_lesson_v2.py`
- `scripts/verify_dashboard_reload.py`
- `scripts/verify_lesson_audio.py`

Current behavior:

- Uses beat-based V2 JSON.
- Validates strings, frets, starts, durations, retriggers, page boundaries, overlaps, chords, rests, and dense notes.
- Exports MIDI/WAV from V2 lesson JSON.
- Dashboard imports V2 JSON plus WAV.
- Dashboard supports `audio_offset`.
- Blender receives JSON/WAV and preserves reusable scene geometry.

Gap:

- V2 JSON is beat-based and fixed-tempo.
- It does not yet represent MIDI ticks, tempo changes, time-signature changes, generated beats, generated measures, or tick-to-seconds mapping.

## Recommended Implementation Order

### 1. Add A Normalized Song Model Beside Existing V2

Status: implemented.

Add new model code without replacing V2:

- New file: `guitar_video_app/core/normalized_song.py`
- Keep existing V2 fixtures and controllers unchanged.
- Include explicit structures for:
  - song metadata
  - PPQ
  - tempo changes
  - time-signature changes
  - tracks
  - notes with ticks and seconds
  - beats
  - measures
  - audio metadata
  - guitar mapping

Reason:

This avoids forcing the current V2 tests to migrate before the normalized contract is proven.

### 2. Upgrade MIDI Parsing To Preserve Facts

Status: implemented in the new normalized path.

Update or wrap `guitar_video_app/core/midi_to_json.py` so the parser extracts MIDI facts without rendering assumptions.

Parser output should preserve:

- `ppq`
- track id/name/channel/instrument when available
- note pitch
- note start tick
- note end tick
- note duration ticks
- raw velocity, without V1 interpretation
- tempo changes by tick
- time-signature changes by tick

Important:

Do not remove the current `midi_to_raw_song` API until callers are migrated.

### 3. Add Music Analyzer

Status: implemented in `guitar_video_app/core/music_analyzer.py`.

Add analyzer code that converts parser facts into the normalized contract.

Suggested file:

- `guitar_video_app/core/music_analyzer.py`

Responsibilities:

- Build a tempo map.
- Convert ticks to seconds.
- Convert ticks to beat positions.
- Generate beat records.
- Generate measure records.
- Compute duration.
- Attach each note to beat and measure context.

This is the key step that keeps Blender from doing musical analysis.

### 4. Reuse Guitar Mapping

Status: implemented in the normalized analyzer.

Keep using existing mapping logic where possible:

- `guitar_video_app/core/fingering_solver.py`
- `guitar_video_app/core/note_mapping.py`
- `guitar_video_app/core/chart_builder.py`

Adapt it so normalized notes receive:

- `string`
- `fret`

without losing:

- `pitch`
- `start_tick`
- `end_tick`
- `start_seconds`
- `end_seconds`

### 5. Add Normalized JSON Export

Status: implemented as the `normalize-midi` CLI command.

Add a new CLI command before changing existing commands.

Suggested command:

```sh
.venv/bin/python -m guitar_video_app.cli normalize-midi input.mid output/song.normalized.json --wav output/audio.wav --audio-offset 0
```

The command should emit the contract described in `docs/JSON_SCHEMA.md`.

Keep existing commands working:

- `midi-to-json`
- `chart`
- `all`
- dashboard import
- V2 lesson tests

### 6. Add Compatibility Conversion Into V2

Status: implemented for fixed-tempo, single-time-signature normalized songs.

Before teaching Blender a new format, add a conversion layer:

```text
normalized song JSON -> current V2 lesson JSON
```

Suggested file:

- `guitar_video_app/core/normalized_to_lesson_v2.py`

Purpose:

- Let the current verified V2 Blender renderer consume normalized MIDI-derived songs.
- Preserve all existing Blender tests.
- Reduce risk before introducing a new Blender importer.

Implemented as:

- `guitar_video_app/core/normalized_to_lesson_v2.py`
- `normalized-to-v2` CLI command
- `scripts/verify_normalized_to_v2.py`

### 7. Extend Dashboard Import

Status: implemented for fixed-tempo, single-time-signature normalized songs.

Once normalized JSON exists and can convert to V2:

- Allow dashboard to import normalized JSON.
- Show song duration, measure count, note count, audio duration, and offset.
- Keep current V2 JSON import working.
- Keep `audio_offset` measured in seconds.

Implemented as:

- Dashboard JSON upload detects `schema_version: "1.0"`.
- Normalized JSON is converted to V2 before storage and Blender transfer.
- Dashboard MIDI upload analyzes MIDI into normalized song data, converts to V2, and stores that lesson JSON for preview and Blender transfer.
- The dashboard summary records whether the source was V2 or normalized JSON.
- `scripts/verify_dashboard_normalized_import.py` verifies normalized import.
- `scripts/verify_dashboard_midi_import.py` verifies MIDI-first import.

### 8. Teach Blender Importer Normalized JSON Directly

Status: next step.

Only after normalized export and compatibility conversion are stable, update Blender import code to consume normalized JSON directly.

Blender should:

- Remove prior song-specific objects and audio.
- Preserve scene/camera/model/panel/material setup.
- Use seconds for frame conversion.
- Use precomputed notes, beats, and measures.
- Never compute tempo maps or measures.

## Risk Controls

Before each phase:

```sh
.venv/bin/python -m py_compile $(find guitar_video_app scripts -name '*.py')
.venv/bin/python scripts/build_lesson_tests.py
.venv/bin/python scripts/verify_lesson_audio.py
```

For Blender-affecting changes:

```sh
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python-exit-code 1 --python scripts/verify_dashboard_reload.py
/Applications/Blender.app/Contents/MacOS/Blender --background outputs/reference-guitar.blend --python-exit-code 1 --python scripts/verify_saved_lesson.py
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup outputs/reference-guitar.blend --python-exit-code 1 --python scripts/verify_lesson_v2.py
```

Do not overwrite:

- `outputs/reference-guitar.blend`
- `outputs/v3-tests.blend`

Use backups or new filenames for experimental scenes.

## First Coding Task

Implement `guitar_video_app/core/normalized_song.py` and `guitar_video_app/core/music_analyzer.py`, then add tests using the existing generated MIDI:

- `outputs/complex_32_measures.mid`

Initial success criteria:

- Normalized JSON includes PPQ, tempo map, time-signature map, tracks, notes with ticks and seconds, beats, measures, duration, guitar mapping, and audio metadata.
- Existing V2 checks still pass.
- No Blender scene files are modified during parser/analyzer work.
