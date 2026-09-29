"""Exercise the saved loader in an isolated Blender process without binding a second bridge."""
from pathlib import Path
import sys
import json
import bpy

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from guitar_video_app.integrations import blender_bridge_server as bridge
bridge.start_bridge=lambda *args,**kwargs:{'ok':True,'isolated_reload_test':True}
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'outputs/v3-tests.blend'))
exec(bpy.data.texts['Demo_16_Note_Tab_Controller.py'].as_string(),{})
scene=bpy.context.scene
assert len([h for h in bpy.app.handlers.frame_change_post if h.__name__=='guitar_lesson_v2_controller'])==1
assert len([s for s in scene.sequence_editor.strips if s.name.startswith('Lesson_JSON_Guitar_Audio')])==1
assert scene['Dashboard_Song_ID']=='complex-32-measures'
checks=json.loads((ROOT/'data/lesson_tests/12_complex_32_measures.expected.json').read_text())['checkpoints']
from fractions import Fraction
for c in checks:
    f=Fraction(c['beat'])*40
    scene.frame_set(int(f),subframe=float(f-int(f)))
    assert set(json.loads(scene['Lesson_V2_Active_IDs']))==set(c['active_ids'])
print('PASS: saved file, embedded loader, single handler/audio and all 13 playback checkpoints after reload.')
