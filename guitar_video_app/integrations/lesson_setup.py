"""Install the saved single-note lesson in the existing guitar scene."""
from __future__ import annotations

import json
from pathlib import Path


def validate_lesson(data: dict) -> None:
    notes = data.get("notes", [])
    if len(notes) != 16 or len(data.get("staff_pages", [])) != 2:
        raise ValueError("This saved layout requires 16 notes in two pages of two staffs.")
    for index, note in enumerate(notes, 1):
        if (note["index"] != index or note["staff"] != (index - 1) // 4 + 1
                or not 1 <= note["string"] <= 6 or note["fret"] not in range(5)
                or str(note.get("label", note["fret"])) != str(note["fret"])):
            raise ValueError("Invalid note order, staff, string or fret (supported frets: 0-4).")
        if note["duration_frames"] <= 0:
            raise ValueError("Note duration must be positive.")
        if index < len(notes) and note["frame"] + note["duration_frames"] != notes[index]["frame"]:
            raise ValueError("The saved lesson controller requires consecutive single notes.")
    if (data["staff_pages"][0]["staffs"] != [1, 2]
            or data["staff_pages"][1]["staffs"] != [3, 4]
            or data["page_switch_frame"] != notes[8]["frame"]
            or data["frame_start"] != notes[0]["frame"]
            or data["frame_end"] != notes[-1]["frame"] + notes[-1]["duration_frames"]):
        raise ValueError("Page and timeline boundaries must match the note timings.")


def build_bar_lines(strings: int = 6) -> None:
    import bpy
    from mathutils import Matrix, Vector
    from bpy_extras.object_utils import world_to_camera_view

    scene = bpy.context.scene
    group = bpy.data.objects['App_Tab_Backdrop_Panel_Cursor_Lines_GROUP']
    collection = bpy.data.collections['App_Tab_Backdrop_Panel_Cursor_Lines_COLLECTION']

    def endpoints(name):
        obj = bpy.data.objects[name]
        points = [obj.matrix_world @ Vector(p.co[:3])
                  for sp in obj.data.splines for p in sp.points]
        points += [obj.matrix_world @ p.co
                   for sp in obj.data.splines for p in sp.bezier_points]
        points.sort(key=lambda p: world_to_camera_view(scene, scene.camera, p).x)
        return points[0], points[-1]

    top, bottom = endpoints('Lesson_Tab_Line_1'), endpoints(f'Lesson_Tab_Line_{strings}')
    line = bpy.data.objects['Lesson_Tab_Line_1']
    inverse = group.matrix_world.inverted()
    for index, fraction in enumerate((0.0, 0.5, 1.0), 1):
        name = f'Lesson_Tab_Bar_{index}'
        obj = bpy.data.objects.get(name)
        if obj is None:
            obj = bpy.data.objects.new(name, bpy.data.curves.new(name, 'CURVE'))
        original_depth = obj.data.bevel_depth or line.get('Lesson_Original_Bevel_Depth', line.data.bevel_depth)
        original_material = obj.data.materials[0] if obj.data.materials else line.material_slots[0].material
        if obj.name not in collection.objects:
            collection.objects.link(obj)
        obj.animation_data_clear()
        curve = obj.data
        curve.animation_data_clear()
        curve.splines.clear()
        curve.dimensions = '3D'
        curve.bevel_depth = original_depth
        curve.bevel_resolution = line.data.bevel_resolution
        curve.use_fill_caps = True
        spline = curve.splines.new('POLY')
        spline.points.add(1)
        obj.parent = group
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_basis = Matrix.Identity(4)
        for point, ends in zip(spline.points, (top, bottom)):
            point.co = (*(inverse @ ends[0].lerp(ends[1], fraction)), 1.0)
        curve.materials.clear()
        curve.materials.append(original_material)
        obj.hide_viewport = False
        obj.hide_set(False)
        obj.hide_render = False


