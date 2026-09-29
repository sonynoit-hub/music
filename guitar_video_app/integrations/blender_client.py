from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any


HOST = "127.0.0.1"
PORT = 8765


def send_command(command: dict[str, Any], host: str = HOST, port: int = PORT) -> dict[str, Any]:
    payload = json.dumps(command).encode("utf-8") + b"\n"
    try:
        with socket.create_connection((host, port), timeout=float(command.get("timeout", 30))) as sock:
            sock.sendall(payload)
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
    except ConnectionRefusedError as exc:
        raise RuntimeError(_bridge_not_running_message(host, port)) from exc
    except TimeoutError as exc:
        raise RuntimeError(f"Timed out connecting to Blender bridge at {host}:{port}.") from exc
    return json.loads(data.decode("utf-8"))


def _bridge_not_running_message(host: str, port: int) -> str:
    return (
        f"Blender bridge is not running at {host}:{port}. "
        "Open Blender, then run this in Blender's Python console or Text editor:\n\n"
        "import sys\n"
        "sys.path.insert(0, '/Users/dc/Documents/Codex/2026-09-25/bef/work')\n"
        "from guitar_video_app.integrations.blender_bridge_server import start_bridge\n"
        "start_bridge()\n"
    )


def ping_blender(host: str = HOST, port: int = PORT) -> dict[str, Any]:
    return send_command({"command": "ping", "timeout": 5}, host=host, port=port)


def animate_chart_in_blender(
    chart_path: str | Path,
    output_video_path: str | Path | None = None,
    before_snapshot_path: str | Path | None = None,
    after_snapshot_path: str | Path | None = None,
    host: str = HOST,
    port: int = PORT,
) -> dict[str, Any]:
    command = {
        "command": "animate_chart",
        "chart_path": str(chart_path),
        "output_video_path": str(output_video_path) if output_video_path else None,
        "before_snapshot_path": str(before_snapshot_path) if before_snapshot_path else None,
        "after_snapshot_path": str(after_snapshot_path) if after_snapshot_path else None,
        "timeout": 30,
    }
    return send_command(command, host=host, port=port)
