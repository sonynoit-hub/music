from __future__ import annotations

import json
from pathlib import Path

from guitar_video_app.integrations.blender_scene_refs import NOTE_MARKERS_COLLECTION, STRING_OBJECTS


def load_chart(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def animate_from_chart(chart_path: str | Path) -> None:
    """Run inside Blender. Uses existing objects and does not reposition the guitar."""
    import bpy

    chart = load_chart(chart_path)
    scene = bpy.context.scene
    scene.render.fps = int(chart.get("fps", scene.render.fps or 30))

    max_frame = scene.frame_end
    _reset_matching_marker_visibility()

    for event in chart["events"]:
        start = int(event["start_frame"])
        end = int(event["end_frame"])
        max_frame = max(max_frame, end)
        for note in event["notes"]:
            string_number = int(note["string"])
            fret_number = int(note["fret"])
            string_obj = bpy.data.objects.get(STRING_OBJECTS[string_number])
            if string_obj is None:
                continue
            _key_string_pulse(string_obj, start, end)
            marker = _find_existing_marker(string_number, fret_number)
            if marker is not None:
                _key_marker_visibility(marker, start, end)

    scene.frame_end = max(scene.frame_end, max_frame)


def _key_string_pulse(obj, start: int, end: int) -> None:
    obj.animation_data_clear()
    base_scale = obj.scale.copy()
    obj.keyframe_insert("scale", frame=max(0, start - 1))
    obj.scale = base_scale
    obj.scale.x = base_scale.x * 1.035
    obj.scale.y = base_scale.y * 1.035
    obj.keyframe_insert("scale", frame=start + 1)
    obj.scale = base_scale
    obj.keyframe_insert("scale", frame=min(end, start + 5))


def _reset_matching_marker_visibility() -> None:
    import bpy

    collection = bpy.data.collections.get(NOTE_MARKERS_COLLECTION)
    if collection is None:
        return
    for marker in collection.objects:
        marker.animation_data_clear()
        marker.hide_viewport = True
        marker.hide_render = True


def _find_existing_marker(string_number: int, fret_number: int):
    import bpy

    collection = bpy.data.collections.get(NOTE_MARKERS_COLLECTION)
    if collection is None:
        return None
    suffix = f"_S{string_number}_F{fret_number:02d}"
    for marker in collection.objects:
        if marker.name.endswith(suffix):
            return marker
    return None


def _key_marker_visibility(marker, start: int, end: int) -> None:
    marker.hide_viewport = True
    marker.hide_render = True
    marker.keyframe_insert("hide_viewport", frame=max(0, start - 1))
    marker.keyframe_insert("hide_render", frame=max(0, start - 1))
    marker.hide_viewport = False
    marker.hide_render = False
    marker.keyframe_insert("hide_viewport", frame=start)
    marker.keyframe_insert("hide_render", frame=start)
    marker.keyframe_insert("scale", frame=start)
    marker.scale = (1.7, 1.7, 1.7)
    marker.keyframe_insert("scale", frame=min(end, start + 3))
    marker.scale = (1.0, 1.0, 1.0)
    marker.keyframe_insert("scale", frame=end)
    marker.hide_viewport = True
    marker.hide_render = True
    marker.keyframe_insert("hide_viewport", frame=end + 1)
    marker.keyframe_insert("hide_render", frame=end + 1)
