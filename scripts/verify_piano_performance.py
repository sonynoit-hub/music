"""Run without Blender: tempo changes, channel sustain, release, and seek determinism."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from guitar_video_app.instruments.piano.view import prepare
from guitar_video_app.instruments.piano.performance import performance, pedal_amount, trail_state

data = dict(version=1, instrument='piano', fps=24, time_signature=[4,4], tempo_bpm=120,
            tempo_changes=[dict(beat=2,bpm=60)], end_beat=8,
            notes=[dict(id='a',pitch=60,hand='right',start_beat=1,duration_beats=2,channel=0),
                   dict(id='b',pitch=48,hand='left',start_beat=1,duration_beats=2,channel=1)],
            pedal_events=[dict(start_beat=2,duration_beats=3,channel=0,type='sustain')])
notes,pedals=performance(data,prepare(data))
a=next(n for n in notes if n['id']=='a')
b=next(n for n in notes if n['id']=='b')
assert (a['start'],a['end'],a['sound_end'])==(.5,2,4)
assert b['sound_end']==2
assert pedal_amount(pedals,2)==1 and pedal_amount(pedals,4.1)==0
assert trail_state(a,.4)==(0,0,0)
assert trail_state(a,2.5)[0]>0 and trail_state(a,2.5)[2]>0
assert trail_state(a,5.5)==(0,0,0)
expected=trail_state(a,1.5)
for t in (5,0,3,1.5): result=trail_state(a,t)
assert result==expected
notes,pedals=performance({**data,'pedal_events':[]},prepare(data))
assert all(n['sound_end']==n['end'] for n in notes)
print('PASS: tempo-aware sustain, channel scope, note release, trail expiry and random seeking')
