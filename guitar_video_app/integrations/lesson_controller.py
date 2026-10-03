import bpy, json, math
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

HANDLER_NAME = 'demo_16_note_tab_controller'

# Source-of-truth mapping:
# JSON note['string'] is the tab string number, top-to-bottom: 1..6.
# Tab rows map directly to staff lines; this scene numbers guitar objects in reverse.
TAB_STRING_TO_LINE = {1: 'Lesson_Tab_Line_1', 2: 'Lesson_Tab_Line_2', 3: 'Lesson_Tab_Line_3', 4: 'Lesson_Tab_Line_4', 5: 'Lesson_Tab_Line_5', 6: 'Lesson_Tab_Line_6'}
TAB_STRING_TO_GUITAR = {1: 'String_6', 2: 'String_5', 3: 'String_4', 4: 'String_3', 5: 'String_2', 6: 'String_1'}


def string_object(tab_string, strings=6):
    """Scene object of a tab string on an instrument with strings strings (the bass scene has 4)."""
    return f'String_{strings + 1 - int(tab_string)}'

SEGMENTS = {'0':[0,1,2,3,4,5], '1':[1,2], '2':[0,1,6,4,3], '3':[0,1,6,2,3], '4':[5,6,1,2]}
SEG_DEF = {0:((-0.35,0.50),(0.35,0.50)), 1:((0.35,0.50),(0.35,0.00)), 2:((0.35,0.00),(0.35,-0.50)), 3:((-0.35,-0.50),(0.35,-0.50)), 4:((-0.35,0.00),(-0.35,-0.50)), 5:((-0.35,0.50),(-0.35,0.00)), 6:((-0.35,0.00),(0.35,0.00))}


def _mat(name, color):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def _ensure_materials():
    black = _mat('Demo_Tab_Note_Black', (0.015, 0.015, 0.015, 1.0))
    orange = _mat('JSON_Guitar_String_Orange', (0.05, 0.48, 1.0, 1.0))
    neutral = _mat('JSON_Guitar_String_Neutral', (0.82, 0.9, 0.92, 1.0))
    yellow = _mat('JSON_Guitar_Note_Yellow', (1.0, 0.92, 0.12, 1.0))
    return black, orange, neutral, yellow


def _bbox(scene, cam, obj):
    eo = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    pts = [eo.matrix_world @ Vector(c) for c in eo.bound_box]
    cs = [world_to_camera_view(scene, cam, p) for p in pts]
    return [min(c.x for c in cs), min(c.y for c in cs), max(c.x for c in cs), max(c.y for c in cs)]


def _center(scene, cam, obj):
    b = _bbox(scene, cam, obj)
    return Vector(((b[0]+b[2])*0.5, (b[1]+b[3])*0.5, 0))


def _move_camera_center(scene, cam, obj, tx, ty):
    bpy.context.view_layer.update()
    c = _center(scene, cam, obj)
    loc = obj.matrix_world.translation.copy()
    q = cam.matrix_world.to_quaternion()
    right = q @ Vector((1,0,0))
    up = q @ Vector((0,1,0))
    step = 0.01
    p0 = world_to_camera_view(scene, cam, loc)
    px = world_to_camera_view(scene, cam, loc + right * step)
    py = world_to_camera_view(scene, cam, loc + up * step)
    dx = (px.x - p0.x) / step if abs(px.x - p0.x) > 1e-9 else 1.0
    dy = (py.y - p0.y) / step if abs(py.y - p0.y) > 1e-9 else 1.0
    obj.matrix_world.translation += right * ((tx - c.x) / dx) + up * ((ty - c.y) / dy)


def _camera_overlay_point(scene, cam, nx, ny, depth_point):
    frame = cam.data.view_frame(scene=scene)
    bl, br, tr, tl = frame[0], frame[1], frame[2], frame[3]
    local_point = bl.lerp(br, nx).lerp(tl.lerp(tr, nx), ny)
    origin = cam.matrix_world.translation
    world = cam.matrix_world @ local_point
    ray = (world - origin).normalized()
    forward = (cam.matrix_world.to_quaternion() @ Vector((0,0,-1))).normalized()
    denom = ray.dot(forward)
    if abs(denom) < 1e-8:
        return depth_point
    return origin + ray * ((depth_point - origin).dot(forward) / denom)


