# Music Lesson Project Agent Rules

## Source Of Truth

This repository generates synchronized short music-lesson videos from MIDI data, normalized lesson JSON, Blender animation, and a final WAV master.

Target pipeline:

```text
MIDI -> MIDI Parser -> Music Analyzer -> Guitar Mapper -> normalized JSON -> Blender
Final WAV -> Blender audio sync
```

## Operating Rules

1. Read this file before making project changes.
2. Keep `docs/ARCHITECTURE.md` as the system design source of truth.
3. Keep `docs/JSON_SCHEMA.md` as the Python-to-Blender contract.
4. Keep `docs/MUSIC_RULES.md` as the timing and measure authority.
5. Keep `docs/DECISIONS.md` updated when architecture choices change.
6. Use `skills/music-pipeline/SKILL.md` for repeatable new-song processing.
7. Do not move musical analysis into Blender.
8. Do not make Blender FPS the source of musical timing.
9. Preserve both tick-based timing and seconds in exported song data.
10. Preserve reusable scene, model, camera, panel, staff, and material setup when importing a new song.

## Current Reuse Base

Use `outputs/v4-vertical.blend` (9:16, 1080x1920) as the latest Blender scene candidate unless the user selects another `.blend` file. It is built from the 4:5 scene `outputs/v3-tests.blend` by `scripts/make_vertical_scene.py`; re-run that script after changing the 4:5 scene.

Do not overwrite `outputs/reference-guitar.blend` unless explicitly requested.

## V1 Boundaries

V1 includes MIDI parsing, musical timing analysis, guitar mapping, normalized JSON export, final WAV sync, and Blender rendering.

V1 excludes WAV-to-MIDI, velocity interpretation, chord detection, key detection, section detection, AI transcription, and advanced guitar techniques.

