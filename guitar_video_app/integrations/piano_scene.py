"""Build the piano scene procedurally: 88 keys at real size, a grand body, lights and camera.

World units are metres. The keyboard is centered on x = 0 with the front edge of the white keys on
y = 0, keys running back along +y and their tops at z = 0. Each key is an object named
Piano_Key_<MIDI pitch> (Piano_Key_021 to Piano_Key_108) whose origin is its pivot, PIVOT_MM behind the
front edge, so pressing a key is a rotation about x. Dimensions come from instruments.piano.keyboard,
the same numbers the piano view gives the renderer.
"""
import math

import bpy

from guitar_video_app.instruments.piano.keyboard import (BLACK_HEIGHT_MM, BLACK_LENGTH_MM, BLACK_MM, HIGH, LOW,
                                                         PRESS_MM, WHITE_LENGTH_MM, WHITE_MM, WIDTH_MM, is_black,
                                                         key_x_mm)

MM = 0.001
PIVOT_MM = 400.0
WHITE_GAP_MM = 0.9
WHITE_DEPTH_MM = 20.0
BLACK_BASE_MM = BLACK_MM - 1.7
BLACK_TOP_MM = BLACK_BASE_MM - 2.4
RESOLUTION = (1080, 1920)
BACKGROUND = (0.018, 0.017, 0.016)
KEYBOARD = 'Piano_Keyboard'
CAMERA = 'PianoCamera'
COLLECTION = 'Piano'
PRESS_ANGLE = math.atan(PRESS_MM / PIVOT_MM)

MATERIALS = {
    'Piano_White': (0.9, 0.89, 0.86, 1.0),
    'Piano_Black': (0.025, 0.025, 0.03, 1.0),
    'Piano_Case': (0.008, 0.009, 0.011, 1.0),
    'Piano_Felt': (0.32, 0.04, 0.05, 1.0),
    'Piano_Metal': (0.86, 0.68, 0.34, 1.0),
    'Piano_Soundboard': (0.55, 0.34, 0.16, 1.0),
    'Piano_Floor': (0.11, 0.105, 0.10, 1.0),
    'Piano_Right_White': (1.0, 0.6, 0.22, 1.0),
    'Piano_Right_Black': (0.86, 0.42, 0.08, 1.0),
    'Piano_Left_White': (0.38, 0.66, 1.0, 1.0),
    'Piano_Left_Black': (0.14, 0.42, 0.9, 1.0),
}


def key_name(pitch: int) -> str:
    return f'Piano_Key_{pitch:03d}'


def world_x(pitch: int) -> float:
    return (key_x_mm(pitch) - WIDTH_MM / 2) * MM


def material(name: str):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = MATERIALS[name]
    mat.roughness = 0.35 if name in ('Piano_Black', 'Piano_Case') else 0.5
    mat.use_nodes = True
    shader = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    shader.inputs['Base Color'].default_value = MATERIALS[name]
    shader.inputs['Roughness'].default_value = 0.19 if name == 'Piano_Case' else mat.roughness
    shader.inputs['Metallic'].default_value = 0.78 if name == 'Piano_Metal' else 0
    shader.inputs['Coat Weight'].default_value = 0.45 if name == 'Piano_Case' else 0
    return mat


def _mesh(name, vertices, faces):
    mesh = bpy.data.meshes.get(name) or bpy.data.meshes.new(name)
    mesh.clear_geometry()
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    return mesh


# Bottom corners 0-3 and top corners 4-7, counterclockwise from above; faces point outward.
BOX_FACES = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


def _box(x0, x1, y0, y1, z0, z1):
    return [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]


def _prism(points, z0, z1):
    """A vertical prism from a 2D polygon in x/y."""
    bottom = [(x, y, z0) for x, y in points]
    top = [(x, y, z1) for x, y in points]
    count = len(points)
    faces = [tuple(reversed(range(count))), tuple(range(count, 2 * count))]
    faces += [(i, (i + 1) % count, (i + 1) % count + count, i + count) for i in range(count)]
    return bottom + top, faces


