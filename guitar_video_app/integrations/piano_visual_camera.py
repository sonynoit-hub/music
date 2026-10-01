"""PIANO_VISUAL's shot camera: plays a song's camera shots while PianoVisual_PresentationCamera stays as it is.

Blender only places the camera. instruments.piano.camera plans every shot from the lesson's tempo map;
the frame handler asks it where the camera is at the frame's time and sets PianoVisual_ShotCamera's
location, rotation, lens and shift, so nothing is keyed or baked and any frame renders the same in any
order. The shot list lives in the PianoVisual_Camera_JSON text block (the lesson in the particles
controller's text block) so the loader rebuilds the camera on reload; the scene property pv_camera is
'shots' while it plays. Without shots the presentation camera is the scene camera, exactly as before.
"""
from __future__ import annotations

import json

import bpy
from mathutils import Vector

from guitar_video_app.instruments.piano.camera import CameraPath, validate
from guitar_video_app.instruments.piano.view import prepare
from guitar_video_app.integrations import piano_visual as pv

COLLECTION = 'PIANO_VISUAL_CAMERAS'
CAMERA = f'{pv.PREFIX}_ShotCamera'
TEXT = 'PianoVisual_Camera_JSON'
HANDLER = 'piano_visual_camera_controller'
PROPERTY = 'pv_camera'
CLIP_START = 0.02

_path = None


def shots():
    """The stored shot list, or None for the single wide view."""
    text = bpy.data.texts.get(TEXT)
    if bpy.context.scene.get(PROPERTY) != 'shots' or text is None:
        return None
    return json.loads(text.as_string())


def store(data, plan):
    """Check a shot list against the piano view and keep it for register(); None keeps the wide view."""
    scene = bpy.context.scene
    if plan is None:
        text = bpy.data.texts.get(TEXT)
        if text:
            bpy.data.texts.remove(text)
        if PROPERTY in scene:
            del scene[PROPERTY]
        return
    plan = validate(plan, prepare(data))
    text = bpy.data.texts.get(TEXT) or bpy.data.texts.new(TEXT)
    text.clear()
    text.write(json.dumps(plan, indent=2))
    scene[PROPERTY] = 'shots'


def _camera():
    collection = bpy.data.collections.get(COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION)
    if collection.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(collection)
    obj = bpy.data.objects.get(CAMERA)
    if obj is None:
        obj = bpy.data.objects.new(CAMERA, bpy.data.cameras.new(CAMERA))
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    obj.parent = bpy.data.objects[pv.FRAME_OBJECT]
    obj.matrix_parent_inverse.identity()
    obj.rotation_mode = 'QUATERNION'
    obj.data.sensor_fit, obj.data.sensor_width = 'AUTO', 36.0
    obj.data.clip_start = CLIP_START
    return obj


def place(obj, state):
    location = Vector(state['location'])
    obj.location = location
    obj.rotation_quaternion = (Vector(state['target']) - location).to_track_quat('-Z', 'Y')
    obj.data.lens = state['lens']
    obj.data.shift_x, obj.data.shift_y = state['shift_x'], state['shift_y']


def update(scene, *_):
    obj = bpy.data.objects.get(CAMERA)
    if _path is None or obj is None:
        return
    place(obj, _path.camera_at((scene.frame_current + scene.frame_subframe) / (scene.render.fps / scene.render.fps_base)))


def _stop():
    handlers = bpy.app.handlers.frame_change_post
    handlers[:] = [h for h in handlers if getattr(h, '__name__', '') != HANDLER]


def register(data):
    """Play the stored shots on the shot camera, or go back to the presentation camera without any."""
    global _path
    plan = shots()
    if plan is None:
        uninstall()
        return None
    _path = CameraPath(prepare(data), plan)
    obj = _camera()
    scene = bpy.context.scene
    scene.camera = obj
    _stop()
    update.__name__ = HANDLER
    bpy.app.handlers.frame_change_post.append(update)
    update(scene)
    return _path


def install(data, plan):
    store(data, plan)
    return register(data)


def uninstall():
    """Delete the shot camera and its shots; the presentation camera becomes the scene camera again."""
    global _path
    _stop()
    _path = None
    obj = bpy.data.objects.get(CAMERA)
    if obj is not None:
        camera = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if camera is not None and camera.users == 0:
            bpy.data.cameras.remove(camera)
    collection = bpy.data.collections.get(COLLECTION)
    if collection is not None:
        bpy.data.collections.remove(collection)
    text = bpy.data.texts.get(TEXT)
    if text is not None:
        bpy.data.texts.remove(text)
    scene = bpy.context.scene
    if PROPERTY in scene:
        del scene[PROPERTY]
    presentation = bpy.data.objects.get(pv.CAMERA_OBJECT)
    if presentation is not None:
        scene.camera = presentation