def _set_bar_mesh(obj, center, right, up, a, b, sx, sy, thickness, mat):
    p1 = center + right*(a[0]*sx) + up*(a[1]*sy)
    p2 = center + right*(b[0]*sx) + up*(b[1]*sy)
    d = p2 - p1
    if d.length < 1e-8:
        return
    axis = d.normalized()
    n = right if abs(axis.dot(right)) < 0.8 else up
    n = (n - axis*n.dot(axis)).normalized() * thickness
    obj.data.clear_geometry()
    obj.data.from_pydata([tuple(p1+n), tuple(p1-n), tuple(p2-n), tuple(p2+n)], [], [(0,1,2,3)])
    obj.data.update()
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def _nudge_digit(scene, cam, slot_index, active_segments, target_x, target_y):
    objs = [bpy.data.objects.get(f'Demo_Tab_Seg_{slot_index+1:02d}_{seg}') for seg in active_segments]
    pts = []
    for obj in objs:
        if obj:
            pts += [obj.matrix_world @ v.co for v in obj.data.vertices]
    if not pts:
        return
    cs = [world_to_camera_view(scene, cam, p) for p in pts]
    cx = (min(c.x for c in cs) + max(c.x for c in cs)) * 0.5
    cy = (min(c.y for c in cs) + max(c.y for c in cs)) * 0.5
    center = sum(pts, Vector()) / len(pts)
    q = cam.matrix_world.to_quaternion()
    right = q @ Vector((1,0,0))
    up = q @ Vector((0,1,0))
    step = 0.01
    p0 = world_to_camera_view(scene, cam, center)
    px = world_to_camera_view(scene, cam, center + right*step)
    py = world_to_camera_view(scene, cam, center + up*step)
    dx = (px.x-p0.x)/step if abs(px.x-p0.x)>1e-9 else 1.0
    dy = (py.y-p0.y)/step if abs(py.y-p0.y)>1e-9 else 1.0
    delta = right*((target_x-cx)/dx) + up*((target_y-cy)/dy)
    for obj in objs:
        if obj:
            for v in obj.data.vertices:
                v.co += delta
            obj.data.update()


def _draw_digit(scene, cam, slot_index, digit, nx, ny, depth_point, mat, size_scale=1.0):
    center = _camera_overlay_point(scene, cam, nx, ny, depth_point)
    q = cam.matrix_world.to_quaternion()
    right = (q @ Vector((1,0,0))).normalized()
    up = (q @ Vector((0,1,0))).normalized()
    active = SEGMENTS.get(str(digit), SEGMENTS['0'])
    for seg in range(7):
        obj = bpy.data.objects.get(f'Demo_Tab_Seg_{slot_index+1:02d}_{seg}')
        if not obj:
            mesh = bpy.data.meshes.new(f'Demo_Tab_Seg_{slot_index+1:02d}_{seg}_Mesh')
            obj = bpy.data.objects.new(f'Demo_Tab_Seg_{slot_index+1:02d}_{seg}', mesh)
            bpy.context.collection.objects.link(obj)
        if seg in active:
            _set_bar_mesh(obj, center, right, up, SEG_DEF[seg][0], SEG_DEF[seg][1], 0.0075 * size_scale, 0.012 * size_scale, 0.00125 * size_scale, mat)
            obj.hide_set(False); obj.hide_render = False; obj.show_in_front = True
        else:
            obj.hide_set(True); obj.hide_render = True
    _nudge_digit(scene, cam, slot_index, active, nx, ny)


def _data():
    text = bpy.data.texts.get('Demo_16_Note_Tab_Timing_JSON')
    return json.loads(text.as_string()) if text else None


def _note_start(note):
    return int(note.get('frame', 0))


def _active_note(notes, frame):
    # Timing rule: a note becomes active only when its scheduled start frame arrives.
    # The cursor travels from the current note to the next note during that interval,
    # so guitar string/fret changes exactly at the tab note frame, not halfway early.
    current = notes[0]
    for note in notes:
        if _note_start(note) <= frame:
            current = note
        else:
            break
    return current


def _curve_points_world(obj):
    pts = []
    if obj and hasattr(obj.data, 'splines'):
        for sp in obj.data.splines:
            for p in getattr(sp, 'bezier_points', []):
                pts.append(obj.matrix_world @ p.co)
            for p in getattr(sp, 'points', []):
                pts.append(obj.matrix_world @ Vector((p.co.x, p.co.y, p.co.z)))
    return pts


