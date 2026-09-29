from __future__ import annotations

import json
from pathlib import Path

from guitar_video_app.integrations.blender_scene_refs import is_preserved_name


def write_snapshot(path: str | Path) -> None:
    """Run inside Blender before/after changes to prove protected transforms stayed fixed."""
    import bpy

    data = {}
    for obj in bpy.data.objects:
        if not is_preserved_name(obj.name):
            continue
        data[obj.name] = {
            "type": obj.type,
            "location": [round(v, 8) for v in obj.location],
            "rotation_euler": [round(v, 8) for v in obj.rotation_euler],
            "scale": [round(v, 8) for v in obj.scale],
            "parent": obj.parent.name if obj.parent else None,
        }
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def compare_snapshots(before_path: str | Path, after_path: str | Path) -> dict:
    before = json.loads(Path(before_path).read_text(encoding="utf-8"))
    after = json.loads(Path(after_path).read_text(encoding="utf-8"))
    changes = {}
    for name, before_value in before.items():
        after_value = after.get(name)
        if before_value != after_value:
            changes[name] = {"before": before_value, "after": after_value}
    return changes
