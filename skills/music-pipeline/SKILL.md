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
4. Map guitar positions:
   - Convert pitch to string and fret.
   - Resolve duplicate playable positions when needed.
   - Attach tab position data to notes or a mapping table.
5. Export normalized JSON:
   - Preserve tick-based timing.
   - Preserve seconds-based timing.
   - Include tempo and time-signature maps.
   - Include `audio_offset`.
6. Import into Blender:
   - Start from the selected reusable scene, currently `outputs/v3-tests.blend` unless the user chooses another file.
   - Load normalized JSON.
   - Remove prior song-specific measures, notes, tabs, animations, and audio.
   - Preserve reusable scene, guitar model, camera, panel, staff, material, lighting, and render setup.
   - Create the current song's measures, notes, tabs, animations, and audio.
   - Convert seconds to frames for animation and audio placement.
7. Verify sync:
   - Confirm the WAV is the final master audio.
   - Confirm `audio_offset` is applied in seconds.
   - Confirm note and measure visuals align to seconds-derived frame positions.

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