def _closest_point_on_segment(p, a, b):
    ab = b - a
    denom = ab.dot(ab)
    if denom < 1e-12:
        return a
    t = max(0.0, min(1.0, (p - a).dot(ab) / denom))
    return a + ab * t


def _object_center_world(name):
    obj = bpy.data.objects.get(name)
    if not obj:
        return None
    pts = []
    if hasattr(obj.data, 'splines'):
        for sp in obj.data.splines:
            for p in getattr(sp, 'bezier_points', []):
                pts.append(obj.matrix_world @ p.co)
            for p in getattr(sp, 'points', []):
                pts.append(obj.matrix_world @ Vector((p.co.x, p.co.y, p.co.z)))
    elif hasattr(obj, 'bound_box'):
        pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    if not pts:
        return obj.matrix_world.translation.copy()
    return sum(pts, Vector()) / len(pts)


def _fret_region_center(fret):
    fret = int(fret)
    if fret <= 0:
        return None
    left_name = 'Nut' if fret == 1 else f'Fret_{fret-1:02d}'
    right_name = f'Fret_{fret:02d}'
    left = _object_center_world(left_name)
    right = _object_center_world(right_name)
    if left is None or right is None:
        return None
    return left.lerp(right, 0.5)


def _point_on_string(tab_string, fret, strings=6):
    obj = bpy.data.objects.get(string_object(tab_string, strings))
    pts = _curve_points_world(obj)
    if not pts:
        return Vector((0,0,0))
    target = _fret_region_center(fret)
    if target is None:
        return pts[0]
    best = pts[0]
    best_dist = 1e18
    for a, b in zip(pts, pts[1:]):
        p = _closest_point_on_segment(target, a, b)
        dist = (p - target).length_squared
        if dist < best_dist:
            best = p
            best_dist = dist
    return best




def _open_string_point(tab_string, strings=6):
    obj = bpy.data.objects.get(string_object(tab_string, strings))
    pts = _curve_points_world(obj)
    if not pts:
        return Vector((0,0,0))
    nut = _object_center_world('Nut')
    if nut is None:
        return pts[-1]
    first_fret = _object_center_world('Fret_01')
    # Mirror the fret-1 marker across the nut so open strings sit on the headstock side.
    target = nut if first_fret is None else nut + (nut - first_fret) * 0.5
    best = pts[0]
    best_dist = 1e18
    for a, b in zip(pts, pts[1:]):
        p = _closest_point_on_segment(target, a, b)
        dist = (p - target).length_squared
        if dist < best_dist:
            best = p
            best_dist = dist
    return best

