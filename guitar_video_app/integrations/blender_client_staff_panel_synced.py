from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any


HOST = "127.0.0.1"
PORT = 8769


def send_command(command: dict[str, Any], host: str = HOST, port: int = PORT) -> dict[str, Any]:
    payload = json.dumps(command).encode("utf-8") + b"\n"
    with socket.create_connection((host, port), timeout=float(command.get("timeout", 30))) as sock:
        sock.sendall(payload)
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode("utf-8"))


def ping_blender(host: str = HOST, port: int = PORT) -> dict[str, Any]:
    return send_command({"command": "ping", "timeout": 5}, host=host, port=port)


def animate_chart_in_blender(chart_path: str | Path, host: str = HOST, port: int = PORT) -> dict[str, Any]:
    return send_command(
        {"command": "animate_chart", "chart_path": str(chart_path), "timeout": 30},
        host=host,
        port=port,
    )

