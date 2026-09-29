"""Blender background integration check; does not save the scene."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy
from mathutils import Vector
from guitar_video_app.integrations.blender_adapter import animate_and_prepare_render
from guitar_video_app.integrations.lesson_setup import install_lesson

scene = bpy.context.scene
chart = ROOT / 'data/demo_16_note_lesson.json'
data = json.loads(chart.read_text())
fixed = ['LessonVerticalCamera', 'App_Tab_White_Panel', 'Backdrop', 'Nut']
fixed += [f'String_{i}' for i in range(1, 7)]
fixed += [f'Lesson_Tab_Line_{i}' for i in range(1, 7)]
fixed += [f'Fret_{i:02d}' for i in range(1, 21)]
before = {n: bpy.data.objects[n].matrix_world.copy() for n in fixed}
result = animate_and_prepare_render(chart)
assert result['note_count'] == 16
count = len(bpy.data.objects)
install_lesson(chart)
assert len(bpy.data.objects) == count, 'Repeated installation created duplicate objects'
colors = set()
for note in data['notes']:
    name = f"String_{7-note['string']}"
    for age in (0, 2, 5, 11):
        scene.frame_set(note['frame'] + age)
        bpy.context.view_layer.update()
        assert scene['Demo_16_Note_Active_Index'] == note['index']
        assert scene['Demo_16_Note_Active_Guitar_Object'] == name
        assert scene['Demo_16_Note_Visible_Staffs'] == ('1,2' if note['index'] <= 8 else '3,4')
        marker = bpy.data.objects['JSON_Guitar_Active_Note_Yellow']
        active = bpy.data.objects[name]
        assert marker.material_slots[0].material == active.material_slots[0].material
        colors.add(tuple(active.material_slots[0].material.diffuse_color))
        for i in range(1, 7):
            obj = bpy.data.objects[f'String_{i}']
            assert obj.material_slots[0].link == 'DATA'
            if obj.name != name:
                assert obj.material_slots[0].material.name == 'JSON_Guitar_String_Neutral'
            rest = json.loads(obj['JSON_String_Rest_State'])
            deltas = [(Vector(p.co[:3]) - Vector(saved[:3])).length
                      for sp, values in zip(obj.data.splines, rest['splines'])
                      for p, saved in zip(sp.points, values['points'])]
            if obj.name != name or age >= 5:
                assert max(deltas) < 1e-7
            elif age == 2:
                assert max(deltas) > 1e-7, 'Active string did not vibrate'
assert len(colors) == 6
for n, matrix in before.items():
    assert all(abs(a-b) < 1e-6 for r1,r2 in zip(matrix,bpy.data.objects[n].matrix_world) for a,b in zip(r1,r2)), n
for i in range(1, 4):
    bar = bpy.data.objects[f'Lesson_Tab_Bar_{i}']
    assert not bar.hide_render and not bar.hide_get()
    assert len(bar.data.splines[0].points) == 2
handlers = [h for h in bpy.app.handlers.frame_change_post if h.__name__ == 'demo_16_note_tab_controller']
assert len(handlers) == 1
exec(compile(bpy.data.texts['Demo_16_Note_Tab_Controller.py'].as_string(), 'embedded', 'exec'), {})
assert len([h for h in bpy.app.handlers.frame_change_post if h.__name__ == 'demo_16_note_tab_controller']) == 1
print('PASS: 64 frame checks; six colors; open/fretted markers; vibration; two pages; bar lines; fixed transforms; repeat install; embedded reload.')
