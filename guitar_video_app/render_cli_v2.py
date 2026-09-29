from __future__ import annotations

import argparse
import json
from pathlib import Path

from guitar_video_app.api.service import build_from_midi
from guitar_video_app.integrations.blender_client_v2 import animate_chart_in_blender, ping_blender


def main() -> None:
    parser = argparse.ArgumentParser(description="Build MIDI chart, send to Blender, and optionally render.")
    sub = parser.add_subparsers(dest="command", required=True)

    ping = sub.add_parser("ping")
    ping.add_argument("--host", default="127.0.0.1")
    ping.add_argument("--port", type=int, default=8766)

    render = sub.add_parser("render")
    render.add_argument("midi")
    render.add_argument("output_video")
    render.add_argument("--work-dir", default="work/data")
    render.add_argument("--fps", type=float, default=30.0)
    render.add_argument("--execute-render", action="store_true")
    render.add_argument("--host", default="127.0.0.1")
    render.add_argument("--port", type=int, default=8766)

    args = parser.parse_args()
    if args.command == "ping":
        print(json.dumps(ping_blender(host=args.host, port=args.port), indent=2))
        return

    output_video = Path(args.output_video)
    output_video.parent.mkdir(parents=True, exist_ok=True)
    build = build_from_midi(args.midi, args.work_dir, fps=args.fps)
    blender = animate_chart_in_blender(
        build.chart_path,
        output_video_path=output_video,
        execute_render=args.execute_render,
        host=args.host,
        port=args.port,
    )
    print(
        json.dumps(
            {
                "build": {
                    "raw_song_path": str(build.raw_song_path),
                    "chart_path": str(build.chart_path),
                    "event_count": build.event_count,
                    "bpm": build.bpm,
                    "fps": build.fps,
                },
                "blender": blender,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
