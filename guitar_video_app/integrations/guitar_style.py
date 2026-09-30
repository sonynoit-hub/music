"""Guitar color styles for lesson videos; 'natural' is the scene as saved in v4-vertical.blend.

Workbench renders use each material's viewport display color, so a style sets those. Some styles
also swap the studio backdrop for a radial grey gradient: a camera-facing disc of rings, each
ring one flat grey, so the Blender window shows the same background as the video.
"""
import math

import bpy
from mathutils import Vector

NATURAL_COLORS = {
    'Guitar | fine spruce': (0.43, 0.23, 0.085, 1.0),
    'Guitar | mahogany': (0.055, 0.009, 0.004, 1.0),
}
BLACK_FINISH = (0.012, 0.012, 0.013, 1.0)
# finish: every mahogany and spruce part (neck and headstock too); body: display (sRGB) color of
# the top, back and sides only; gradient: the grey gradient instead of the studio backdrop.
STYLES = {
    'natural': dict(),
    'black': dict(finish=BLACK_FINISH, gradient=True),
    'white': dict(body=(0.92, 0.91, 0.88)),
    'red': dict(body=(0.55, 0.04, 0.07), gradient=True),
    'blue': dict(body=(0.07, 0.16, 0.45)),
}
BODY_PARTS = {'Body_Soundboard': 'Guitar | fine spruce', 'Body_Back': 'Guitar | mahogany', 'Body_Sides': 'Guitar | mahogany'}
BODY_MATERIAL = 'Guitar | style body'
BACKDROP = 'Backdrop'
GRADIENT = 'Lesson_Style_Gradient'
# Display (sRGB) grey at the gradient's center and edges; center (from the bottom left) and radii
# are fractions of the frame. Greys are exact at the dashboard's render exposure.
GRADIENT_GREYS = (0.42, 0.2)
GRADIENT_CENTER = (0.5, 0.55)
GRADIENT_RADII = (0.75, 0.6)
RENDER_EXPOSURE = 0.8
# Workbench studio lighting returns this share of a rough, fully metallic material's color on a
# surface facing the camera; metallic avoids the fixed specular floor a dielectric gets.
STUDIO_LIGHT_SHARE = 0.615
RINGS = 48
SEGMENTS = 96
OUTER_RADIUS = 1.8
LEGACY_COMPOSITOR = 'Lesson_Style_Compositor'


def install_style(name='natural'):
    """Apply a style to the open scene; 'natural' restores the saved look exactly."""
    if name not in STYLES:
        raise ValueError(f'Guitar style must be one of {tuple(STYLES)}.')
    scene = bpy.context.scene
    style = STYLES[name]
    for material, color in NATURAL_COLORS.items():
        bpy.data.materials[material].diffuse_color = style.get('finish', color)
    _set_body(style.get('body'))
    backdrop = bpy.data.objects[BACKDROP]
    backdrop.hide_render = backdrop.hide_viewport = bool(style.get('gradient'))
    _remove_gradient()
    if style.get('gradient'):
        _add_gradient(scene, backdrop)
    # An earlier version composited the gradient; undo that in scenes saved with it.
    group = bpy.data.node_groups.get(LEGACY_COMPOSITOR)
    if group:
        if scene.compositing_node_group == group:
            scene.compositing_node_group = None
        bpy.data.node_groups.remove(group)
        scene.render.film_transparent = False
    if bpy.data.images.get(GRADIENT):
        bpy.data.images.remove(bpy.data.images[GRADIENT])


def _set_body(srgb):
    """Give the top, back and sides one colored material, or their own materials back."""
    body = bpy.data.materials.get(BODY_MATERIAL)
    if srgb:
        if body is None:
            source = bpy.data.materials['Guitar | mahogany']
            body = bpy.data.materials.new(BODY_MATERIAL)
            body.roughness, body.metallic = source.roughness, source.metallic
        body.diffuse_color = (*[_linear(c) for c in srgb], 1.0)
    for part, original in BODY_PARTS.items():
        for slot in bpy.data.objects[part].material_slots:
            slot.material = body if srgb else bpy.data.materials[original]
    if body and not srgb:
        bpy.data.materials.remove(body)


def _linear(srgb):
    return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4


def _remove_gradient():
    obj = bpy.data.objects.get(GRADIENT)
    if obj:
        mesh = obj.data
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)
    for material in [m for m in bpy.data.materials if m.name.startswith(GRADIENT + '_')]:
        bpy.data.materials.remove(material)


def _add_gradient(scene, backdrop):
    cam = scene.camera
    axis = cam.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    corners = [backdrop.matrix_world @ Vector(c) for c in backdrop.bound_box]
    depth = min(max((c - cam.matrix_world.translation).dot(axis) for c in corners), 0.9 * cam.data.clip_end)
    frame = cam.data.view_frame(scene=scene)
    scale = 1.0 if cam.data.type == 'ORTHO' else depth / -frame[0].z
    left, right = min(v.x for v in frame) * scale, max(v.x for v in frame) * scale
    bottom, top = min(v.y for v in frame) * scale, max(v.y for v in frame) * scale
    cx, cy = left + GRADIENT_CENTER[0] * (right - left), bottom + GRADIENT_CENTER[1] * (top - bottom)
    rx, ry = GRADIENT_RADII[0] * (right - left), GRADIENT_RADII[1] * (top - bottom)
    levels = [i / RINGS for i in range(RINGS + 1)] + [OUTER_RADIUS]
    verts = [(cx, cy, -depth)] + [(cx + t * rx * math.cos(2 * math.pi * k / SEGMENTS),
                                   cy + t * ry * math.sin(2 * math.pi * k / SEGMENTS), -depth)
                                  for t in levels[1:] for k in range(SEGMENTS)]
    vertex = lambda ring, k: 1 + ring * SEGMENTS + k % SEGMENTS
    faces = [(0, vertex(0, k), vertex(0, k + 1)) for k in range(SEGMENTS)]
    faces += [(vertex(r, k), vertex(r + 1, k), vertex(r + 1, k + 1), vertex(r, k + 1))
              for r in range(len(levels) - 2) for k in range(SEGMENTS)]
    mesh = bpy.data.meshes.new(GRADIENT)
    mesh.from_pydata(verts, [], faces)
    center, edge = GRADIENT_GREYS
    for ring in range(len(levels) - 1):
        t = min(1.0, (levels[ring] + levels[ring + 1]) / 2)
        srgb = center + (edge - center) * t ** 1.5
        grey = _linear(srgb) / 2 ** RENDER_EXPOSURE / STUDIO_LIGHT_SHARE
        material = bpy.data.materials.new(f'{GRADIENT}_{ring:02d}')
        material.diffuse_color = (grey, grey, grey, 1.0)
        material.roughness, material.metallic = 1.0, 1.0
        mesh.materials.append(material)
    for index, polygon in enumerate(mesh.polygons):
        polygon.material_index = 0 if index < SEGMENTS else 1 + (index - SEGMENTS) // SEGMENTS
    obj = bpy.data.objects.new(GRADIENT, mesh)
    scene.collection.objects.link(obj)
    obj.parent = cam
    obj.matrix_parent_inverse = cam.matrix_world.inverted() @ cam.matrix_world.normalized()
