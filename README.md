# Guitar Video App

## Project Context For Codex

Start future project work by reading `AGENTS.md`.

Detailed project memory is split by topic:

- `docs/ARCHITECTURE.md` for system design and component ownership.
- `docs/JSON_SCHEMA.md` for the Python-to-Blender JSON contract.
- `docs/MUSIC_RULES.md` for timing, beat, measure, tempo, and audio sync rules.
- `docs/ROADMAP.md` for current scope and later work.
- `docs/DECISIONS.md` for architectural decisions and rationale.
- `skills/music-pipeline/SKILL.md` for the repeatable new-song workflow.

The latest known Blender scene candidate is `outputs/v3-tests.blend`.

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

## Blender Verification

Before changing Blender behavior, run `transform_snapshot.write_snapshot(...)` inside Blender, make the change, run it again, then compare with `compare_snapshots(...)`.

Any changed preserve-listed transform should be treated as a blocker unless the change was explicitly requested.
