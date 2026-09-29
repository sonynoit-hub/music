"""Run in Blender against reference-guitar.blend; leave the original file unchanged."""
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from guitar_video_app.core.lesson_v2 import prepare, seconds_at, state
from guitar_video_app.integrations.lesson_setup import install_lesson
from guitar_video_app.integrations import lesson_controller_v2 as runtime
from guitar_video_app.integrations import lesson_controller as geometry
from bpy_extras.object_utils import world_to_camera_view

scene = bpy.context.scene
fixed = ['LessonVerticalCamera','App_Tab_White_Panel','Backdrop','Nut']
fixed += [f'String_{i}' for i in range(1,7)] + [f'Lesson_Tab_Line_{i}' for i in range(1,7)]
before = {n: bpy.data.objects[n].matrix_world.copy() for n in fixed}
count = 0
for path in sorted((ROOT/'data/lesson_tests').glob('*.json')):
    if path.name.endswith('.expected.json'):
        continue
    data = json.loads(path.read_text())
    lesson = prepare(data)
    install_lesson(path)
    frames = {0,lesson['frame_end'],lesson['frame_end']+1}
    for n in lesson['notes']:
        for boundary in (n['start'],n['end']):
            f = math.ceil(seconds_at(lesson['tempo_map'], boundary) * lesson['fps'])
            frames.update((f-1,f,f+1))
    # Both playback directions plus loop restart must evaluate identically.
    for frame in sorted(frames) + list(reversed(sorted(frames)))[::7] + [0]:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        position,page,active = state(lesson,frame)
        ids = [n['id'] for n in active]
        assert json.loads(scene['Lesson_V2_Active_IDs']) == ids
        assert scene['Lesson_V2_Page'] == page+1
        panel = geometry._bbox(scene,scene.camera,bpy.data.objects['App_Tab_White_Panel'])
        for digit in bpy.data.objects:
            if digit.name.startswith('Demo_Tab_Seg_') and not digit.hide_render:
                for vertex in digit.data.vertices:
                    p = world_to_camera_view(scene,scene.camera,digit.matrix_world @ vertex.co)
                    assert panel[0] <= p.x <= panel[2] and panel[1] <= p.y <= panel[3], (path.name,frame,digit.name,tuple(p))
        for string in range(1,7):
            obj = bpy.data.objects[f'String_{7-string}']
            marker = bpy.data.objects[f'Lesson_V2_Marker_{string}']
            note = next((n for n in active if n['string']==string),None)
            assert marker.hide_render == (note is None)
            if note:
                assert marker['note_id'] == note['id']
                assert obj.material_slots[0].material == marker.material_slots[0].material
                assert obj.material_slots[0].material.name == f'JSON_String_{7-string}_Active'
            else:
                assert obj.material_slots[0].material.name == 'JSON_Guitar_String_Neutral'
                rest=json.loads(obj['JSON_String_Rest_State'])
                for sp,saved in zip(obj.data.splines,rest['splines']):
                    for p,co in zip(sp.points,saved['points']):
                        assert max(abs(a-b) for a,b in zip(p.co,co)) < 1e-7
        count += 1
    print('PASS',path.name,flush=True)
for path in (ROOT/'data/lesson_tests/invalid').glob('*.json'):
    try:
        prepare(json.loads(path.read_text()))
    except ValueError:
        continue
    raise AssertionError(f'Accepted invalid input: {path}')
for n,matrix in before.items():
    assert all(abs(a-b)<1e-6 for ra,rb in zip(matrix,bpy.data.objects[n].matrix_world) for a,b in zip(ra,rb)), n
# Independent timing assertions: no old sustained note resurrects after a retrigger.
retrigger=prepare(json.loads((ROOT/'data/lesson_tests/06_retrigger.json').read_text()))
assert [n['id'] for n in state(retrigger,30)[2]] == ['n2']
assert state(retrigger,45)[2] == []
triplets=prepare(json.loads((ROOT/'data/lesson_tests/02_durations.json').read_text()))
assert [n['id'] for n in state(triplets,370)[2]] == ['n8']
print('PASS',count,'frame checks, invalid inputs, retrigger, triplets and preserved transforms',flush=True)
install_lesson(ROOT/'data/lesson_tests/03_chords.json')
scene.frame_set(360)
exec(bpy.data.texts['Demo_16_Note_Tab_Controller.py'].as_string(),{})
assert len([h for h in bpy.app.handlers.frame_change_post if h.__name__==runtime.HANDLER]) == 1
versions=bpy.context.preferences.filepaths.save_version
try:
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'outputs/lesson-v2-tests.blend'))
finally:
    bpy.context.preferences.filepaths.save_version=versions
scene.render.engine='BLENDER_WORKBENCH'
scene.display.shading.color_type='MATERIAL'
scene.render.resolution_percentage=30
scene.render.filepath=str(ROOT/'outputs/lesson-v2-chords.png')
scene.render.image_settings.media_type='IMAGE'
scene.render.image_settings.file_format='PNG'
bpy.ops.render.render(write_still=True)
