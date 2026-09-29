from __future__ import annotations

import json
from pathlib import Path

from guitar_video_app.integrations.blender_scene_refs import NOTE_MARKERS_COLLECTION, STRING_OBJECTS


GENERATED_MARKER_PREFIX = "App_Guitar_Note_"
MARKER_RADIUS = 0.004
MARKER_Z_OFFSET = 0.012


def load_chart(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def animate_from_chart(chart_path: str | Path) -> None:
    """Run inside Blender. Generate guitar markers from chart data and animate by frame."""
    import bpy

    chart = load_chart(chart_path)
    scene = bpy.context.scene
    scene.render.fps = int(chart.get("fps", scene.render.fps or 30))

    _hide_legacy_markers()
    _clear_generated_markers()

    max_frame = scene.frame_end
    for event_index, event in enumerate(chart["events"]):
        start = int(event["start_frame"])
        end = int(event["end_frame"])
        max_frame = max(max_frame, end)
        for note_index, note in enumerate(event["notes"]):
            string_number = int(note["string"])
            fret_number = int(note["fret"])
            _animate_string(string_number, start, end)
            location = _marker_location(string_number, fret_number)
            if location is None:
                continue
            marker = _create_marker(event_index, note_index, string_number, fret_number, location)
            _animate_marker(marker, start, end)

    scene.frame_end = max(scene.frame_end, max_frame)


def _hide_legacy_markers() -> None:
    import bpy

    collection = bpy.data.collections.get(NOTE_MARKERS_COLLECTION)
    if collection is None:
        return
    for marker in collection.objects:
        marker.hide_viewport = True
        marker.hide_render = True


def _clear_generated_markers() -> None:
    import bpy

    for obj in list(bpy.data.objects):
        if obj.name.startswith(GENERATED_MARKER_PREFIX):
            bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if mesh.name.startswith(GENERATED_MARKER_PREFIX):
            bpy.data.meshes.remove(mesh)


def _animate_string(string_number: int, start: int, end: int) -> None:
    import bpy

    string_obj = bpy.data.objects.get(STRING_OBJECTS.get(string_number, ""))
    if string_obj is None:
        return
    string_obj.animation_data_clear()
    base_scale = string_obj.scale.copy()
    string_obj.scale = base_scale
    string_obj.keyframe_insert("scale", frame=max(0, start - 1))
    string_obj.scale.x = base_scale.x * 1.035
    string_obj.scale.y = base_scale.y * 1.035
    string_obj.keyframe_insert("scale", frame=start + 1)
    string_obj.scale = base_scale
    string_obj.keyframe_insert("scale", frame=min(end, start + 5))


def _marker_location(string_number: int, fret_number: int):
    estimated = _estimated_marker_location(string_number, fret_number)
    if estimated is not None:
        return estimated
    return _legacy_marker_location(string_number, fret_number)


def _legacy_marker_location(string_number: int, fret_number: int):
    import bpy

    collection = bpy.data.collections.get(NOTE_MARKERS_COLLECTION)
    if collection is None:
        return None
    suffix = f"_S{string_number}_F{fret_number:02d}"
    for marker in collection.objects:
        if marker.name.endswith(suffix):
            return marker.location.copy()
    return None


def _estimated_marker_location(string_number: int, fret_number: int):
    import bpy
    from mathutils import Vector

    string_obj = bpy.data.objects.get(STRING_OBJECTS.get(string_number, ""))
    if string_obj is None:
        return None
    base = string_obj.location.copy()
    if fret_number == 0:
        return Vector((base.x, base.y + 0.02, base.z + MARKER_Z_OFFSET))
    current_fret = bpy.data.objects.get(f"Fret_{max(1, min(20, fret_number)):02d}")
    previous_fret = bpy.data.objects.get(f"Fret_{max(1, min(20, fret_number - 1)):02d}")
    next_fret = bpy.data.objects.get(f"Fret_{max(1, min(20, fret_number + 1)):02d}")
    if current_fret is not None and previous_fret is not None and fret_number > 1:
        y = (float(current_fret.location.y) + float(previous_fret.location.y)) / 2.0
        return Vector((base.x, y, base.z + MARKER_Z_OFFSET))
    if current_fret is not None and next_fret is not None:
        y = (float(current_fret.location.y) + float(next_fret.location.y)) / 2.0
        return Vector((base.x, y, base.z + MARKER_Z_OFFSET))
    if current_fret is not None:
        return Vector((base.x, current_fret.location.y, base.z + MARKER_Z_OFFSET))
    return Vector((base.x, base.y, base.z + MARKER_Z_OFFSET))


def _create_marker(event_index: int, note_index: int, string_number: int, fret_number: int, location):
    import bpy
    import math

    mesh_name = f"{GENERATED_MARKER_PREFIX}{event_index + 1:03d}_{note_index + 1:02d}_S{string_number}_F{fret_number:02d}"
    mesh = bpy.data.meshes.new(mesh_name)
    verts = [(0.0, 0.0, 0.0)]
    for index in range(32):
        angle = 2.0 * math.pi * index / 32
        verts.append((math.cos(angle) * MARKER_RADIUS, math.sin(angle) * MARKER_RADIUS, 0.0))
    faces = [(0, index, 1 + (index % 32)) for index in range(1, 33)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    marker = bpy.data.objects.new(mesh_name, mesh)
    marker.location = location
    material = _marker_material(string_number)
    if material:
        marker.data.materials.append(material)
    collection = bpy.data.collections.get(NOTE_MARKERS_COLLECTION)
    if collection:
        collection.objects.link(marker)
    else:
        bpy.context.collection.objects.link(marker)
    return marker


def _marker_material(string_number: int):
    import bpy

    material = bpy.data.materials.get(f"NoteMarker_String_{string_number}_Glow")
    if material:
        return material
    material = bpy.data.materials.new(f"App_Guitar_Marker_String_{string_number}")
    material.diffuse_color = _string_color(string_number)
    material.use_nodes = True
    node = next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if node:
        node.inputs["Base Color"].default_value = _string_color(string_number)
        node.inputs["Emission Color"].default_value = _string_color(string_number)
        node.inputs["Emission Strength"].default_value = 0.8
    return material


def _string_color(string_number: int) -> tuple[float, float, float, float]:
    return {
        1: (1.00, 0.42, 0.10, 1.0),
        2: (0.20, 0.45, 1.00, 1.0),
        3: (0.55, 0.25, 1.00, 1.0),
        4: (1.00, 0.92, 0.15, 1.0),
        5: (1.00, 0.16, 0.22, 1.0),
        6: (0.20, 1.00, 0.30, 1.0),
    }.get(string_number, (1.0, 1.0, 1.0, 1.0))


def _animate_marker(marker, start: int, end: int) -> None:
    marker.hide_viewport = True
    marker.hide_render = True
    marker.keyframe_insert("hide_viewport", frame=max(0, start - 1))
    marker.keyframe_insert("hide_render", frame=max(0, start - 1))

    marker.hide_viewport = False
    marker.hide_render = False
    marker.scale = (1.0, 1.0, 1.0)
    marker.keyframe_insert("hide_viewport", frame=start)
    marker.keyframe_insert("hide_render", frame=start)
    marker.keyframe_insert("scale", frame=start)

    marker.scale = (1.75, 1.75, 1.75)
    marker.keyframe_insert("scale", frame=min(end, start + 3))
    marker.scale = (1.0, 1.0, 1.0)
    marker.keyframe_insert("scale", frame=end)

    marker.hide_viewport = True
    marker.hide_render = True
    marker.keyframe_insert("hide_viewport", frame=end + 1)
    marker.keyframe_insert("hide_render", frame=end + 1)
