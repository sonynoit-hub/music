"""Polyphonic lesson visuals, sharing the existing scene geometry helpers."""
import json
import math
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
from guitar_video_app.instruments.guitar.view import prepare, view_spec
from guitar_video_app.music.lesson import seconds_between, state
from guitar_video_app.integrations import lesson_controller as legacy

HANDLER = 'guitar_lesson_v2_controller'
# The scene names its strings from thick bass to thin treble (legacy.string_object).
_lesson = None
_strings = 6  # strings of the installed view's instrument: 6 guitar, 4 bass
_draw_key = None
_retriggered = set()
RETRIGGER_GAP_SECONDS = 0.1


def _retriggered_notes(lesson):
    """IDs of notes followed, with no gap, by the same fret on the same string."""
    previous, ids = {}, set()
    for note in lesson['notes']:
        before = previous.get(note['string'])
        if before and before['fret'] == note['fret'] and before['end'] == note['start']:
            ids.add(before['id'])
        previous[note['string']] = note
    return ids


def _in_retrigger_gap(lesson, note, position):
    if note['id'] not in _retriggered:
        return False
    gap = min(RETRIGGER_GAP_SECONDS, seconds_between(lesson, note['start'], note['end']) / 2)
    return seconds_between(lesson, position, note['end']) <= gap


def _mute_mesh(string):
    """The X shown instead of the round marker on a string playing a muted note; one mesh per string
    so each takes its string's colour."""
    name = f'Lesson_V2_Mute_X_{string}'
    mesh = bpy.data.meshes.get(name)
    if mesh is None:
        mesh = bpy.data.meshes.new(name)
        arm, width = 0.0075, 0.0016
        verts, faces = [], []
        for angle in (math.pi / 4, -math.pi / 4):
            c, s = math.cos(angle), math.sin(angle)
            base = len(verts)
            verts += [(c * x - s * y, s * x + c * y, 0) for x, y in
                      ((-arm, -width), (arm, -width), (arm, width), (-arm, width))]
            faces.append((base, base + 1, base + 2, base + 3))
        mesh.from_pydata(verts, [], faces)
        mesh.update()
    return mesh


def _set_marker_shape(marker, muted):
    if 'Lesson_Disc_Mesh' not in marker:
        marker['Lesson_Disc_Mesh'] = marker.data.name
    disc = bpy.data.meshes.get(marker['Lesson_Disc_Mesh'])
    target = _mute_mesh(int(marker.name.rsplit('_', 1)[1])) if muted else disc
    if target is not None and marker.data != target:
        marker.data = target


def _draw_number(scene, cam, slot, label, x, y, height, depth, material):
    name = f'Lesson_Tab_Number_{slot:03d}'
    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, bpy.data.curves.new(name, 'FONT'))
        scene.collection.objects.link(obj)
    obj.data.body = label
    obj.data.align_x = 'CENTER'
    obj.data.size = 0.02
    obj.data.extrude = 0
    obj.data.bevel_depth = 0
    obj.data.materials.clear()
    obj.data.materials.append(material)
    obj.rotation_euler = cam.matrix_world.to_euler()
    obj.location = legacy._camera_overlay_point(scene, cam, x, y, depth)
    obj.hide_set(False)
    obj.hide_render = False
    obj.show_in_front = True
    bpy.context.view_layer.update()
    box = legacy._bbox(scene, cam, obj)
    obj.data.size *= height / max(1e-8, box[3]-box[1])
    bpy.context.view_layer.update()
    legacy._move_camera_center(scene, cam, obj, x, y)
    bpy.context.view_layer.update()
    return legacy._bbox(scene, cam, obj)


