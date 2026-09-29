"""Build the 9:16 vertical scene from the 4:5 scene, keeping the guitar, tab and materials.

Blender -b outputs/v3-tests.blend --python scripts/make_vertical_scene.py -- [--out outputs/v4-vertical.blend]
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
from guitar_video_app.integrations import lesson_controller as legacy
from guitar_video_app.integrations.lesson_setup import build_bar_lines

RESOLUTION = (1080, 1920)
FRAME_HEIGHT = 0.90  # ortho_scale, world units; the 4:5 frame was 0.736 tall
CAMERA_SHIFT = (0.035, -0.105)  # right, up in world units; keeps the headstock in frame and the neck above the tab
# Fractions of the frame. Short-video apps draw captions over the bottom 20% and buttons over the
# right 14%, so the panel sits above the captions and the staff ends before the buttons, centered.
PANEL_Y = (0.21, 0.36)  # bottom, top of the white panel
PANEL_X = (0.115, 0.885)  # left, right of the white panel
STAFF_X = (0.14, 0.86)  # left, right ends of the staff lines
TAB_FRAME = 'App_Tab_Frame_9x16'

parser = argparse.ArgumentParser()
parser.add_argument('--out', type=Path, default=ROOT / 'outputs/v4-vertical.blend')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])

scene = bpy.context.scene
cam = scene.camera
group = bpy.data.objects['App_Tab_Backdrop_Panel_Cursor_Lines_GROUP']
panel = bpy.data.objects['App_Tab_White_Panel']
if TAB_FRAME in bpy.data.objects or group.parent is not None:
    raise SystemExit('Run this on the 4:5 scene (outputs/v3-tests.blend), not on an already vertical one.')

scene.render.resolution_x, scene.render.resolution_y = RESOLUTION
scene.render.resolution_percentage = 100
rotation = cam.matrix_world.to_quaternion()
right, up = rotation @ Vector((1, 0, 0)), rotation @ Vector((0, 1, 0))
cam.location += right * CAMERA_SHIFT[0] + up * CAMERA_SHIFT[1]
cam.data.ortho_scale = FRAME_HEIGHT
frame_width = FRAME_HEIGHT * RESOLUTION[0] / RESOLUTION[1]


def staff_x():
    xs = [world_to_camera_view(scene, cam, p).x for i in (1, 6)
          for p in legacy._curve_points_world(bpy.data.objects[f'Lesson_Tab_Line_{i}'])]
    return min(xs), max(xs)


def move_panel(world_offset):
    parent_space = (panel.parent.matrix_world @ panel.matrix_parent_inverse).inverted().to_3x3()
    panel.location += parent_space @ world_offset


# A camera-aligned parent scales the tab along screen x and y; scaling the tilted group itself would shear it.
frame = bpy.data.objects.new(TAB_FRAME, None)
group.users_collection[0].objects.link(frame)
frame.matrix_world = rotation.to_matrix().to_4x4()
frame.matrix_world.translation = panel.matrix_world.translation
bpy.context.view_layer.update()
group.parent = frame
group.matrix_parent_inverse = frame.matrix_world.inverted()
bpy.context.view_layer.update()

# Size and place the whole tab by the panel height and the staff width...
left, bottom, right_edge, top = legacy._bbox(scene, cam, panel)
staff_left, staff_right = staff_x()
frame.scale = ((STAFF_X[1] - STAFF_X[0]) / (staff_right - staff_left), (PANEL_Y[1] - PANEL_Y[0]) / (top - bottom), 1)
bpy.context.view_layer.update()
left, bottom, right_edge, top = legacy._bbox(scene, cam, panel)
staff_left, _ = staff_x()
frame.location += right * ((STAFF_X[0] - staff_left) * frame_width) + up * ((PANEL_Y[0] - bottom) * FRAME_HEIGHT)
bpy.context.view_layer.update()
# ...then fit only the white panel around the staff.
left, bottom, right_edge, top = legacy._bbox(scene, cam, panel)
panel.scale.x *= (PANEL_X[1] - PANEL_X[0]) / (right_edge - left)
bpy.context.view_layer.update()
left, bottom, right_edge, top = legacy._bbox(scene, cam, panel)
move_panel(right * ((PANEL_X[0] - left) * frame_width))
bpy.context.view_layer.update()
build_bar_lines()

box = legacy._bbox(scene, cam, panel)
print('Tab panel in camera view (left, bottom, right, top):', tuple(round(v, 3) for v in box))
print('Staff lines from', tuple(round(v, 3) for v in staff_x()))
bpy.ops.wm.save_as_mainfile(filepath=str(args.out.resolve()))
print(f'Saved {args.out}')
