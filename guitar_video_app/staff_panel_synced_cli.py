from __future__ import annotations

import argparse
import json

from guitar_video_app.integrations.blender_client_staff_panel_synced import animate_chart_in_blender, ping_blender


def main() -> None:
    parser = argparse.ArgumentParser(description="Test synced guitar markers and staff-panel tabs.")
    sub = parser.add_subparsers(dest="command", required=True)

    ping = sub.add_parser("ping")
    ping.add_argument("--host", default="127.0.0.1")
    ping.add_argument("--port", type=int, default=8769)

    send = sub.add_parser("send")
    send.add_argument("chart")
    send.add_argument("--host", default="127.0.0.1")
    send.add_argument("--port", type=int, default=8769)

    args = parser.parse_args()
    if args.command == "ping":
        print(json.dumps(ping_blender(host=args.host, port=args.port), indent=2))
    elif args.command == "send":
        print(json.dumps(animate_chart_in_blender(args.chart, host=args.host, port=args.port), indent=2))


if __name__ == "__main__":
    main()

