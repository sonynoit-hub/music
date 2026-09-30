"""Piano lesson playback in Blender: keys press and light up in the hand's color.

Blender only animates. The piano view (instruments.piano.view) says which key each note uses,
which hand plays it and when, in beats; seconds come from the lesson's tempo map. A key starts
down PRESS_SECONDS before its note so it is fully down when the note sounds, holds until the note
ends and rises over RELEASE_SECONDS. A key struck again lifts first: its previous note ends up to
REPEAT_GAP_SECONDS early.
"""
from bisect import bisect_right
from collections import defaultdict
import json
from pathlib import Path

import bpy

from guitar_video_app.instruments.piano.keyboard import HIGH, LOW
from guitar_video_app.instruments.piano.view import prepare
from guitar_video_app.integrations.piano_scene import CAMERA, PRESS_ANGLE, frame_camera, key_name, material
from guitar_video_app.music.tempo import seconds_at
from guitar_video_app.integrations import piano_effects

HANDLER = 'piano_lesson_controller'
TEXT = 'Lesson_Piano_JSON'
LOADER = 'Piano_Lesson_Controller.py'
PRESS_SECONDS = 0.035
RELEASE_SECONDS = 0.07
REPEAT_GAP_SECONDS = 0.08
LIT_AT = 0.35
_keys = {}
_shown = {}


def key_events(lesson):
    """{pitch: (starts, events)}; an event is (start, end, hand, press, release) in seconds."""
    tempos = lesson['tempo_map']
    by_key = defaultdict(list)
    for note in lesson['notes']:
        by_key[note['pitch']].append((float(seconds_at(tempos, note['start'])), float(seconds_at(tempos, note['end'])),
                                      note['hand']))
    keys = {}
    for pitch, notes in by_key.items():
        notes.sort()
        events, press = [], PRESS_SECONDS
        for index, (start, end, hand) in enumerate(notes):
            release, next_press = RELEASE_SECONDS, PRESS_SECONDS
            if index + 1 < len(notes):
                following = notes[index + 1][0]
                gap = min(REPEAT_GAP_SECONDS, (following - start) / 2)
                end = min(end, following - gap)
                release, next_press = min(RELEASE_SECONDS, gap / 2), min(PRESS_SECONDS, gap / 2)
            events.append((start, max(end, start), hand, press, release))
            press = next_press
        keys[pitch] = ([e[0] for e in events], events)
    return keys


def key_state(starts, events, now):
    """How far the key is down (0-1) at now, in seconds, and the hand pressing it."""
    amount, hand = 0.0, None
    index = bisect_right(starts, now + PRESS_SECONDS)
    for start, end, who, press, release in events[max(0, index - 2):index]:
        if now < start - press or now >= end + release:
            continue
        down = (now - start + press) / press if now < start else 1.0 if now <= end else 1 - (now - end) / release
        if down > amount:
            amount, hand = down, who
    return amount, hand


def update(scene):
    now = (scene.frame_current + scene.frame_subframe) / (scene.render.fps / scene.render.fps_base)
    piano_effects.update(now)
    for pitch, (starts, events) in _keys.items():
        amount, hand = key_state(starts, events, now)
        lit = hand if amount >= LIT_AT else None
        if _shown.get(pitch) == (amount, lit):
            continue
        _shown[pitch] = (amount, lit)
        _set_key(pitch, amount, lit)


def _set_key(pitch, amount, hand):
    obj = bpy.data.objects[key_name(pitch)]
    obj.rotation_euler.x = PRESS_ANGLE * amount
    black = pitch % 12 in (1, 3, 6, 8, 10)
    name = f"Piano_{hand.title()}_{'Black' if black else 'White'}" if hand else ('Piano_Black' if black else 'Piano_White')
    obj.data.materials[0] = material(name)


def register():
    global _keys
    data = json.loads(bpy.data.texts[TEXT].as_string())
    lesson = prepare(data)
    _keys = key_events(lesson)
    piano_effects.install(data, lesson)
    _shown.clear()
    for pitch in range(LOW, HIGH + 1):
        _set_key(pitch, 0.0, None)
    handlers = bpy.app.handlers.frame_change_post
    handlers[:] = [h for h in handlers if getattr(h, '__name__', '') != HANDLER]
    update.__name__ = HANDLER
    handlers.append(update)
    update(bpy.context.scene)


def install_piano(data):
    """Load a piano view into the open piano scene: frame the keys it uses, set the frame range
    from its tempo map and start the controller."""
    lesson = prepare(data)
    scene = bpy.context.scene
    missing = [key_name(p) for p in range(LOW, HIGH + 1) if key_name(p) not in bpy.data.objects]
    if missing or scene.camera is None or scene.camera.name != CAMERA:
        raise ValueError('Open the piano scene (outputs/piano-vertical.blend) first.'
                         + (f' Missing {len(missing)} keys.' if missing else ''))
    text = bpy.data.texts.get(TEXT) or bpy.data.texts.new(TEXT)
    text.clear()
    text.write(json.dumps(data, indent=2))
    pitches = [n['pitch'] for n in lesson['notes']]
    frame_camera(scene, min(pitches), max(pitches))
    scene.render.fps = lesson['fps']
    scene.render.fps_base = 1
    scene.frame_start = 0
    scene.frame_end = lesson['frame_end']
    root = str(Path(__file__).resolve().parents[2])
    loader = bpy.data.texts.get(LOADER) or bpy.data.texts.new(LOADER)
    loader.clear()
    loader.write('import sys\n' + f'sys.path.insert(0, {root!r})\n'
                 + 'from guitar_video_app.integrations.piano_lesson import register\nregister()\n')
    loader.use_module = True
    register()
    return {'instrument': 'piano', 'note_count': len(lesson['notes']), 'timing': 'beats'}
