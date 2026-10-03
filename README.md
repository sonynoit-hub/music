# Music Video Studio

Synchronized short music videos for guitar and piano, from MIDI, lesson JSON, Blender and a final WAV.

## Project Context For Codex

Start future project work by reading `AGENTS.md`.

Detailed project memory is split by topic:

- `docs/ARCHITECTURE.md` for system design and component ownership.
- `docs/JSON_SCHEMA.md` for the Python-to-Blender JSON contract.
- `docs/MUSIC_RULES.md` for timing, beat, measure, tempo, and audio sync rules.
- `docs/ROADMAP.md` for current scope and later work.
- `docs/DECISIONS.md` for architectural decisions and rationale.
- `skills/music-pipeline/SKILL.md` for the repeatable new-song workflow.

The latest known Blender scene candidate is `outputs/v4-vertical.blend` (9:16), built from the 4:5 scene `outputs/v3-tests.blend` by `scripts/make_vertical_scene.py`.

## Local dashboard

```sh
.venv/bin/pip install -r requirements-dashboard.txt
.venv/bin/python scripts/run_dashboard.py
```

Open `http://127.0.0.1:8780`. The library starts with the current 206-note lesson.
Create songs, import MIDI, V2/normalized JSON, and PCM WAV files, preview the
waveform and tabs, set an audio offset, and send the pair to Blender. MIDI import
analyzes the music layer and creates the current V2 lesson JSON automatically.
Positive offset delays audio; negative offset starts it before the lesson. Offset
is rounded to Blender frames.

The trash icon on a song in the library (shown on hover and on the selected song)
deletes it after a confirmation. The song leaves the library and its folder (audio,
MIDI, lessons, extracted bass, renders) moves to `data/dashboard/trash/<id>-<time>/`
with its library row as `song.json`, so it can be recovered by hand; empty that
folder to free the space.

**Time signature** (next to Tempo: 4/4, 3/4, 2/4, 2/2, 6/8, 9/8, 12/8, 5/4, 7/8)
sets the bar length for the whole song. Notes keep their audio timing and only the
bar lines move, so the tab, staff, Blender pages and camera shots follow; set where
bar 1 starts with First beat and Apply timing. The song remembers it: Generate MIDI
bars the transcription in it, and a tab file without its own `time_signature` uses
it (decision 45).

The Generate MIDI from WAV button is local and pluggable. It uses Basic Pitch
from a separate transcription environment when installed:

```sh
uv venv --python /opt/homebrew/bin/python3.11 .venv-transcribe
uv pip install --python .venv-transcribe/bin/python basic-pitch "setuptools<81"
```

Without that optional dependency, the dashboard keeps working and shows a setup
message when MIDI generation is requested.

The dashboard connects to the local app bridge on port 8765. Its Connect button
can start that bridge through Blender MCP when available on port 9876. Otherwise
run `scripts/start_dashboard_bridge.py` inside Blender. Open the existing guitar
scene first. No camera, guitar or panel geometry is rebuilt during a transfer.

Send applies the pair without saving the blend. Use Save Blender file to persist
it. An existing lesson soundtrack is replaced rather than duplicated. The saved
lesson loader also starts the bridge when the existing Blender startup loader
loads this file. The Python project must stay at its current location.

Song metadata and revisions are stored in `data/dashboard/library.sqlite3`;
imported assets are copied into song folders there. Originals remain unchanged.
The UI reference image is static, not a live Blender camera feed. Current scope:
V2 JSON + mono/stereo PCM WAV, local playback, transfers and scene saving.
MIDI editing, PDF import, render queues and REAPER are not included yet.

## MIDI and guitar audio

Export the current V2 lesson using the same effective note endings as Blender:

```sh
.venv/bin/pip install -r requirements-midi.txt
.venv/bin/python scripts/export_lesson_audio.py data/lesson_tests/12_complex_32_measures.json outputs/complex_32_measures.mid --wav outputs/complex_32_measures.wav
.venv/bin/python scripts/verify_lesson_audio.py
```