def _key_vertices(pitch):
    """Key corners relative to its pivot; a black key is narrower at the top than at its base."""
    back = -PIVOT_MM * MM + WHITE_LENGTH_MM * MM
    front = -PIVOT_MM * MM
    if not is_black(pitch):
        half = (WHITE_MM - WHITE_GAP_MM) / 2 * MM
        return _box(-half, half, front, back, -WHITE_DEPTH_MM * MM, 0)
    base, top = BLACK_BASE_MM / 2 * MM, BLACK_TOP_MM / 2 * MM
    y0 = back - BLACK_LENGTH_MM * MM
    z0, z1 = -6 * MM, BLACK_HEIGHT_MM * MM
    return [(-base, y0, z0), (base, y0, z0), (base, back, z0), (-base, back, z0),
            (-top, y0 + 5 * MM, z1), (top, y0 + 5 * MM, z1), (top, back, z1), (-top, back, z1)]


def _object(name, mesh, collection, parent, location, mat, bevel_mm):
    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
    obj.data = mesh
    obj.parent = parent
    obj.location = location
    obj.rotation_euler = (0, 0, 0)
    mesh.materials.clear()
    mesh.materials.append(mat)
    if bevel_mm:
        bevel = obj.modifiers.get('Bevel') or obj.modifiers.new('Bevel', 'BEVEL')
        bevel.width = bevel_mm * MM
        bevel.segments = 2
        bevel.limit_method = 'ANGLE'
    for polygon in mesh.polygons:
        polygon.use_smooth = False
    return obj


def _remove_prefixed(prefixes):
    for obj in list(bpy.data.objects):
        if any(obj.name.startswith(prefix) for prefix in prefixes):
            bpy.data.objects.remove(obj, do_unlink=True)


def _cylinder(name, collection, parent, radius, depth, location, mat, vertices=32):
    obj = bpy.data.objects.get(name)
    if obj is None:
        bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location)
        obj = bpy.context.object
        obj.name = name
        if obj.name not in collection.objects:
            for linked in obj.users_collection:
                linked.objects.unlink(obj)
            collection.objects.link(obj)
    obj.parent = parent
    obj.location = location
    obj.rotation_euler = (0, 0, 0)
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    bevel = obj.modifiers.get('Soft edges') or obj.modifiers.new('Soft edges', 'BEVEL')
    bevel.width = 1.4 * MM
    bevel.segments = 3
    return obj


def build_keyboard():
    """Create or update the keys, case and keyboard anchor; returns the anchor."""
    collection = bpy.data.collections.get(COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION)
        bpy.context.scene.collection.children.link(collection)
    anchor = bpy.data.objects.get(KEYBOARD)
    if anchor is None:
        anchor = bpy.data.objects.new(KEYBOARD, None)
        collection.objects.link(anchor)
    anchor.location = (0, 0, 0)
    anchor['width_mm'] = WIDTH_MM
    for pitch in range(LOW, HIGH + 1):
        black = is_black(pitch)
        mesh = _mesh(key_name(pitch), _key_vertices(pitch), BOX_FACES)
        obj = _object(key_name(pitch), mesh, collection, anchor, (world_x(pitch), PIVOT_MM * MM, 0),
                      material('Piano_Black' if black else 'Piano_White'), 1.2 if black else 0.8)
        obj['pitch'] = pitch
    half = WIDTH_MM / 2 * MM
    cheek = 45 * MM
    back = WHITE_LENGTH_MM * MM
    parts = {
        'Piano_Key_Slip': (_box(-half - cheek, half + cheek, -22 * MM, -2 * MM, -62 * MM, -22 * MM), 'Piano_Case'),
        'Piano_Cheek_Left': (_box(-half - cheek, -half - 1 * MM, -22 * MM, back + 40 * MM, -62 * MM, 32 * MM), 'Piano_Case'),
        'Piano_Cheek_Right': (_box(half + 1 * MM, half + cheek, -22 * MM, back + 40 * MM, -62 * MM, 32 * MM), 'Piano_Case'),
        'Piano_Felt': (_box(-half, half, back, back + 6 * MM, -20 * MM, 3 * MM), 'Piano_Felt'),
        'Piano_Fallboard': (_box(-half - 1 * MM, half + 1 * MM, back + 6 * MM, back + 40 * MM, -62 * MM, 62 * MM), 'Piano_Case'),
        'Piano_Key_Bed': (_box(-half - cheek, half + cheek, -22 * MM, back + 40 * MM, -70 * MM, -62 * MM), 'Piano_Case'),
    }
    for name, (vertices, mat) in parts.items():
        _object(name, _mesh(name, vertices, BOX_FACES), collection, anchor, (0, 0, 0), material(mat), 2.0)
    for name in MATERIALS:
        material(name)
    return anchor