def install_lesson(chart_path: str | Path) -> dict:
    import bpy
    from guitar_video_app.integrations import lesson_controller

    data = json.loads(Path(chart_path).read_text(encoding='utf-8'))
    if data.get('version') == 2:
        return install_v2(data)
    validate_lesson(data)
    bpy.app.handlers.frame_change_post[:] = [
        h for h in bpy.app.handlers.frame_change_post
        if getattr(h, '__name__', '') != 'guitar_lesson_v2_controller'
    ]
    for obj in bpy.data.objects:
        if obj.name.startswith(('Lesson_V2_Marker_', 'Demo_Tab_Seg_')):
            obj.hide_set(True)
            obj.hide_render = True
    required = ['App_Tab_White_Panel', 'App_Tab_Cursor_Visible_6_String_Length',
                'App_Tab_Backdrop_Panel_Cursor_Lines_GROUP', 'Nut']
    required += [f'String_{i}' for i in range(1, 7)]
    required += [f'Lesson_Tab_Line_{i}' for i in range(1, 7)]
    required += [f'Fret_{i:02d}' for i in range(1, 5)]
    missing = [name for name in required if name not in bpy.data.objects]
    if missing or bpy.context.scene.camera is None:
        raise ValueError(f'Open the saved guitar lesson scene first. Missing objects: {missing}')

    # Persist the external source in the blend for the existing reload handler.
    for name, content in (
        ('Demo_16_Note_Tab_Controller.py', Path(lesson_controller.__file__).read_text(encoding='utf-8')
         + '\nregister_demo_16_note_handler()\n'),
        ('Demo_16_Note_Tab_Timing_JSON', json.dumps(data, indent=2)),
    ):
        text = bpy.data.texts.get(name) or bpy.data.texts.new(name)
        text.clear()
        text.write(content)

    for i in range(1, 7):
        obj = bpy.data.objects[f'String_{i}']
        action = obj.animation_data.action if obj.animation_data else None
        if action:
            for layer in action.layers:
                for strip in layer.strips:
                    for bag in strip.channelbags:
                        for curve in bag.fcurves:
                            if curve.data_path in ('location', 'scale') and curve.keyframe_points:
                                getattr(obj, curve.data_path)[curve.array_index] = curve.keyframe_points[0].co.y
            obj.animation_data.action = None
    build_bar_lines()
    scene = bpy.context.scene
    scene.frame_start = int(data['frame_start'])
    scene.frame_end = int(data['frame_end']) - 1
    lesson_controller.register_demo_16_note_handler()
    return {'guitar_animation': 'lesson_controller', 'tab_overlay': 'four_note_bars',
            'timing': 'shared_json_frames', 'note_count': len(data['notes'])}


def install_v2(data):
    import bpy
    from guitar_video_app.instruments.guitar.view import prepare, view_spec
    from guitar_video_app.integrations import lesson_controller as legacy
    from guitar_video_app.integrations import lesson_controller_v2 as runtime
    from guitar_video_app.integrations.blender_scene_refs import check_lesson_scene
    lesson = prepare(data)
    strings = view_spec(data).strings
    check_lesson_scene(bpy.context.scene, strings, bpy.data.objects)
    for i in range(1, strings + 1):
        obj = bpy.data.objects[f'String_{i}']
        if obj.animation_data and obj.animation_data.action:
            raise ValueError('Remove legacy string transform actions before installing V2.')
    text = bpy.data.texts.get('Lesson_V2_JSON') or bpy.data.texts.new('Lesson_V2_JSON')
    text.clear()
    text.write(json.dumps(data, indent=2))
    template = legacy._ensure_flat_marker(legacy._ensure_materials()[3])
    for i in range(1, strings + 1):
        name = f'Lesson_V2_Marker_{i}'
        if name not in bpy.data.objects:
            marker = bpy.data.objects.new(name, template.data.copy())
            bpy.context.scene.collection.objects.link(marker)
            marker.show_in_front = True
    build_bar_lines(strings)
    scene = bpy.context.scene
    scene.render.fps = lesson['fps']
    scene.render.fps_base = 1
    scene.frame_start = 0
    scene.frame_end = lesson['frame_end']
    # The existing startup loader runs this text; source remains external.
    root = str(Path(__file__).resolve().parents[2])
    loader = bpy.data.texts.get('Demo_16_Note_Tab_Controller.py') or bpy.data.texts.new('Demo_16_Note_Tab_Controller.py')
    loader.clear()
    loader.write('import sys\n' + f'sys.path.insert(0, {root!r})\n'
                 + 'from guitar_video_app.integrations.lesson_controller_v2 import register\nregister()\n')
    runtime.register()
    return {'version': 2, 'note_count': len(lesson['notes']), 'timing': 'beats', 'tab_overlay': 'two_measures_per_page'}