MIDI uses one channel per string and General MIDI nylon guitar (program 24,
zero-based). The optional WAV renderer requires macOS, Swift command-line tools,
and the system General MIDI sound bank. It produces a sampled guitar preview,
not a recording of a real performance. The MIDI file is portable to other DAWs.

## Normalized MIDI JSON

Export MIDI into the V1 normalized JSON contract while preserving ticks, seconds,
tempo changes, time signatures, tracks, measures, beats, guitar mapping, and WAV
sync metadata:

```sh
.venv/bin/python -m guitar_video_app.cli normalize-midi outputs/complex_32_measures.mid outputs/complex_32_measures.normalized.json --wav outputs/complex_32_measures.wav --audio-offset 0 --title "Complex 32 Measures"
.venv/bin/python scripts/verify_normalized_song.py
```

This does not replace the existing V2 lesson/dashboard workflow yet. The next
architecture step is teaching the dashboard to accept normalized JSON and convert
it into the current V2 lesson JSON before sending it to Blender.

Convert normalized JSON into the current V2 lesson format:

```sh
.venv/bin/python -m guitar_video_app.cli normalized-to-v2 outputs/complex_32_measures.normalized.json outputs/complex_32_measures.v2.json --fps 60 --name "Complex 32 Measures From Normalized JSON"
.venv/bin/python scripts/verify_normalized_to_v2.py
```

This compatibility bridge currently supports the fixed-tempo, single-time-signature
case that V2 can render. Songs with tempo or time-signature changes should stay in
normalized JSON until the direct normalized Blender importer exists.

## Version 2 test lessons

See `data/lesson_tests/README.md` for the beat-based JSON contract and test cases.
V2 supports simultaneous strings, independent note lengths, rests, same-string
retriggering, frets 0-20, and two measures per page. It uses standard numbering
(1 = high E, 6 = low E), unlike the historical demo's row-based numbering.

The tested preview scene is `outputs/lesson-v2-tests.blend`; the original
`outputs/reference-guitar.blend` is not overwritten by verification.
Load a JSON fixture through `install_lesson` or the existing app adapters.
To install a fixture into a chosen blend file using the command line:

```sh
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup outputs/lesson-v2-tests.blend --python scripts/install_saved_lesson.py -- --chart data/lesson_tests/11_combined.json --save
```

## Saved 16-note lesson

The current lesson controller is maintained in
`guitar_video_app/integrations/lesson_controller.py`. Its source was extracted from
`outputs/reference-guitar.blend`. The scene remains the source of guitar, camera,
panel and staff placement. `lesson_setup.py` installs the controller, detaches old
string transform actions and recreates the three vertical bar lines.

The lesson uses `data/demo_16_note_lesson.json`: 16 consecutive single notes,
four notes per staff, two staffs visible per page. This saved layout supports
frets 0-4. Tab rows 1-6 map to guitar objects `String_6` through `String_1` in this
particular scene. Guitar strings 1-6 use red, green, purple, cyan, blue and orange.
The active flat marker shares its string material; inactive strings stay neutral.
Vibration occurs during the first five frames of each note.

To apply the external source and save it into the existing Blender file:

```bash
cd /Users/dc/CodexProjects/guitar
/Applications/Blender.app/Contents/MacOS/Blender --background outputs/reference-guitar.blend --python scripts/install_saved_lesson.py -- --save
```

The default and staff-panel-synced adapters also recognize this lesson JSON.
Other event-chart formats keep their existing adapters. The installer embeds a
copy of the external controller in the blend for the existing Blender reload
handler; it does not automatically watch source-file changes. Re-run it after
editing the external source. No camera or panel layout is rebuilt.

This folder contains the first app-shaped structure for the offline Blender guitar lesson video workflow.

The current `.blend` scene remains the source of truth for object placement. The app prepares musical data and asks Blender to animate existing objects by name, not rebuild or move the guitar, tabs, or cameras.

## Pipeline

```text
MIDI
  -> raw_song.json
  -> guitar_chart.json
  -> Blender adapter: animation + tab overlay
  -> rendered video
```

## Structure

```text
guitar_video_app/
  core/           # MIDI, timing, note mapping, fingering, chart generation
  integrations/   # Blender, DAW, Codex boundaries
  api/            # service layer and optional HTTP API
  cli.py          # command line entry point

scripts/
  run_blender_chart.py  # script to run inside Blender Python later
```

