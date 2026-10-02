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

When a published tab exists, it replaces the MIDI branch for strings, frets and beats:

```text
Tab image or PDF -> tab file (written by the agent) -> Tab Fitter (+ onsets of the final WAV) -> V3 lesson -> guitar view (V2) -> Blender
```

### Tab Fitter

`guitar_video_app/music/alignment.py` derives the tempo map and audio offset from the recording's note onsets, then adapts the written part to what is played (notes moved, added or removed). `guitar_video_app/instruments/guitar/tab.py` reads the tab file and keeps the tab's fingering; added notes take the string the tab uses for their pitch nearby. See decision 24; tabs written above 120 BPM are fitted counting slower beats and keep their written meter (decision 29).

### Tab Review

When the song already has a lesson (usually a transcription), a tab reviews it instead of replacing it: `guitar_video_app/music/review.py` finds every place the recording plays the tab, puts the fitted and adapted tab there, keeps the lesson's other notes and continues the tab's bar lines and tempo over the rest of the song; `review_with_tab` in `instruments/guitar/tab.py` then re-fingers the kept notes like the tab. See decision 28.

```text
V3 lesson (transcribed) + tab file + onsets and cleaned transcription of the final WAV -> Tab Review -> V3 lesson + change report
```

## Code Layout: Music And Instruments

Music logic does not depend on any instrument, so another instrument reuses it unchanged (decision 31); piano was added this way (decision 32).

- `guitar_video_app/music/`: MIDI analysis (`analyzer.py`), transcription and its cleanup, tempo maps (`tempo.py`), the lesson's music layer and playback (`lesson.py`), retiming and tidying (`retime.py`), fitting a written part to audio (`alignment.py`), reviewing against a reference (`review.py`), MIDI export (`midi_export.py`) and normalized-JSON conversion (`normalized.py`). Nothing here imports an instrument; `scripts/verify_music_without_instrument.py` checks that and runs the whole music layer with no instrument part.
- `guitar_video_app/music/rules.py`: the questions music code asks about how notes are played (which notes share a slot and cut each other off, their order, which notes are bass, how a copied or added note is played). `PitchRules` answers by pitch alone.
- `guitar_video_app/instruments/`: one package per instrument, registered in `INSTRUMENTS`. An instrument (`base.Instrument`) turns its part of a lesson into rules for the music code (`rules`), chooses how its part plays the notes (`assign`), checks the part against the music (`check`), drops data of deleted notes (`sync`), builds what its renderer draws (`view`) and names its MIDI tracks (`midi_tracks`). The first part is the active one: `lesson_rules(lesson)` and `check_lesson` use it (or `PitchRules` when there is none), and `activate(lesson, instrument)` makes another instrument's part active, adding and assigning it when missing; other parts are kept for switching back.
- `guitar_video_app/instruments/guitar/`: tuning, the Guitar Mapper (`mapper.py`), fingering (`fingering_solver.py`, `refinger.py`), `GuitarRules` (the string is the slot), tabs (`tab.py`), the V2 guitar view and its validation (`view.py`) and per-string MIDI export (`midi.py`).
- `guitar_video_app/instruments/piano/`: the 88-key geometry in millimetres (`keyboard.py`), the hand planner and hands from MIDI tracks (`hands.py`), `PianoRules` (the pitch is the slot; the left hand is the bass), the piano view (`view.py`) and piano lessons from normalized JSON (`normalized.py`).
- `guitar_video_app/core/`: old import paths only; each module re-exports from the new place so older scripts and saved scenes keep working.

Adding an instrument: write `instruments/<name>/` with an `Instrument` subclass and its rules, register it, and give its renderer a view. The music layer, dashboard timing tools and tab-free imports need no change.

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
- Sustain pedal spans from MIDI CC64, stored separately from note timing.
- Beat positions.
- Measure boundaries.
- Song duration.
- Tick-to-seconds conversion.

### Guitar Mapper

The guitar mapper (`guitar_video_app/instruments/guitar/mapper.py`) turns analyzed pitches into guitar-specific playing positions. The Music Analyzer (`guitar_video_app/music/analyzer.py`) leaves `string` and `fret` empty.

It owns:

