from __future__ import annotations

import json
import queue
import socket
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from guitar_video_app.integrations.blender_adapter import animate_and_prepare_render


HOST = "127.0.0.1"
PORT = 8765

_server: socket.socket | None = None
_thread: threading.Thread | None = None
_requests: queue.Queue["BridgeRequest"] = queue.Queue()


@dataclass
class BridgeRequest:
    command: dict[str, Any]
    done: threading.Event
    result: dict[str, Any] | None = None
    cancelled: bool = False


def start_bridge(host: str = HOST, port: int = PORT) -> dict[str, Any]:
    """Run inside Blender. Starts a local bridge for the Python app."""
    global _server, _thread
    if _thread and _thread.is_alive():
        return {"ok": True, "status": "already_running", "host": host, "port": port}

    import bpy

    _server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _server.bind((host, port))
    _server.listen(8)

    _thread = threading.Thread(target=_serve_forever, args=(_server,), daemon=True)
    _thread.start()

    if not bpy.app.timers.is_registered(_process_pending_requests):
        bpy.app.timers.register(_process_pending_requests, persistent=True)

    return {"ok": True, "status": "started", "host": host, "port": port}


def stop_bridge() -> dict[str, Any]:
    global _server
    if _server:
        try:
            _server.close()
        finally:
            _server = None
    return {"ok": True, "status": "stopped"}


def _serve_forever(server: socket.socket) -> None:
    while True:
        try:
            conn, _addr = server.accept()
        except OSError:
            return
        threading.Thread(target=_handle_client, args=(conn,), daemon=True).start()


def _handle_client(conn: socket.socket) -> None:
    with conn:
        try:
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            command = json.loads(data.decode("utf-8"))
            request = BridgeRequest(command=command, done=threading.Event())
            _requests.put(request)
            if not request.done.wait(timeout=float(command.get("timeout", 30))):
                request.cancelled = True
            result = request.result or {"ok": False, "error": "Timed out waiting for Blender main thread"}
        except Exception as exc:
            result = {"ok": False, "error": str(exc), "traceback": traceback.format_exc()}
        conn.sendall((json.dumps(result) + "\n").encode("utf-8"))


def _process_pending_requests() -> float:
    while True:
        try:
            request = _requests.get_nowait()
        except queue.Empty:
            break
        try:
            if request.cancelled:
                continue
            request.result = _run_command(request.command)
        except Exception as exc:
            request.result = {"ok": False, "error": str(exc), "traceback": traceback.format_exc()}
        finally:
            request.done.set()
    return 0.1


def _run_command(command: dict[str, Any]) -> dict[str, Any]:
    name = command.get("command")
    if name == "dashboard_status":
        from guitar_video_app.integrations.dashboard_bridge import status
        return status()
    if name == "dashboard_save":
        import bpy
        if not bpy.data.filepath:
            raise ValueError("Save the Blender file to a location first.")
        versions = bpy.context.preferences.filepaths.save_version
        try:
            bpy.context.preferences.filepaths.save_version = 0
            bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
        finally:
            bpy.context.preferences.filepaths.save_version = versions
        return {"ok": True, "file": bpy.data.filepath}
    if name == "dashboard_sync":
        from guitar_video_app.integrations.dashboard_bridge import sync
        return sync(command)
    if name == "ping":
        return {"ok": True, "message": "pong"}
    if name == "animate_chart":
        chart_path = _required_path(command, "chart_path")
        result = animate_and_prepare_render(
            chart_path,
            output_video_path=command.get("output_video_path"),
            before_snapshot_path=command.get("before_snapshot_path"),
            after_snapshot_path=command.get("after_snapshot_path"),
        )
        return {"ok": True, "result": result}
    raise ValueError(f"Unknown Blender bridge command: {name}")


def _required_path(command: dict[str, Any], key: str) -> str:
    value = command.get(key)
    if not value:
        raise ValueError(f"Missing required command field: {key}")
    path = Path(value)
    if not path.exists():
        raise FileNotFoundError(str(path))
    return str(path)