def _staff_number_gaps(scene, cam, slots):
    """Cut only the staff centerlines under each displayed fret label."""
    for string, ranges in slots.items():
        obj = string
        points = legacy._curve_points_world(obj)
        points.sort(key=lambda p: world_to_camera_view(scene, cam, p).x)
        a, b = points[0], points[-1]
        xa = world_to_camera_view(scene, cam, a).x
        xb = world_to_camera_view(scene, cam, b).x
        padding = (xb - xa) * 0.003
        # Clamp both ends: a gap past the line end would otherwise lengthen the line.
        gaps = sorted((min(0.99999, max(0.00001, (lo-padding-xa)/(xb-xa))),
                       min(0.99999, max(0.00001, (hi+padding-xa)/(xb-xa)))) for lo,hi in ranges)
        spans, end = [], 0.0
        for lo, hi in gaps:
            if lo > end:
                spans.append((end,lo))
            end = max(end,hi)
        if end < 1:
            spans.append((end,1.0))
        inverse = obj.matrix_world.inverted()
        obj.data.splines.clear()
        for lo,hi in spans:
            spline = obj.data.splines.new('POLY')
            spline.points.add(1)
            spline.points[0].co = (*(inverse @ a.lerp(b,lo)),1)
            spline.points[1].co = (*(inverse @ a.lerp(b,hi)),1)
        obj.data.update_tag()


