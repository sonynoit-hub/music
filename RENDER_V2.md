# Render-Capable Blender Bridge

This is an opt-in v2 bridge that leaves the original `8765` bridge alone.

## Start v2 Bridge In Blender

Run this in Blender's Python console or Text editor:

```python
import sys
sys.path.insert(0, "/Users/dc/Documents/Codex/2026-09-25/bef/work")

from guitar_video_app.integrations.blender_bridge_server_v2 import start_bridge
start_bridge()
```

It listens on:

```text
127.0.0.1:8766
```

## Test Connection

```bash
cd /Users/dc/Documents/Codex/2026-09-25/bef
PYTHONPATH=work python3 -m guitar_video_app.render_cli_v2 ping
```

## Build And Send Without Rendering

```bash
PYTHONPATH=work python3 -m guitar_video_app.render_cli_v2 render input.mid outputs/lesson.mp4 --fps 30
```

## Build, Send, And Render

```bash
PYTHONPATH=work python3 -m guitar_video_app.render_cli_v2 render input.mid outputs/lesson.mp4 --fps 30 --execute-render
```

This command:

1. Parses MIDI.
2. Builds `raw_song.json`.
3. Builds `guitar_chart.json`.
4. Sends the chart to Blender.
5. Configures the output video path.
6. Optionally starts Blender's animation render.

