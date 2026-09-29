from __future__ import annotations

import argparse
import json

from guitar_video_app.integrations.blender_adapter import animate_and_prepare_render


def main() -> None:
    parser = argparse.ArgumentParser(description="Run chart animation inside Blender Python.")
    parser.add_argument("chart")
    parser.add_argument("--output-video")
    parser.add_argument("--before-snapshot")
    parser.add_argument("--after-snapshot")
    args = parser.parse_args()

    result = animate_and_prepare_render(
        args.chart,
        output_video_path=args.output_video,
        before_snapshot_path=args.before_snapshot,
        after_snapshot_path=args.after_snapshot,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

