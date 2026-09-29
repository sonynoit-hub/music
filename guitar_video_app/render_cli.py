from __future__ import annotations

import argparse
import json
from pathlib import Path

from guitar_video_app.api.service import build_from_midi
from guitar_video_app.integrations.blender_client import animate_chart_in_blender


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a MIDI lesson chart and send it to Blender.")
    parser.add_argument("midi")
    parser.add_argument("output_video")
    parser.add_argument("--work-dir", default="work/data")
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--execute-render", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    output_video = Path(args.output_video)
    output_video.parent.mkdir(parents=True, exist_ok=True)

    build = build_from_midi(args.midi, args.work_dir, fps=args.fps)
    blender = animate_chart_in_blender(
        build.chart_path,
        output_video_path=output_video,
        host=args.host,
        port=args.port,
    )

    payload = {
        "build": {
            "raw_song_path": str(build.raw_song_path),
            "chart_path": str(build.chart_path),
            "event_count": build.event_count,
            "bpm": build.bpm,
            "fps": build.fps,
        },
        "blender": blender,
        "execute_render_requested": args.execute_render,
        "note": (
            "This command configures Blender output and sends the chart. "
            "Use the main CLI --execute-render once the bridge command has been upgraded."
        ),
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
