from __future__ import annotations

import json
from pathlib import Path

from guitar_video_app.integrations.blender_scene_refs import LESSON_CAMERA, TAB_ROOT


GENERATED_PREFIX = "App_Tab_"
NOTE_PREFIX = f"{GENERATED_PREFIX}Note_"
PANEL_NAME = f"{GENERATED_PREFIX}White_Panel"
CURSOR_NAME = f"{GENERATED_PREFIX}Cursor"
TAB_NOTE_Z = 0.018
PANEL_Z = -0.012
TAB_FONT_SIZE = 0.02
PANEL_PAD_LEFT = 0.006
PANEL_PAD_RIGHT = 0.026
PANEL_PAD_TOP = 0.012
PANEL_PAD_BOTTOM = 0.012


def load_chart(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_tab_overlay(chart_path: str | Path) -> None:
    """Run inside Blender. Place fret numbers on the existing tab staff and add a white panel."""
    import bpy

    chart = load_chart(chart_path)
    camera = bpy.data.objects.get(LESSON_CAMERA)
    root = bpy.data.objects.get(TAB_ROOT)
    if camera is None:
        raise RuntimeError(f"{LESSON_CAMERA} not found")
    if root is None:
        raise RuntimeError(f"{TAB_ROOT} not found")

    events = chart["events"]
    if not events:
        return

    line_bounds = _tab_line_bounds(root)
    x_positions = _x_positions(events, line_bounds)
    string_y = _string_y_positions(line_bounds)

    _clear_generated()
    _hide_legacy_demo_tabs()
    _create_white_panel(root, line_bounds, x_positions)
    generated_notes = _create_tab_notes(root, events, x_positions, string_y)
    _animate_tab_notes(generated_notes)
    _create_and_animate_cursor(root, events, x_positions, line_bounds)
    bpy.context.scene.frame_end = max(bpy.context.scene.frame_end, max(int(event["end_frame"]) for event in events))


def _tab_line_bounds(root) -> dict:
    import bpy
    from mathutils import Vector

    line_objects = [
        bpy.data.objects.get(f"Lesson_Tab_Line_{index}")
        for index in range(1, 7)
    ]
    line_objects = [obj for obj in line_objects if obj is not None]
    if not line_objects:
        raise RuntimeError("No Lesson_Tab_Line_* objects found")

    inv_root = root.matrix_world.inverted()
    centers = []
    xs = []
    ys = []
    for obj in line_objects:
        for corner in obj.bound_box:
            point = inv_root @ (obj.matrix_world @ Vector(corner))
            xs.append(float(point.x))
            ys.append(float(point.y))
        local_center = inv_root @ obj.matrix_world.translation
        if obj.bound_box:
            bbox_y = [
                float((inv_root @ (obj.matrix_world @ Vector(corner))).y)
                for corner in obj.bound_box
            ]
            center_y = (min(bbox_y) + max(bbox_y)) / 2.0
        else:
            center_y = float(local_center.y)
        centers.append(center_y)

    centers = sorted(set(round(value, 6) for value in centers), reverse=True)
    if len(centers) < 6:
        min_y = min(ys)
        max_y = max(ys)
        step = (max_y - min_y) / 5.0
        centers = [max_y - step * index for index in range(6)]

    return {
        "min_x": min(xs),
        "max_x": max(xs),
        "min_y": min(ys),
        "max_y": max(ys),
        "line_y": centers[:6],
    }


def _x_positions(events: list[dict], line_bounds: dict) -> list[float]:
    left = line_bounds["min_x"] + PANEL_PAD_LEFT
    right = line_bounds["max_x"] - PANEL_PAD_RIGHT
    if len(events) == 1:
        return [left]
    step = (right - left) / (len(events) - 1)
    return [left + step * index for index in range(len(events))]


def _string_y_positions(line_bounds: dict) -> dict[int, float]:
    # Standard tab: string 1/high E is the top line, string 6/low E is the bottom line.
    line_y = line_bounds["line_y"]
    return {string: line_y[string - 1] for string in range(1, min(6, len(line_y)) + 1)}


def _clear_generated() -> None:
    import bpy

    for obj in list(bpy.data.objects):
        if obj.name.startswith(GENERATED_PREFIX):
            bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if mesh.name.startswith(GENERATED_PREFIX):
            bpy.data.meshes.remove(mesh)
    for curve in list(bpy.data.curves):
        if curve.name.startswith(GENERATED_PREFIX):
            bpy.data.curves.remove(curve)


def _hide_legacy_demo_tabs() -> None:
    import bpy

    prefixes = ("Lesson_Tab_Note_", "Lesson_Tab_Bar_")
    names = {"Lesson_Tab_Cursor"}
    for obj in bpy.data.objects:
        if obj.name in names or any(obj.name.startswith(prefix) for prefix in prefixes):
            obj.hide_viewport = True
            obj.hide_render = True


def _create_white_panel(root, line_bounds: dict, x_positions: list[float]) -> None:
    import bpy

    min_x = line_bounds["min_x"] - PANEL_PAD_LEFT
    max_x = line_bounds["max_x"] + PANEL_PAD_RIGHT
    min_y = line_bounds["min_y"] - PANEL_PAD_BOTTOM
    max_y = line_bounds["max_y"] + PANEL_PAD_TOP
    verts = [
        (min_x, min_y, PANEL_Z),
        (max_x, min_y, PANEL_Z),
        (max_x, max_y, PANEL_Z),
        (min_x, max_y, PANEL_Z),
    ]
    mesh = bpy.data.meshes.new(PANEL_NAME)
    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    mesh.update()
    panel = bpy.data.objects.new(PANEL_NAME, mesh)
    panel.parent = root
    material = bpy.data.materials.get("App_Tab_White_Panel")
    if material is None:
        material = bpy.data.materials.new("App_Tab_White_Panel")
        material.diffuse_color = (1.0, 1.0, 1.0, 1.0)
        material.use_nodes = True
        node = next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if node:
            node.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            node.inputs["Roughness"].default_value = 0.65
    panel.data.materials.append(material)
    bpy.context.collection.objects.link(panel)


def _create_tab_notes(root, events: list[dict], x_positions: list[float], string_y: dict[int, float]) -> list[tuple[object, int, int]]:
    import bpy

    material = bpy.data.materials.get("Lesson Tabs | black ink")
    generated = []
    for event_index, event in enumerate(events):
        x = x_positions[event_index]
        start_frame = int(event["start_frame"])
        end_frame = int(event["end_frame"])
        for note_index, note in enumerate(event["notes"]):
            string_number = int(note["string"])
            y = string_y.get(string_number)
            if y is None:
                continue
            curve = bpy.data.curves.new(f"{NOTE_PREFIX}{event_index + 1:03d}_{note_index + 1:02d}", "FONT")
            curve.body = str(note["fret"])
            curve.align_x = "CENTER"
            curve.align_y = "CENTER"
            curve.size = TAB_FONT_SIZE
            obj = bpy.data.objects.new(curve.name, curve)
            obj.parent = root
            obj.location = (x, y, TAB_NOTE_Z)
            if material:
                obj.data.materials.append(material)
            bpy.context.collection.objects.link(obj)
            generated.append((obj, start_frame, end_frame))
    return generated


def _animate_tab_notes(generated: list[tuple[object, int, int]]) -> None:
    for obj, start, end in generated:
        obj.animation_data_clear()
        obj.scale = (1.0, 1.0, 1.0)
        obj.keyframe_insert(data_path="scale", frame=max(0, start - 1))
        obj.scale = (1.7, 1.7, 1.7)
        obj.keyframe_insert(data_path="scale", frame=start + 2)
        obj.scale = (1.0, 1.0, 1.0)
        obj.keyframe_insert(data_path="scale", frame=min(end, start + 8))


def _create_and_animate_cursor(root, events: list[dict], x_positions: list[float], line_bounds: dict) -> None:
    import bpy

    min_y = line_bounds["min_y"] - PANEL_PAD_BOTTOM * 0.55
    max_y = line_bounds["max_y"] + PANEL_PAD_TOP * 0.55
    width = 0.0035
    verts = [
        (-width / 2.0, min_y, 0.03),
        (width / 2.0, min_y, 0.03),
        (width / 2.0, max_y, 0.03),
        (-width / 2.0, max_y, 0.03),
    ]
    mesh = bpy.data.meshes.new(CURSOR_NAME)
    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    mesh.update()
    cursor = bpy.data.objects.new(CURSOR_NAME, mesh)
    cursor.parent = root
    material = bpy.data.materials.get("Lesson Tabs | cursor blue")
    if material:
        cursor.data.materials.append(material)
    bpy.context.collection.objects.link(cursor)

    for index, event in enumerate(events):
        frame = int(event["start_frame"])
        cursor.location.x = x_positions[min(index, len(x_positions) - 1)]
        cursor.location.y = 0.0
        cursor.location.z = 0.0
        cursor.scale = (1.0, 1.0, 1.0)
        cursor.keyframe_insert(data_path="location", frame=frame)
        cursor.keyframe_insert(data_path="scale", frame=max(0, frame - 1))
        cursor.scale = (1.0, 1.7, 1.0)
        cursor.keyframe_insert(data_path="scale", frame=frame + 2)
        cursor.scale = (1.0, 1.0, 1.0)
        cursor.keyframe_insert(data_path="scale", frame=frame + 7)