- Pitch-to-string mapping.
- Pitch-to-fret mapping.
- Duplicate-position resolution when needed.
- Tab position data for Blender.

### Normalized JSON

The normalized JSON file is the contract between the Python pipeline and Blender.

It must contain enough tick-based and seconds-based data for Blender to render without performing musical analysis.

The dashboard stores each song's lesson as V3: a music layer plus one part per instrument. Blender and the renderer read the active instrument's view of it, written beside the lesson on every send and render: the guitar view (V2, `guitar_view.json`) or the piano view (`piano_view.json`).

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

The piano has its own scene, `outputs/piano-vertical.blend`, built from nothing by `scripts/make_piano_scene.py` (`integrations/piano_scene.py`: 88 keys at real size named `Piano_Key_021`-`Piano_Key_108`, pivoting 400 mm behind their front edge, a simple case, Workbench studio lighting and an orthographic camera). `integrations/piano_lesson.py` loads a piano view, frames the keys the song uses and presses and colors keys by hand on every frame, with seconds from the lesson's tempo map. The dashboard sends and renders with the scene of the song's instrument; a piano song's Piano look (`piano_look`) picks this lesson keyboard or the PIANO_VISUAL stage with rising notes or plumes (`outputs/piano-visual.blend`, decisions 36 and 37). Sustain pedal events are available in the piano view as optional metadata; the current key-press renderer does not yet use them to extend visual sustain or animate pedals.

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

- `outputs/v4-vertical.blend` (9:16, built from `outputs/v3-tests.blend` by `scripts/make_vertical_scene.py`)
- `outputs/piano-vertical.blend` for piano songs (9:16, built by `scripts/make_piano_scene.py`)
- `outputs/piano-visual.blend`: PIANO_VISUAL, a compact 88-key stage piano for visualization videos with open space above the keys (built by `scripts/make_piano_visual_scene.py` from `integrations/piano_visual.py`, checked by `scripts/verify_piano_visual.py`; decision 34). A piano view plays on it with key and pedal motion and the final WAV, and one of two effects (`integrations/piano_visual_particles.py`, rendered by `scripts/render_piano_visual.py --effect notes|plumes`). The default effect is glowing half, quarter and eighth note symbols rising from each key press with a sparkle trail (`integrations/piano_visual_notes.py`, checked by `scripts/verify_piano_visual_notes.py`; decision 37). The other is particle plumes rising from the sounding keys (checked by `scripts/verify_piano_visual_particles.py`; decision 35). Either effect is blue, white or gold, or coloured by hand (right orange, left blue), with keys glowing to match (`--colors`; decision 38). Piano songs whose Piano look is Musical notes or Particle plumes send and render here from the dashboard with their Note colour (`scripts/verify_dashboard_piano_visual.py`; decisions 36 to 38). Such a song can also have camera shots: a bar-based shot list edited bar by bar on the dashboard's Camera by bar strip or suggested by Auto, planned by `instruments/piano/camera.py` from the tempo map and played by a separate shot camera (`integrations/piano_visual_camera.py`, `--camera camera_shots.json`). Without a list, the presentation camera is used unchanged (checked by `scripts/verify_piano_camera.py` and `scripts/verify_piano_visual_camera.py`; decision 39). For compositing over a background made elsewhere (for example an AI video, put together in DaVinci Resolve), `scripts/render_piano_visual.py --layers` renders transparent RGBA PNG sequences of the instrument, notes, shadow and fx layers plus `composite.json`, and `--reference-frames` renders a reference, guide and mask per shot plus `cameras.json`, with every shot held still (`camera.locked`). `integrations/compositing.py` builds the view layers at render time and removes them afterwards, so nothing is saved into the `.blend`; MP4 stays the preview format (checked by `scripts/verify_piano_visual_layers.py`; decision 40).

Other important reusable files:

- `outputs/v3-tests.blend` (4:5 source scene)
- `outputs/reference-guitar.blend`
- `outputs/lesson-v2-tests.blend`
- `outputs/complex_32_measures.mid`
- `outputs/complex_32_measures.wav`
- `data/lesson_tests/`
- `guitar_video_app/music/`
- `guitar_video_app/instruments/`
- `guitar_video_app/integrations/`