## Important Safety Rule

Preserve transforms for:

- `LessonVerticalCamera`
- `GuitarCamera`
- `Lesson_Tabs_Demo`
- all `Lesson_Tab_*`
- all `String_*`
- all `Fret_*`
- all `Reference Guitar - *`
- all generated `Note_*` marker objects unless intentionally regenerated

## Commands

```bash
PYTHONPATH=work python -m guitar_video_app.cli midi-to-json input.mid work/data/raw_song.json
PYTHONPATH=work python -m guitar_video_app.cli chart work/data/raw_song.json work/data/guitar_chart.json --fps 30
PYTHONPATH=work python -m guitar_video_app.cli all input.mid work/data --fps 30
```

The MIDI parser requires `mido`.

## API

Optional HTTP API:

```bash
PYTHONPATH=work uvicorn guitar_video_app.api.server:app --reload
```

Endpoints:

- `GET /health`
- `POST /build/from-midi`
- `POST /build/chart`

## Blender Adapter

Run `scripts/run_blender_chart.py` inside Blender Python when the project path is importable. It calls:

```python
from guitar_video_app.integrations.blender_adapter import animate_and_prepare_render
```

That adapter loads `guitar_chart.json`, animates the existing scene objects, updates the tab overlay, optionally configures render output, and can write before/after transform snapshots.

## Live Blender Bridge

When the bridge is running inside Blender, the normal Python app can affect the live scene:

```bash
PYTHONPATH=work python3 -m guitar_video_app.cli blender-ping
PYTHONPATH=work python3 -m guitar_video_app.cli blender-send work/data/sample_guitar_chart.json
```

The bridge listens on `127.0.0.1:8765` and accepts JSON commands. Keep it local; it is meant for your machine only.

End-to-end command shape:

```bash
PYTHONPATH=work python3 -m guitar_video_app.cli render input.mid outputs/lesson.mp4 --fps 30
```

This currently builds the MIDI chart, sends it to Blender, and configures the render output path. Rendering execution can be triggered from Blender after inspection.

## Compositing over a background (piano stage)

A piano song on the PIANO_VISUAL stage (Piano look Musical notes or Particle plumes) can be rendered as a transparent foreground for a background video made separately, for example by an AI video generator, and put together in DaVinci Resolve. This project does not make the background. Test 4 s and Render full still make MP4 previews.

In the dashboard, under Render video, use the "For compositing" row:

- **Reference frames** writes one set of stills per camera shot into `data/dashboard/<song>/renders/<name> reference/`. Each set has a reference (grey floor and background), a guide (floor grid, red horizon, yellow safe box, blue space for the rising notes) and a mask (white where the piano and notes go), plus `cameras.json`. Give the reference or guide to the video generator so its scene matches the camera's perspective and horizon and keeps the masked space clear. Make one still-camera clip per shot, as long as the shot (frames in `cameras.json`).
- **Layers (PNG)** writes the whole song, full size, into `<name> layers/`: the folders `instrument`, `notes`, `shadow` and `fx` of 16-bit RGBA PNGs, and `composite.json`. It is several times slower than Render full: one second of song at half size took about 3.5 minutes for the four layers on an M1 with 8 GB, and full size takes longer.

Show in Finder opens the folder. From the command line:

```sh
Blender -b outputs/piano-visual.blend --python scripts/render_piano_visual.py -- --json piano_view.json \
    --wav final.wav --camera camera_shots.json --out renders/song-layers --layers          # all layers
Blender -b outputs/piano-visual.blend --python scripts/render_piano_visual.py -- --json piano_view.json \
    --camera camera_shots.json --out renders/song-reference --reference-frames
```

Every shot is held still in these renders (its move becomes static and every change a cut), so a still background clip lines up with it. To match the Test 4 s preview, use Static moves and Cut transitions in the Camera strip.

In Resolve (settings in `composite.json`):

