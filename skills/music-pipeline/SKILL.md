# Music Pipeline Skill

Use this skill when adding or updating the MIDI-to-JSON-to-Blender music lesson workflow, especially when processing a new song.

## Start Here

Before changing code or data, read:

1. `AGENTS.md`
2. `docs/ARCHITECTURE.md`
3. `docs/JSON_SCHEMA.md`
4. `docs/MUSIC_RULES.md`
5. `docs/DECISIONS.md`

Use `docs/ROADMAP.md` to check whether a request belongs in V1.

## New-Song Processing Workflow

Follow this sequence for each new song:

1. Collect the source MIDI file and final WAV file.
2. Parse MIDI facts:
   - PPQ.
   - Raw notes.
   - Tempo changes.
   - Time-signature changes.
   - Track information.
3. Analyze musical timing:
   - Convert ticks to beats.
   - Convert ticks to seconds using the tempo map.
   - Calculate note start, end, and duration.
   - Calculate beat positions.
   - Calculate measure boundaries.
   - Calculate total duration.
4. Map to the instrument (for guitar, `instruments/guitar/mapper.py`; steps 2-3 are `music/` and know no instrument):
   - Convert pitch to string and fret.
   - Resolve duplicate playable positions when needed.
   - Attach tab position data to notes or a mapping table. In a dashboard lesson (Lesson V3) this is the guitar part's `positions`; Blender reads the guitar view (V2) built from it.
5. Export normalized JSON:
   - Preserve tick-based timing.
   - Preserve seconds-based timing.
   - Include tempo and time-signature maps.
   - Include `audio_offset`.
   For piano, set the song's instrument to Piano in the dashboard before importing: hands come from the MIDI file's left- and right-hand tracks when it has them, otherwise they are planned (`instruments/piano/hands.py`). Check the piano roll, click notes to flip a wrong hand, then Plan hands to re-plan the rest around your choices.
6. Import into Blender:
   - Start from the selected reusable scene, currently `outputs/v4-vertical.blend` unless the user chooses another file. Piano songs use `outputs/piano-vertical.blend` (rebuild it with `Blender -b --factory-startup --python scripts/make_piano_scene.py`), or `outputs/piano-visual.blend` when the song's Piano look is Musical notes or Blue plumes (rebuild it with `scripts/make_piano_visual_scene.py`; render with `scripts/render_piano_visual.py`, which shows notes unless given `--effect plumes`).
   - Load normalized JSON.
   - Remove prior song-specific measures, notes, tabs, animations, and audio.
   - Preserve reusable scene, guitar model, camera, panel, staff, material, lighting, and render setup.
   - Create the current song's measures, notes, tabs, animations, and audio.
   - Convert seconds to frames for animation and audio placement.
7. Verify sync:
   - Confirm the WAV is the final master audio.
   - Confirm `audio_offset` is applied in seconds.
   - Confirm note and measure visuals align to seconds-derived frame positions.

## Tab Image Or PDF Workflow

When the user gives a published tab (image or PDF) for a song whose audio is in the dashboard, use it as the reference for the lesson instead of transcription alone. The import fits it to the audio and then adapts it to what the player actually plays (moved, added and removed notes), keeping the tab's fingering. No code change is needed per song.

1. Read the tab and write a tab file in `data/tabs/<song>.json` (format: `docs/JSON_SCHEMA.md`, "Tab file"; example: `data/tabs/shape_of_my_heart_intro.json`):
   - `title`, `artist`, the written `tempo_bpm` (approximate is fine; the fit searches 70-140% of it), `time_signature`.
   - One note per line: `string` (1 = high E), `fret`, `start_beat` and `duration_beats` counted in quarter notes from the start of the first bar, as fractions like `"3/4"`; triplet 8ths are `"1/3"` beat apart.
   - Write repeats and endings out in the order they are played in the recording.
   - Add `audio_start` (rough audio second of the first bar) only if the tab covers a later section.
2. Check every bar: each bar's notes and rests should add up to the time signature. Read chords from the tab column, and rhythm from the stems and beams under the tab.
3. Import it: dashboard Tab row, or `.venv/bin/python scripts/import_tab.py data/tabs/<song>.json --song <song id>`. If the song already has a lesson (for example after Generate MIDI), this reviews it instead: the tab's bars are replaced wherever the recording plays them, the rest keeps its notes with fingering like the tab, and Undo review restores the previous lesson. A tab of one section is enough; do not write out repeats of it.
4. Report the fit to the user: notes heard out of total, average error, tempo, start, any capo shift, and how many notes were moved, added and removed to match the playing. For a review, report where the tab was found and the counts of unchanged, re-fingered, moved, added and removed notes. Under about 60% heard means the tab and the recording differ (other arrangement, key, or section).
5. Keep a copy as a benchmark (`data/benchmarks/`) when it is useful for measuring transcription.

## Guardrails

- Do not infer measures in Blender.
- Do not interpret tempo maps in Blender.
- Do not make FPS the source of musical timing.
- Do not add out-of-scope music-analysis features to V1 unless the roadmap is intentionally updated.
- Do not preserve old song-specific data during a new-song import.
- Do not overwrite `outputs/reference-guitar.blend` unless explicitly requested.

## Update Rules

When changing the pipeline:

- Update `docs/ARCHITECTURE.md` for component responsibility changes.
- Update `docs/JSON_SCHEMA.md` for JSON contract changes.
- Update `docs/MUSIC_RULES.md` for timing or measure-rule changes.
- Update `docs/DECISIONS.md` for major architecture decisions.
- Update `docs/ROADMAP.md` when scope changes.
- Keep musical logic in `guitar_video_app/music/` free of instrument imports; put instrument-specific logic in `guitar_video_app/instruments/<instrument>/` behind the `Instrument` interface and `PitchRules` (decision 31). Run `scripts/verify_music_without_instrument.py` after changing `music/`, and `scripts/verify_piano.py` after changing `instruments/` or the piano scene.

