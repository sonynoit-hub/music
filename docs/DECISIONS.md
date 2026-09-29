# Architectural Decisions

This file records project decisions and rationale so future work does not need the original conversation history.

## 1. Reuse The Existing Guitar Project

Decision: Continue from `/Users/dc/CodexProjects/guitar` rather than starting a new project.

Rationale: This project already contains useful Blender scenes, MIDI/WAV outputs, V2 lesson tests, dashboard code, and Blender bridge code.

## 2. Use `outputs/v3-tests.blend` As Latest Scene Candidate

Decision: Treat `outputs/v3-tests.blend` as the latest known Blender scene candidate unless the user selects another file.

Rationale: It is newer than `outputs/lesson-v2-tests.blend` and `outputs/reference-guitar.blend`, and appears to match the user's memory of the latest scene.

## 3. Use MIDI As The Structured Music Source

Decision: V1 uses MIDI for musical structure.

Rationale: MIDI already contains notes, ticks, PPQ, tempo changes, time signatures, and tracks. This avoids unreliable audio transcription in the first version.

## 4. Use Final WAV As Master Audio

Decision: V1 uses the final WAV for rendered audio.

Rationale: MIDI provides structure, but the WAV is the sound the viewer should hear. Blender syncs visuals to the WAV using seconds-based timing and `audio_offset`.

## 5. Keep Musical Analysis Outside Blender

Decision: Python owns MIDI parsing, musical timing, measure calculation, and guitar mapping. Blender only renders.

Rationale: Blender is better as a visual renderer than as a music-analysis engine. Keeping analysis outside Blender makes the JSON contract testable and keeps renders deterministic.

## 6. Preserve Ticks And Seconds

Decision: Export both tick-based timing and seconds-based timing.

Rationale: Ticks preserve musical structure. Seconds are required for audio and Blender timeline sync.

## 7. Make JSON The Python-To-Blender Contract

Decision: Normalized JSON is the boundary between analysis and rendering.

Rationale: A stable contract lets the analyzer and Blender importer evolve independently while making import bugs easier to isolate.

## 8. Rebuild Song-Specific Data On Import

Decision: Importing a new song rebuilds song-specific measures, notes, tabs, animations, and audio.

Rationale: Song data should never leak from one import to the next. Reusable scene setup should remain intact.

## 9. Freeze V1 Before Advanced Features

Decision: V1 excludes WAV-to-MIDI, velocity interpretation, chord/key/section detection, AI transcription, and advanced guitar techniques.

Rationale: The first milestone is reliable synchronization and rendering. Higher-level musical interpretation can be added after the base pipeline works.

## 10. Add Normalized Export Beside Existing V2

Decision: Add `guitar_video_app/core/normalized_song.py`, `guitar_video_app/core/music_analyzer.py`, and the `normalize-midi` CLI command without replacing the existing V2 lesson renderer.

Rationale: The current V2 dashboard and Blender workflow is already verified. A separate normalized exporter lets the project prove the MIDI-to-JSON contract first, then add compatibility conversion or direct Blender import with lower risk.

## 11. Convert Normalized JSON To V2 Before Direct Blender Import

Decision: Add a normalized-to-V2 compatibility bridge for fixed-tempo, single-time-signature songs before changing Blender import behavior.

Rationale: V2 can already render beat-based lessons reliably, but it cannot represent tempo maps or time-signature changes. The bridge lets MIDI-derived normalized songs use the existing renderer while keeping richer normalized JSON as the long-term contract.

## 12. Dashboard Stores Converted V2 For Normalized Imports

Decision: When the dashboard receives normalized JSON, it converts the file to V2 lesson JSON and stores that converted V2 file for preview and Blender transfer.

Rationale: This keeps the verified dashboard and Blender bridge unchanged while allowing the user to import normalized MIDI-derived song data. Direct normalized Blender import remains the later architecture step.
