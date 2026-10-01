"""Exercise the saved loader in an isolated Blender process without binding a second bridge.

The test song is sent to outputs/v3-tests.blend (whatever song it was saved with), saved to a temporary copy and
reopened there, so the real .blend is never written.
"""
from fractions import Fraction
from pathlib import Path
import json
import sys
import tempfile
import bpy

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from guitar_video_app.integrations import blender_bridge_server as bridge
from guitar_video_app.integrations import dashboard_bridge
bridge.start_bridge=lambda *args,**kwargs:{'ok':True,'isolated_reload_test':True}
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'outputs/v3-tests.blend'))
dashboard_bridge.sync(dict(command='dashboard_sync',json_path=str(ROOT/'data/lesson_tests/12_complex_32_measures.json'),
                           wav_path=str(ROOT/'outputs/complex_32_measures.wav'),song_id='complex-32-measures',
                           revision=1,offset_seconds=0))
with tempfile.TemporaryDirectory() as folder:
    copy=str(Path(folder)/'reload-test.blend')
    bpy.ops.wm.save_as_mainfile(filepath=copy,copy=True)
    bpy.ops.wm.open_mainfile(filepath=copy)
    exec(bpy.data.texts['Demo_16_Note_Tab_Controller.py'].as_string(),{})
    scene=bpy.context.scene
    assert len([h for h in bpy.app.handlers.frame_change_post if h.__name__=='guitar_lesson_v2_controller'])==1
    assert len([s for s in scene.sequence_editor.strips if s.name.startswith('Lesson_JSON_Guitar_Audio')])==1
    assert scene['Dashboard_Song_ID']=='complex-32-measures'
    checks=json.loads((ROOT/'data/lesson_tests/12_complex_32_measures.expected.json').read_text())['checkpoints']
    for c in checks:
        f=Fraction(c['beat'])*40
        scene.frame_set(int(f),subframe=float(f-int(f)))
        assert set(json.loads(scene['Lesson_V2_Active_IDs']))==set(c['active_ids']),(c['beat'],scene['Lesson_V2_Active_IDs'])
print(f'PASS: sent the test song, saved a copy, reopened it: embedded loader, single handler/audio and all '
      f'{len(checks)} playback checkpoints after reload; outputs/v3-tests.blend not written.')