def _ensure_flat_marker(yellow_mat):
    obj = bpy.data.objects.get('JSON_Guitar_Active_Note_Yellow')
    if obj:
        obj.data.materials.clear(); obj.data.materials.append(yellow_mat)
        return obj
    mesh = bpy.data.meshes.new('JSON_Guitar_Active_Note_Yellow_Mesh')
    verts = [(0,0,0)]
    faces = []
    r = 0.006
    for i in range(32):
        a = math.tau * i / 32
        verts.append((math.cos(a)*r, math.sin(a)*r, 0))
    for i in range(1,33):
        faces.append((0, i, 1 if i == 32 else i+1))
    mesh.from_pydata(verts, [], faces); mesh.update()
    obj = bpy.data.objects.new('JSON_Guitar_Active_Note_Yellow', mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(yellow_mat)
    obj.show_in_front = True
    return obj


def _capture_string_rest(obj):
    if not obj or not hasattr(obj.data, 'splines'):
        return
    if obj.get('JSON_String_Rest_State'):
        return
    data = {'bevel_depth': float(getattr(obj.data, 'bevel_depth', 0.0)), 'splines': []}
    for sp in obj.data.splines:
        item = {'type': sp.type, 'points': []}
        if sp.type == 'BEZIER':
            for p in sp.bezier_points:
                item['points'].append({
                    'co': [p.co.x, p.co.y, p.co.z],
                    'handle_left': [p.handle_left.x, p.handle_left.y, p.handle_left.z],
                    'handle_right': [p.handle_right.x, p.handle_right.y, p.handle_right.z],
                })
        else:
            for p in sp.points:
                item['points'].append([p.co.x, p.co.y, p.co.z, p.co.w])
        data['splines'].append(item)
    obj['JSON_String_Rest_State'] = json.dumps(data)


def _restore_string_rest(obj):
    if not obj or not hasattr(obj.data, 'splines'):
        return
    _capture_string_rest(obj)
    raw = obj.get('JSON_String_Rest_State')
    if not raw:
        return
    data = json.loads(raw)
    obj.data.bevel_depth = float(data.get('bevel_depth', obj.data.bevel_depth))
    for sp, item in zip(obj.data.splines, data.get('splines', [])):
        if sp.type == 'BEZIER':
            for p, saved in zip(sp.bezier_points, item.get('points', [])):
                p.co = Vector(saved['co'])
                p.handle_left = Vector(saved['handle_left'])
                p.handle_right = Vector(saved['handle_right'])
        else:
            for p, saved in zip(sp.points, item.get('points', [])):
                p.co = (saved[0], saved[1], saved[2], saved[3])
    obj.data.update_tag()


def _vibrate_active_string(scene, cam, obj, tab_string):
    if not obj or not hasattr(obj.data, 'splines'):
        return
    _restore_string_rest(obj)
    q = cam.matrix_world.to_quaternion() if cam else None
    camera_up = (q @ Vector((0,1,0))).normalized() if q else Vector((0,0,1))
    local_up = obj.matrix_world.inverted().to_3x3() @ camera_up
    if local_up.length < 1e-8:
        local_up = Vector((0,0,1))
    local_up.normalize()
    # Thinner strings need a slightly stronger visual displacement.
    amp_by_string = {1: 0.0019, 2: 0.00165, 3: 0.00145, 4: 0.00125, 5: 0.0011, 6: 0.0010}
    amp = amp_by_string.get(int(tab_string), 0.00125)
    phase = scene.frame_current * 1.4
    count = 0
    for sp in obj.data.splines:
        pts = sp.bezier_points if sp.type == 'BEZIER' else sp.points
        total = max(1, len(pts) - 1)
        for idx, p in enumerate(pts):
            center_weight = math.sin(math.pi * idx / total) if total else 1.0
            wave = math.sin(phase + idx * 2.35) * amp * center_weight
            delta = local_up * wave
            if sp.type == 'BEZIER':
                p.co += delta
                p.handle_left += delta
                p.handle_right += delta
            else:
                p.co = (p.co.x + delta.x, p.co.y + delta.y, p.co.z + delta.z, p.co.w)
            count += 1
    base_depth = float(json.loads(obj.get('JSON_String_Rest_State')).get('bevel_depth', obj.data.bevel_depth))
    obj.data.bevel_depth = base_depth * (1.32 if int(tab_string) <= 3 else 1.22)
    obj.data.update_tag()


STRING_NOTE_COLORS = {
    'String_1': (1.0, 0.12, 0.18, 1.0),
    'String_2': (0.12, 0.85, 0.28, 1.0),
    'String_3': (0.72, 0.22, 1.0, 1.0),
    'String_4': (0.05, 0.85, 0.90, 1.0),
    'String_5': (0.05, 0.32, 1.0, 1.0),
    'String_6': (1.0, 0.42, 0.06, 1.0),
}


def _update_guitar(scene, cam, active, orange, neutral, yellow):
    tab_string = int(active['string'])
    fret = int(active['fret'])
    guitar_obj_name = TAB_STRING_TO_GUITAR[tab_string]
    active_material = _mat('JSON_' + guitar_obj_name + '_Active', STRING_NOTE_COLORS[guitar_obj_name])
    for i in range(1,7):
        so = bpy.data.objects.get(TAB_STRING_TO_GUITAR[i])
        if so and hasattr(so.data, 'materials'):
            _restore_string_rest(so)
            mat = active_material if i == tab_string else neutral
            if so.data.materials:
                so.data.materials[0] = mat
            else:
                so.data.materials.append(mat)
            # Object-linked legacy glow materials otherwise override the lesson.
            for slot in so.material_slots:
                slot.link = 'DATA'
                slot.material = mat
            if i == tab_string:
                note_age = scene.frame_current - _note_start(active)
                if 0 <= note_age <= 4:
                    _vibrate_active_string(scene, cam, so, tab_string)
    marker = _ensure_flat_marker(active_material)
    if fret == 0:
        marker.location = _open_string_point(tab_string)
    else:
        marker.location = _point_on_string(tab_string, fret)
    marker.rotation_euler = cam.matrix_world.to_euler() if cam else marker.rotation_euler
    marker.show_in_front = True
    marker.hide_set(False); marker.hide_render = False
    for obj in bpy.data.objects:
        n = obj.name
        if (n.startswith('Note_') or n.startswith('App_Guitar_Note_') or n.startswith('Demo_Guitar_String_Highlight_') or n.startswith('Lesson_Tab_Note_') or n == 'Demo_Guitar_Fret_Marker' or n == 'Lesson_Tab_Cursor'):
            obj.hide_set(True); obj.hide_render = True
    scene['Demo_16_Note_Active_String'] = tab_string
    scene['Demo_16_Note_Active_Fret'] = fret
    scene['Demo_16_Note_Active_Guitar_Object'] = guitar_obj_name
    scene['Demo_16_Note_Flat_Marker_Visible'] = True


def demo_16_note_tab_controller(scene):
    data = _data()
    cam = scene.camera or bpy.data.objects.get('LessonVerticalCamera')
    panel = bpy.data.objects.get('App_Tab_White_Panel')
    cursor = bpy.data.objects.get('App_Tab_Cursor_Visible_6_String_Length')
    if not data or not cam or not panel or not cursor:
        return
    black, orange, neutral, yellow = _ensure_materials()
    frame = scene.frame_current
    notes = sorted(data['notes'], key=lambda n: int(n['index']))
    page = 0 if frame < int(data['page_switch_frame']) else 1
    staffs = data['staff_pages'][page]['staffs']
    visible = sorted([n for n in notes if int(n['staff']) in staffs], key=lambda n: int(n['index']))
    if not visible:
        return

    pb = _bbox(scene, cam, panel)
    left, bottom, right, top = pb
    line_y = {}
    for tab_string, line_name in TAB_STRING_TO_LINE.items():
        line_obj = bpy.data.objects.get(line_name)
        if not line_obj:
            return
        b = _bbox(scene, cam, line_obj)
        line_y[tab_string] = (b[1] + b[3]) * 0.5

    slot_xs = [left + (right-left)*p for p in [0.10,0.18,0.26,0.34,0.66,0.74,0.82,0.90]]
    depth = panel.matrix_world.translation + (cam.matrix_world.to_quaternion() @ Vector((0,0,-1))).normalized() * 0.35
    for j, note in enumerate(visible):
        tab_string = max(1, min(6, int(note['string'])))
        _draw_digit(scene, cam, j, note.get('label', str(note['fret'])), slot_xs[j], line_y[tab_string], depth, black)

    active = _active_note(notes, frame)
    if active not in visible:
        active = visible[0]
    idx = visible.index(active)
    nxt = visible[min(idx+1, len(visible)-1)]
    span = max(1, _note_start(nxt) - _note_start(active))
    t = min(1, max(0, (frame - _note_start(active)) / span)) if nxt is not active else 0
    cursor_x = slot_xs[idx] + (slot_xs[min(idx+1, len(slot_xs)-1)] - slot_xs[idx]) * t
    cursor_y = (line_y[1] + line_y[6]) * 0.5
    _move_camera_center(scene, cam, cursor, cursor_x, cursor_y)
    cursor.hide_set(False); cursor.hide_render = False

    _update_guitar(scene, cam, active, orange, neutral, yellow)
    scene['Demo_16_Note_Active_Index'] = int(active['index'])
    scene['Demo_16_Note_Active_Label'] = str(active.get('label', active.get('fret')))
    scene['Demo_16_Note_Visible_Staffs'] = ','.join(str(s) for s in staffs)


def register_demo_16_note_handler():
    handlers = bpy.app.handlers.frame_change_post
    handlers[:] = [h for h in handlers if getattr(h, '__name__', '') != HANDLER_NAME]
    demo_16_note_tab_controller.__name__ = HANDLER_NAME
    handlers.append(demo_16_note_tab_controller)
    demo_16_note_tab_controller(bpy.context.scene)

if __name__ == '__main__':
    register_demo_16_note_handler()