def _bezier_segment(a, b, c, d, steps=20):
    return [tuple((1-t)**3*a[j] + 3*(1-t)**2*t*b[j] +
                  3*(1-t)*t*t*c[j] + t**3*d[j] for j in range(2))
            for t in (i / steps for i in range(steps))]


def build_grand_body(anchor, collection):
    """Build a curved grand case around the existing key animation coordinates."""
    from mathutils import Vector

    _remove_prefixed(('Piano_Grand_', 'Piano_Soundboard', 'Piano_Lid_', 'Piano_Music_Stand',
                      'Piano_Leg_', 'Piano_Pedal_', 'Piano_String_Group_', 'Piano_Floor'))
    case = material('Piano_Case')
    brass = material('Piano_Metal')
    wood = material('Piano_Soundboard')
    half = WIDTH_MM * MM / 2
    edge = half + 0.065
    floor_z = -0.74

    def solid(name, points, bottom, top, mat=case, bevel=2):
        verts, faces = _prism(points, bottom, top)
        return _object(name, _mesh(name, verts, faces), collection, anchor,
                       (0, 0, 0), mat, bevel)

    def box(name, bounds, mat=case, bevel=2):
        return _object(name, _mesh(name, _box(*bounds), BOX_FACES),
                       collection, anchor, (0, 0, 0), mat, bevel)

    def rod(name, a, b, radius, mat=brass):
        a, b = Vector(a), Vector(b)
        obj = _cylinder(name, collection, anchor, radius, (b-a).length, (a+b)/2, mat, 16)
        obj.rotation_euler = (b-a).to_track_quat('Z', 'Y').to_euler()
        return obj

    # Straight bass side, rounded tail and an inward-curving treble side.
    outline = [(-edge, 0.25), (edge, 0.25)]
    outline += _bezier_segment((edge, .25), (edge, .62), (.38, .68), (.24, 1.03))
    outline += _bezier_segment((.24, 1.03), (.12, 1.36), (.05, 1.77), (-.31, 1.78))
    outline += _bezier_segment((-.31, 1.78), (-.58, 1.78), (-edge, 1.66), (-edge, 1.44))
    # Remove the duplicated front corner before constructing the mesh.
    outline.pop(1)
    inner = [(x * .94, .98 + (y-.98)*.94) for x, y in outline]
    count = len(outline)
    verts = [(x,y,z) for z in (-.17,.085) for ring in (outline,inner) for x,y in ring]
    faces = []
    for i in range(count):
        j = (i+1) % count
        faces.extend([(i,j,2*count+j,2*count+i),
                      (count+j,count+i,3*count+i,3*count+j),
                      (2*count+i,2*count+j,3*count+j,3*count+i),
                      (j,i,count+i,count+j)])
    rim = _object('Piano_Grand_Rim', _mesh('Piano_Grand_Rim',verts,faces),
                  collection,anchor,(0,0,0),case,3)
    for polygon in rim.data.polygons:
        polygon.use_smooth = polygon.index % 4 < 2
    solid('Piano_Soundboard', inner, -.12, -.106, wood, 1)
    box('Piano_Grand_Front_Apron',(-edge,edge,-.024,.26,-.15,-.07))
    box('Piano_Grand_Inner_Rail',(-edge+.045,edge-.045,.28,.34,-.10,.025),brass)
    box('Piano_Grand_Fallboard_Trim',(-half,half,.263,.267,.025,.029),brass,.5)
    # The wooden bridge follows the shortening strings toward the treble.
    bridge = [(-.59,1.47),(-.39,1.30),(-.17,1.10),(.06,.90),(.28,.70),(.47,.49)]
    for index,(a,b) in enumerate(zip(bridge,bridge[1:])):
        rod(f'Piano_Grand_Bridge_{index}',(*a,-.066),(*b,-.066),.013,wood)

    # Lid vertices are local to the long bass-side hinge.
    lid_points = [(x+edge,y) for x,y in outline]
    lid = solid('Piano_Lid_Main',lid_points,0,.024)
    lid.location = (-edge,0,.093)
    lid.rotation_euler.y = math.radians(-29)
    lid['role'] = 'hinged_grand_lid'
    for index,y in enumerate((.44,.95,1.40)):
        rod(f'Piano_Lid_Hinge_{index}',(-edge,y-.038,.096),(-edge,y+.038,.096),.007)
    bpy.context.view_layer.update()
    prop_top = lid.matrix_world @ Vector((1.06,.62,0))
    rod('Piano_Lid_Prop',(.38,.62,.025),prop_top,.011,case)

    stand = box('Piano_Music_Stand',(-.34,.34,-.012,.012,0,.23))
    stand.location = (0,.345,.08)
    stand.rotation_euler.x = math.radians(-15)
    box('Piano_Music_Stand_Ledge',(-.35,.35,.305,.36,.08,.098))
    for x in (-.26,.26):
        rod(f'Piano_Music_Stand_Support_{x}',(x,.40,.015),(x,.40,.14),.008,case)

    # The caster bottoms share exactly the same floor plane.
    for label,x,y in (('Left',-edge+.055,.10),('Right',edge-.055,.10),('Tail',-.32,1.56)):
        name = f'Piano_Leg_{label}'
        box(name+'_Collar',(x-.056,x+.056,y-.056,y+.056,-.205,-.14))
        verts = _box(-.023,.023,-.023,.023,floor_z+.082,-.19)
        verts[4:] = [(-.043,-.043,-.19),(.043,-.043,-.19),
                     (.043,.043,-.19),(-.043,.043,-.19)]
        _object(name,_mesh(name,verts,BOX_FACES),collection,anchor,(x,y,0),case,3)
        box(name+'_Ferrule',(x-.025,x+.025,y-.025,y+.025,floor_z+.072,floor_z+.105),brass)
        rod(name+'_Caster', (x-.022,y,floor_z+.033),(x+.022,y,floor_z+.033),.033,brass)
        box(name+'_Fork',(x-.029,x+.029,y-.014,y+.014,floor_z+.037,floor_z+.084),brass,1)

    # Suspended lyre and pedals retain clearance for actual pedal travel.
    for label,x in (('Left',-.09),('Right',.09)):
        rod('Piano_Pedal_Lyre_'+label,(x,.17,-.145),(x*.82,.12,floor_z+.10),.016,case)
        rod('Piano_Pedal_Brace_'+label,(x,.13,floor_z+.14),(x*1.7,.42,-.15),.007,brass)
    box('Piano_Pedal_Lyre_Base',(-.13,.13,.075,.17,floor_z+.067,floor_z+.115),case,5)
    for index,x in enumerate((-.07,0,.07),1):
        points=[(x-.012,.13),(x+.012,.13),(x+.019,-.015),(x+.014,-.04),
                (x-.014,-.04),(x-.019,-.015)]
        pedal=solid(f'Piano_Pedal_{index}',list(reversed(points)),floor_z+.055,floor_z+.068,brass,3)
        pedal['role']=('soft_pedal','sostenuto_pedal','sustain_pedal')[index-1]
        rod(f'Piano_Pedal_Rod_{index}',(x,.14,floor_z+.11),(x,.20,-.14),.004,brass)

    # Plate braces, bridges, and individually spaced strings provide depth under the lid.
    for index,(a,b) in enumerate((
        ((-.56,.36,-.068),(-.48,1.56,-.068)),
        ((-.15,.36,-.068),(-.32,1.62,-.068)),
        ((.26,.36,-.068),(-.15,1.35,-.068)),
        ((.54,.36,-.068),(.11,.85,-.068)),
    )):
        rod(f'Piano_Grand_Plate_Brace_{index}',a,b,.016,brass)
    for index in range(66):
        t=index/65
        x=-.54+1.07*t
        length=1.15-.92*t
        for unison in range(2):
            offset=unison*.003
            rod(f'Piano_String_Group_{index:02d}_{unison}',
                (x+offset,.36,-.039),(x-.10+offset,.36+length,-.039),.00065,brass)
        rod(f'Piano_Grand_Pin_{index}',(x,.35,-.055),(x,.35,-.022),.0024,brass)
    box('Piano_Floor',(-100,100,-100,100,floor_z-.02,floor_z),material('Piano_Floor'),0)