1. Set the timeline to the render's fps (30) and 1080×1920.
2. Import each layer folder as an image sequence and stack, bottom to top: the background clips (one per shot, at the frames in `shots`), `shadow` (composite mode Multiply), `instrument`, `fx` (Add or Screen) and `notes` (Normal). The PNGs have straight alpha; if edges look dark or fringed, set the clip's alpha mode to Straight.
3. Add the final WAV as the audio, starting at `audio.start_frame`. The layers carry no audio.
4. Add glow in Resolve (for example Glow on the `notes` and `fx` layers). Blender's bloom is off in the layers so the glow can spread over the background.

The colours are already in Blender's AgX view, like the MP4. Formats: `docs/JSON_SCHEMA.md`, "Compositing files"; design: decision 40.

## Bass

A song can be played on a 4-string bass (E1 A1 D2 G2, MIDI 28 to 63). In the dashboard choose Bass in the Instrument select. Then:

- **Import MIDI** plans strings and frets on the bass (one finger per fret, low positions and open strings first). Notes the bass cannot play are left out.
- **Generate MIDI from WAV** listens only in the bass range. Set **Recording** first: **Bass alone** (the default, for bass-tab videos) takes each note from the pitch struck hardest at each attack; **Full band** keeps the lowest note at each moment and drops chords and harmony above it (decision 43); **Full band, extract bass first** (for bass covers over a backing track) separates the bass with Demucs and takes each note's pitch from it with pYIN (decision 44). The first Generate with it takes about as long as the audio; it needs `uv pip install --python .venv-transcribe/bin/python demucs librosa`. With it, set **Bass style**: **Fingers** (the default) also keeps soft attacks such as quiet repeated notes; **Slap or pick** keeps only clear attacks, leaving out ghost hits, dead notes and the noise of a ringing note (decision 46). Bars of a generated bass start on its roots, the long low notes, so a pickup stays a pickup, and the tempo changes only where that clearly fits more notes (decision 47); move bar 1 with First beat and Apply timing if it is still off.
- **Bass only** (next to Play) plays the bass separated from the full band at the same position, to check the tab by ear; press it again for the full audio. The first press extracts the bass when it has not been extracted yet (whatever the Recording setting), and Generate MIDI with **Full band, extract bass first** reuses it.
- **Tab files** for the bass add `"instrument": "bass"`, with strings 1 = high G to 4 = low E (`docs/JSON_SCHEMA.md`, "Tab File"). A dead note is `"muted": true`; it stays where the tab puts it.
- The tab editor shows four lines ("Bass · E A D G") under a bass-clef staff, written an octave above the sound as bass music usually is. Strings are 1 to 4 and frets 0 to 20.
- **Muted (dead) notes**: select a note and press X, or tick Muted (x) in the note editor. The note is drawn "x" on the tab, as an X notehead in the notation and as an X on the string in Blender, and it sounds as a short click. Press X again to play it normally. This works on the guitar too.
- Switching a song between guitar and bass keeps each instrument's strings and frets. A song with notes the other instrument cannot play stays where it is, with a message.

Send to Blender and renders use `outputs/bass-vertical.blend`: open it in Blender before Send. Rebuild it from the guitar scene, which is only read, with:

```sh
/Applications/Blender.app/Contents/MacOS/Blender -b outputs/v4-vertical.blend --python scripts/make_bass_scene.py
```

Design: decision 41.

## Checks

Run every verify script, the Blender ones in background Blender, with one pass/fail line each:

```sh
.venv/bin/python scripts/verify_all.py            # all checks, about 2 to 3 minutes
.venv/bin/python scripts/verify_all.py --only piano
.venv/bin/python scripts/verify_all.py --only bass  # the bass, its dashboard song and its scene
```

No check writes a scene you work in. `scripts/verify_lesson_v2.py` regenerates its own samples, `outputs/lesson-v2-tests.blend` and `outputs/lesson-v2-chords.png`. `scripts/verify_dashboard.cjs` (Playwright, with the dashboard and Blender running) is run separately.

## Blender Verification

Before changing Blender behavior, run `transform_snapshot.write_snapshot(...)` inside Blender, make the change, run it again, then compare with `compare_snapshots(...)`.

Any changed preserve-listed transform should be treated as a blocker unless the change was explicitly requested.
