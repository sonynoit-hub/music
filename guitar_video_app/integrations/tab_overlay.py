from __future__ import annotations

import json
from pathlib import Path

from guitar_video_app.integrations.blender_scene_refs import LESSON_CAMERA, TAB_ROOT

GENERATED_TAB_PREFIX = "App_Tab_Note_"
STRING_ROW_GAP = 0.015696
STRING_1_Y = -0.20576
TAB_NOTE_Z = 0.012
TAB_FONT_SIZE = 0.018


def load_chart(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_tab_overlay(chart_path: str | Path) -> None:
    """Run inside Blender. Keeps the existing tab root/camera position unchanged."""
    import bpy

    chart = load_chart(chart_path)
    camera = bpy.data.objects.get(LESSON_CAMERA)
    root = bpy.data.objects.get(TAB_ROOT)
    if camera is None:
        raise RuntimeError(f"{LESSON_CAMERA} not found")
    if root is None:
        raise RuntimeError(f"{TAB_ROOT} not found")

    # This module intentionally avoids changing root/camera transforms.
    events = chart["events"]
    if not events:
        return

    x_positions = _tab_x_positions_for_events(events)
    _clear_generated_tab_notes()
    _create_tab_notes(events, x_positions)
    _animate_existing_cursor(events, x_positions)
    bpy.context.scene.frame_end = max(bpy.context.scene.frame_end, max(int(event["end_frame"]) for event in events))


def _animate_existing_cursor(events: list[dict], x_positions: list[float]) -> None:
    import bpy

    cursor = bpy.data.objects.get("Lesson_Tab_Cursor")
    if cursor is None:
        return

    if not x_positions:
        return

    cursor.animation_data_clear()
    base_location = cursor.location.copy()
    for index, event in enumerate(events):
        frame = int(event["start_frame"])
        cursor.location.x = x_positions[min(index, len(x_positions) - 1)]
        cursor.location.y = base_location.y
        cursor.location.z = base_location.z
        cursor.keyframe_insert(data_path="location", frame=frame)


def _tab_x_positions_for_events(events: list[dict]) -> list[float]:
    existing = _existing_demo_tab_note_x_positions()
    if len(existing) >= len(events):
        return existing[: len(events)]
    if existing:
        left = min(existing)
        right = max(existing)
    else:
        left, right = -0.233, 0.203
    if len(events) == 1:
        return [left]
    step = (right - left) / (len(events) - 1)
    return [left + step * index for index in range(len(events))]


def _existing_demo_tab_note_x_positions() -> list[float]:
    import bpy

    notes = [
        obj
        for obj in bpy.data.objects
        if obj.name.startswith("Lesson_Tab_Note_") and obj.type == "FONT"
    ]
    notes.sort(key=lambda obj: obj.name)
    return [float(obj.location.x) for obj in notes]


def _clear_generated_tab_notes() -> None:
    import bpy

    for obj in list(bpy.data.objects):
        if obj.name.startswith(GENERATED_TAB_PREFIX):
            bpy.data.objects.remove(obj, do_unlink=True)
    for curve in list(bpy.data.curves):
        if curve.name.startswith(GENERATED_TAB_PREFIX):
            bpy.data.curves.remove(curve)


def _create_tab_notes(events: list[dict], x_positions: list[float]) -> None:
    import bpy

    root = bpy.data.objects.get(TAB_ROOT)
    if root is None:
        return
    material = bpy.data.materials.get("Lesson Tabs | black ink")
    for event_index, event in enumerate(events):
        x = x_positions[event_index]
        for note_index, note in enumerate(event["notes"]):
            string_number = int(note["string"])
            fret = str(note["fret"])
            curve = bpy.data.curves.new(f"{GENERATED_TAB_PREFIX}{event_index + 1:03d}_{note_index + 1:02d}", "FONT")
            curve.body = fret
            curve.align_x = "CENTER"
            curve.align_y = "CENTER"
            curve.size = TAB_FONT_SIZE
            obj = bpy.data.objects.new(curve.name, curve)
            obj.parent = root
            obj.location = (x, _string_y(string_number), TAB_NOTE_Z)
            if material:
                obj.data.materials.append(material)
            bpy.context.collection.objects.link(obj)


def _string_y(string_number: int) -> float:
    return STRING_1_Y - (string_number - 1) * STRING_ROW_GAP
