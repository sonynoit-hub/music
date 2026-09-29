from __future__ import annotations

import argparse
import json
from pathlib import Path

from guitar_video_app.api.service import build_chart_from_raw_json, build_from_midi
from guitar_video_app.core.midi_to_json import write_raw_json
from guitar_video_app.core.music_analyzer import normalize_midi_file
from guitar_video_app.core.normalized_song import write_normalized_song
from guitar_video_app.core.normalized_to_lesson_v2 import convert_normalized_file_to_lesson_v2
from guitar_video_app.integrations.blender_client import animate_chart_in_blender, ping_blender


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline guitar lesson video app")
    sub = parser.add_subparsers(dest="command", required=True)

    midi = sub.add_parser("midi-to-json")
    midi.add_argument("midi")
    midi.add_argument("output")

    normalize = sub.add_parser("normalize-midi")
    normalize.add_argument("midi")
    normalize.add_argument("output")
    normalize.add_argument("--wav")
    normalize.add_argument("--audio-offset", type=float, default=0.0)
    normalize.add_argument("--title")

    to_v2 = sub.add_parser("normalized-to-v2")
    to_v2.add_argument("normalized_json")
    to_v2.add_argument("output")
    to_v2.add_argument("--fps", type=int, default=60)
    to_v2.add_argument("--name")

    chart = sub.add_parser("chart")
    chart.add_argument("raw_json")
    chart.add_argument("output")
    chart.add_argument("--fps", type=float, default=30.0)

    all_cmd = sub.add_parser("all")
    all_cmd.add_argument("midi")
    all_cmd.add_argument("output_dir")
    all_cmd.add_argument("--fps", type=float, default=30.0)

    ping = sub.add_parser("blender-ping")
    ping.add_argument("--host", default="127.0.0.1")
    ping.add_argument("--port", type=int, default=8765)

    send = sub.add_parser("blender-send")
    send.add_argument("chart")
    send.add_argument("--output-video")
    send.add_argument("--before-snapshot")
    send.add_argument("--after-snapshot")
    send.add_argument("--host", default="127.0.0.1")
    send.add_argument("--port", type=int, default=8765)

    render = sub.add_parser("render")
    render.add_argument("midi")
    render.add_argument("output_video")
    render.add_argument("--work-dir", default="work/data")
    render.add_argument("--fps", type=float, default=30.0)
    render.add_argument("--host", default="127.0.0.1")
    render.add_argument("--port", type=int, default=8765)

    args = parser.parse_args()
    if args.command == "midi-to-json":
        write_raw_json(args.midi, args.output)
    elif args.command == "normalize-midi":
        normalized = normalize_midi_file(
            args.midi,
            wav_path=args.wav,
            audio_offset=args.audio_offset,
            title=args.title,
        )
        write_normalized_song(normalized, args.output)
    elif args.command == "normalized-to-v2":
        convert_normalized_file_to_lesson_v2(
            args.normalized_json,
            args.output,
            fps=args.fps,
            name=args.name,
        )
    elif args.command == "chart":
        result = build_chart_from_raw_json(args.raw_json, args.output, fps=args.fps)
        print(json.dumps(_result_payload(result), indent=2))
    elif args.command == "all":
        result = build_from_midi(args.midi, args.output_dir, fps=args.fps)
        print(json.dumps(_result_payload(result), indent=2))
    elif args.command == "blender-ping":
        print(json.dumps(ping_blender(host=args.host, port=args.port), indent=2))
    elif args.command == "blender-send":
        result = animate_chart_in_blender(
            args.chart,
            output_video_path=args.output_video,
            before_snapshot_path=args.before_snapshot,
            after_snapshot_path=args.after_snapshot,
            host=args.host,
            port=args.port,
        )
        print(json.dumps(result, indent=2))
    elif args.command == "render":
        result = build_from_midi(args.midi, args.work_dir, fps=args.fps)
        blender_result = animate_chart_in_blender(
            result.chart_path,
            output_video_path=args.output_video,
            host=args.host,
            port=args.port,
        )
        print(json.dumps({"build": _result_payload(result), "blender": blender_result}, indent=2))


def _result_payload(result) -> dict:
    return {
        "raw_song_path": str(result.raw_song_path),
        "chart_path": str(result.chart_path),
        "event_count": result.event_count,
        "bpm": result.bpm,
        "fps": result.fps,
    }


if __name__ == "__main__":
    main()
