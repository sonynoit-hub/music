"""Piano-local 3D trails and a pivoted sustain pedal. No camera dependencies."""
import math
import bpy
from guitar_video_app.instruments.piano.performance import performance, pedal_amount, trail_state
from guitar_video_app.integrations.piano_scene import (
    KEYBOARD, COLLECTION, BOX_FACES, _box, _mesh, _object, world_x,
)

COLORS = {'left': (.055, .38, 1, 1), 'right': (1, .38, .035, 1),
          'unknown': (.65, .7, .75, 1)}
_notes = []
_pedals = []
_objects = []


def install(data, prepared):
    global _notes, _pedals, _objects
    _notes, _pedals = performance(data, prepared)
    _objects = []
    for obj in list(bpy.data.objects):
        if obj.name.startswith('Piano_Trail_'):
            mesh = obj.data
            mats = list(mesh.materials)
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
            for mat in mats:
                if mat.users == 0:
                    bpy.data.materials.remove(mat)
    parent = bpy.data.objects[KEYBOARD]
    collection = bpy.data.collections[COLLECTION]
    for index, note in enumerate(_notes):
        name = f'Piano_Trail_{index:05d}'
        color = COLORS.get(note['hand'], COLORS['unknown'])
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = color
        mat.use_nodes = True
        shader = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        shader.inputs['Base Color'].default_value = color
        shader.inputs['Emission Color'].default_value = color
        shader.inputs['Roughness'].default_value = .28
        width = .011 if note['pitch'] % 12 in (1, 3, 6, 8, 10) else .017
        mesh = _mesh(name, _box(-width/2,width/2,-.009,.009,0,1), BOX_FACES)
        obj = _object(name, mesh, collection, parent,
                      (world_x(note['pitch']), .035, .042), mat, 1.5)
        obj['note_id'] = note['id']
        _objects.append((obj, shader, color))
    # Move the pedal origin to its rear hinge without changing its resting geometry.
    pedal = bpy.data.objects.get('Piano_Pedal_3')
    if pedal and not pedal.get('animation_pivot'):
        from mathutils import Vector
        pivot = Vector((.07, .13, -.74+.062))
        for vertex in pedal.data.vertices:
            vertex.co -= pivot
        pedal.location = pivot
        pedal['animation_pivot'] = True
    rod = bpy.data.objects.get('Piano_Pedal_Rod_3')
    if rod and 'rest_z' not in rod:
        rod['rest_z'] = rod.location.z


def update(now):
    for note, (obj, shader, color) in zip(_notes, _objects):
        bottom, length, brightness = trail_state(note, now)
        obj.location.z = .042 + bottom
        # Zero scale, rather than visibility flags, is reliable when baking for rendering.
        obj.scale = (1 if length else 0, 1 if length else 0, length)
        shader.inputs['Emission Strength'].default_value = brightness*1.7
        shader.inputs['Base Color'].default_value = tuple(c*brightness for c in color[:3])+(1,)
        obj.data.materials[0].diffuse_color = tuple(c*brightness for c in color[:3])+(1,)
    amount = pedal_amount(_pedals, now)
    pedal = bpy.data.objects.get('Piano_Pedal_3')
    if pedal:
        pedal.rotation_euler.x = math.radians(9)*amount
    rod = bpy.data.objects.get('Piano_Pedal_Rod_3')
    if rod:
        rod.location.z = rod['rest_z']-.008*amount


def bake_frame(frame):
    for obj, shader, _ in _objects:
        obj.keyframe_insert('location', frame=frame)
        obj.keyframe_insert('scale', frame=frame)
        obj.data.materials[0].keyframe_insert('diffuse_color', frame=frame)
        for name in ('Emission Strength', 'Base Color'):
            shader.inputs[name].keyframe_insert('default_value', frame=frame)
    for name, path in (('Piano_Pedal_3', 'rotation_euler'), ('Piano_Pedal_Rod_3', 'location')):
        obj = bpy.data.objects.get(name)
        if obj:
            obj.keyframe_insert(path, frame=frame)