def build_presentation(scene):
    """Separate inspection camera and softboxes; lesson framing stays independent."""
    from mathutils import Vector

    target = Vector((0, .67, -.05))
    name = 'Piano_Grand_PresentationCamera'
    cam = bpy.data.objects.get(name)
    if cam is None:
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        scene.collection.objects.link(cam)
    cam.location = (2.65, -3.65, 2.8)
    cam.rotation_euler = (target-cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.lens = 52
    for label, position, energy, size in (
        ('Key', (1, -2, 3.8), 650, 3.0),
        ('Fill', (-2.6, -.5, 1.8), 450, 2.5),
        ('Rim', (.3, 3, 3.0), 850, 2.0),
    ):
        name = 'Piano_Grand_Light_' + label
        light = bpy.data.objects.get(name)
        if light is None:
            light = bpy.data.objects.new(name, bpy.data.lights.new(name, 'AREA'))
            scene.collection.objects.link(light)
        light.location = position
        light.rotation_euler = (target-light.location).to_track_quat('-Z', 'Y').to_euler()
        light.data.energy = energy
        light.data.size = size
    return cam


def build_scene():
    """The whole piano scene: keyboard, world, Workbench render settings and the camera."""
    scene = bpy.context.scene
    for obj in [o for o in scene.objects if o.name in ('Cube', 'Light')]:
        bpy.data.objects.remove(obj, do_unlink=True)
    anchor = build_keyboard()
    collection = bpy.data.collections.get(COLLECTION)
    build_grand_body(anchor, collection)
    scene.render.resolution_x, scene.render.resolution_y = RESOLUTION
    scene.render.resolution_percentage = 100
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.show_specular_highlight = True
    world = scene.world or bpy.data.worlds.new('World')
    scene.world = world
    world.color = BACKGROUND
    cam = bpy.data.objects.get(CAMERA)
    if cam is None:
        cam = bpy.data.objects.new(CAMERA, bpy.data.cameras.new(CAMERA))
        scene.collection.objects.link(cam)
    for obj in [o for o in scene.objects if o.type == 'CAMERA' and o is not cam]:
        bpy.data.objects.remove(obj, do_unlink=True)
    scene.camera = cam
    frame_camera(scene, 48, 84)
    build_presentation(scene)
    return scene


# Camera: orthographic, looking down at ELEVATION degrees from the front, framing the keys a song
# uses. Short-video apps cover the bottom 20% with captions, so the keys sit at KEYS_Y of the frame
# height, filling FILL of its width.
ELEVATION = 55
KEYS_Y = 0.40
FILL = 0.86
MIN_WHITE_KEYS = 15
MARGIN_WHITE_KEYS = 1


def frame_camera(scene, low: int, high: int):
    """Point the camera at the keys from low to high (MIDI pitches), at least MIN_WHITE_KEYS wide."""
    cam = scene.camera
    left = world_x(low) - (MARGIN_WHITE_KEYS + 0.5) * WHITE_MM * MM
    right = world_x(high) + (MARGIN_WHITE_KEYS + 0.5) * WHITE_MM * MM
    width = max(right - left, MIN_WHITE_KEYS * WHITE_MM * MM)
    center = (left + right) / 2
    tilt = math.radians(90 - ELEVATION)
    direction = (0, math.sin(tilt), -math.cos(tilt))
    target = (center, WHITE_LENGTH_MM / 2 * MM, 0)
    distance = 2.0
    cam.location = tuple(t - d * distance for t, d in zip(target, direction))
    cam.rotation_euler = (tilt, 0, 0)
    cam.data.type = 'ORTHO'
    cam.data.sensor_fit = 'AUTO'
    aspect = scene.render.resolution_y / scene.render.resolution_x
    cam.data.ortho_scale = width / FILL * max(1.0, aspect)
    cam.data.shift_x = 0
    cam.data.shift_y = 0.5 - KEYS_Y
    cam.data.clip_start = 0.01
    cam.data.clip_end = 10
    # Placing the title reads cam.matrix_world, which only follows location after an update.
    bpy.context.view_layer.update()
    return cam