def update(scene):
    global _draw_key
    lesson = _lesson
    position, page, active = state(lesson, scene.frame_current + scene.frame_subframe)
    cam = scene.camera
    panel = bpy.data.objects['App_Tab_White_Panel']
    cursor = bpy.data.objects['App_Tab_Cursor_Visible_6_String_Length']
    black, _, neutral, _ = legacy._ensure_materials()
    # Curve bounds can include stale/evaluated bevel geometry in the viewport.
    # Use the actual staff centerlines, which define the musical layout.
    lines = []
    line_objects = []
    for i in range(1, _strings + 1):
        staff = bpy.data.objects[f'Lesson_Tab_Line_{i}']
        if 'Lesson_Original_Bevel_Depth' not in staff:
            staff['Lesson_Original_Bevel_Depth'] = staff.data.bevel_depth
        staff.data.bevel_depth = staff['Lesson_Original_Bevel_Depth'] * 0.55
        staff_material = legacy._mat('Lesson_Staff_Soft_Gray', (0.48, 0.48, 0.48, 1.0))
        if staff.data.materials:
            staff.data.materials[0] = staff_material
        else:
            staff.data.materials.append(staff_material)
        for material_slot in staff.material_slots:
            material_slot.link = 'DATA'
            material_slot.material = staff_material
        points = [world_to_camera_view(scene, cam, point) for point in
                  legacy._curve_points_world(bpy.data.objects[f'Lesson_Tab_Line_{i}'])]
        lines.append((min(p.x for p in points), min(p.y for p in points),
                      max(p.x for p in points), max(p.y for p in points)))
        line_objects.append(bpy.data.objects[f'Lesson_Tab_Line_{i}'])
    line_objects = [obj for _,obj in sorted(zip(lines,line_objects), key=lambda pair: -(pair[0][1]+pair[0][3]))]
    lines.sort(key=lambda box: -(box[1] + box[3]))
    ys = [(box[1] + box[3]) / 2 for box in lines]
    left = max(box[0] for box in lines)
    right = min(box[2] for box in lines)
    width = right - left
    page_start = page * lesson['page_beats']

    def x_at(beat):
        measures = max(0.0, min(2.0, float((beat - page_start) / lesson['measure'])))
        measure_index = min(1, int(measures))
        return left + width * (measure_index * 0.5 + 0.012 + 0.476 * (measures - measure_index))

    # Page meshes are static during playback; rebuild only after layout/page changes.
    key = (page, tuple(tuple(box) for box in lines),
           tuple(tuple(row) for row in panel.matrix_world),
           tuple(tuple(row) for row in cam.matrix_world), cam.data.lens, cam.data.ortho_scale)
    if key != _draw_key:
        for obj in bpy.data.objects:
            if obj.name.startswith(('Demo_Tab_Seg_', 'Lesson_Tab_Number_')) or obj.name == 'JSON_Guitar_Active_Note_Yellow':
                obj.hide_set(True)
                obj.hide_render = True
        visible = [n for n in lesson['notes'] if page_start <= n['start'] < page_start + lesson['page_beats']]
        depth = panel.matrix_world.translation + (cam.matrix_world.to_quaternion() @ Vector((0, 0, -1))) * 0.35
        slot = 0
        gaps = {obj: [] for obj in line_objects}
        for note in visible:
            digits = 'x' if note.get('muted') else str(note['fret'])
            # Keep labels just inside the bar at measure starts; chord notes share x.
            x = max(left + width * 0.012, min(right - width * 0.012, x_at(note['start'])))
            # Fewer lines spread over the same staff height keep the six-line number size.
            height = min(abs(a-b) for a,b in zip(ys,ys[1:])) * 0.72 * min(1, (_strings - 1) / 5)
            # A lower-case x is fitted to the same height as digits; keep it at x-height.
            box = _draw_number(scene, cam, slot, digits, x, ys[note['string']-1],
                               height * (0.75 if digits == 'x' else 1), depth, black)
            slot += 1
            gaps[line_objects[note['string']-1]].append((box[0],box[2]))
        _staff_number_gaps(scene,cam,gaps)
        _draw_key = key
    legacy._move_camera_center(scene, cam, cursor,
                               max(left, min(right, x_at(position))), (ys[0] + ys[-1])/2)
    cursor.hide_set(False)
    cursor.hide_render = False
    # Blank the highlight just before a same-fret repeat so each attack reads as a new hit.
    by_string = {n['string']: n for n in active if not _in_retrigger_gap(lesson, n, position)}
    for string in range(1, _strings + 1):
        obj = bpy.data.objects[legacy.string_object(string, _strings)]
        legacy._restore_string_rest(obj)
        note = by_string.get(string)
        material = legacy._mat(f'JSON_{obj.name}_Active', legacy.STRING_NOTE_COLORS[obj.name]) if note else neutral
        obj.data.materials[0] = material
        for material_slot in obj.material_slots:
            material_slot.link = 'DATA'
            material_slot.material = material
        marker = bpy.data.objects[f'Lesson_V2_Marker_{string}']
        marker.hide_set(note is None)
        marker.hide_render = note is None
        _set_marker_shape(marker, bool(note and note.get('muted')))
        if note:
            # Geometry helpers accept the old reversed tab-row mapping.
            row = string
            marker.location = (legacy._open_string_point(row, _strings) if note['fret'] == 0
                               else legacy._point_on_string(row, note['fret'], _strings))
            marker.rotation_euler = cam.matrix_world.to_euler()
            marker.data.materials.clear()
            marker.data.materials.append(material)
            marker['note_id'] = note['id']
            age = seconds_between(lesson, note['start'], position)
            # Small, deterministic attack decay; no lingering deformation at note-off. A muted string does not ring.
            if age < 0.3 and not note.get('muted'):
                legacy._vibrate_active_string(scene, cam, obj, string)
                rest = json.loads(obj['JSON_String_Rest_State'])
                decay = math.exp(-12 * age)
                for sp, saved in zip(obj.data.splines, rest['splines']):
                    for point, coords in zip(sp.points, saved['points']):
                        base = Vector(coords[:3])
                        point.co = (*(base + (Vector(point.co[:3])-base) * decay), coords[3])
                obj.data.bevel_depth = rest['bevel_depth']
    scene['Lesson_V2_Active_IDs'] = json.dumps([n['id'] for n in active])
    scene['Lesson_V2_Page'] = page + 1


def register():
    global _lesson, _draw_key, _retriggered, _strings
    _draw_key = None
    data = json.loads(bpy.data.texts['Lesson_V2_JSON'].as_string())
    _lesson = prepare(data)
    _strings = view_spec(data).strings
    _retriggered = _retriggered_notes(_lesson)
    legacy.SEGMENTS.update({'5': [0,5,6,2,3], '6': [0,5,6,4,2,3],
                            '7': [0,1,2], '8': list(range(7)), '9': [0,1,2,3,5,6]})
    handlers = bpy.app.handlers.frame_change_post
    handlers[:] = [h for h in handlers if getattr(h, '__name__', '') not in (HANDLER, legacy.HANDLER_NAME)]
    update.__name__ = HANDLER
    handlers.append(update)
    # On file load, world matrices are stale until the depsgraph is evaluated.
    bpy.context.view_layer.update()
    update(bpy.context.scene)
