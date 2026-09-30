"""Song title and credit line above the guitar, placed in camera space like the tab numbers."""
from pathlib import Path

import bpy
from mathutils import Vector

from guitar_video_app.integrations import lesson_controller as legacy

FONT_FOLDER = Path('/System/Library/Fonts/Supplemental')
# Object name, font file, baseline height and font size, as fractions of the frame height.
LINES = (('Lesson_Title', 'Georgia.ttf', 0.87, 0.075),
         ('Lesson_Subtitle', 'Georgia Italic.ttf', 0.82, 0.038))
MAX_WIDTH = 0.88
COLOR = (0.93, 0.91, 0.86, 1.0)


def _font(name):
    path = FONT_FOLDER / name
    return bpy.data.fonts.load(str(path), check_existing=True) if path.exists() else None


def _frame_point(scene, cam, nx, ny, depth):
    """World point at normalized frame position (nx, ny) on the camera-facing plane through depth."""
    if cam.data.type != 'ORTHO':
        return legacy._camera_overlay_point(scene, cam, nx, ny, depth)
    tr, br, bl, tl = cam.data.view_frame(scene=scene)
    point = cam.matrix_world @ bl.lerp(br, nx).lerp(tl.lerp(tr, nx), ny)
    forward = (cam.matrix_world.to_quaternion() @ Vector((0, 0, -1))).normalized()
    return point + forward * (depth - point).dot(forward)


def install_title(title='', subtitle='', anchor='App_Tab_White_Panel'):
    """Show title and subtitle centered above the instrument; an empty line is hidden. The text
    lies on a camera-facing plane just behind the anchor object (the guitar's tab panel)."""
    scene = bpy.context.scene
    cam = scene.camera
    panel = bpy.data.objects[anchor]
    depth = panel.matrix_world.translation + (cam.matrix_world.to_quaternion() @ Vector((0, 0, -1))) * 0.35
    frame_height = (_frame_point(scene, cam, 0.5, 1, depth) - _frame_point(scene, cam, 0.5, 0, depth)).length
    material = legacy._mat('Lesson_Title_Text', COLOR)
    for (name, font, baseline, size), text in zip(LINES, (title, subtitle)):
        text = (text or '').strip()
        obj = bpy.data.objects.get(name)
        if obj is None:
            obj = bpy.data.objects.new(name, bpy.data.curves.new(name, 'FONT'))
            scene.collection.objects.link(obj)
        obj.hide_render = not text
        obj.hide_set(not text)
        if not text:
            continue
        obj.data.body = text
        obj.data.font = _font(font) or obj.data.font
        obj.data.align_x = 'CENTER'
        obj.data.align_y = 'BOTTOM_BASELINE'
        obj.data.size = size * frame_height
        obj.data.extrude = 0
        obj.data.bevel_depth = 0
        obj.data.materials.clear()
        obj.data.materials.append(material)
        obj.rotation_euler = cam.matrix_world.to_euler()
        obj.location = _frame_point(scene, cam, 0.5, baseline, depth)
        obj.show_in_front = True
        bpy.context.view_layer.update()
        box = legacy._bbox(scene, cam, obj)
        if box[2] - box[0] > MAX_WIDTH:
            obj.data.size *= MAX_WIDTH / (box[2] - box[0])
