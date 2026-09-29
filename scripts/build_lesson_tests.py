"""Generate reproducible JSON fixtures for the V2 lesson contract."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'data' / 'lesson_tests'


def lesson(rows, end=16):
    return dict(version=2, tempo_bpm=120, fps=60, time_signature=[4, 4],
                string_numbering='1=high E, 6=low E', end_beat=end,
                notes=[dict(id=f'n{i+1}', string=s, fret=f, start_beat=t, duration_beats=d)
                       for i, (s,f,t,d) in enumerate(rows)])


def build():
    ROOT.mkdir(parents=True, exist_ok=True)
    cases = {
        '01_mapping': lesson([(s,f,(s-1)*2+f,0.5) for s in range(1,7) for f in (0,1)]),
        '02_durations': lesson([(1,2,t,d) for t,d in [(0,.25),(1,.5),(2,1),(4,2),(6,4),(10,1.5),(12,'1/3'),('37/3','1/3'),('38/3','1/3')]]),
        '03_chords': lesson([(s,0 if s%2 else 3,(size-2)*3,1) for size in range(2,7) for s in range(1,size+1)]),
        '04_independent_endings': lesson([(s,s,0,s/2) for s in range(1,7)]),
        '05_overlap': lesson([(6,0,0,8)]+[(1,2,t,.5) for t in range(8)]),
        '06_retrigger': lesson([(2,3,0,6),(2,3,1,.5),(2,5,3,1),(2,0,4,1)]),
        '07_silence': lesson([(5,0,1,1),(1,3,8,1)],12),
        '08_boundaries': lesson([(6,0,7,3),(2,3,8,1),(1,2,15,3),(3,9,16,1)],20),
        '09_frets': lesson([(1,f,i*2,1) for i,f in enumerate((0,1,9,10,12,20))]),
        '10_dense': lesson([(1,12,i/4,.25) for i in range(32)],8),
    }
    combined=[]
    for index, data in enumerate(list(cases.values())[:9]):
        from fractions import Fraction
        combined += [(n['string'], n['fret'], str(Fraction(str(n['start_beat']))+index*24), n['duration_beats']) for n in data['notes']]
    cases['11_combined'] = lesson(combined,216)
    for name,data in cases.items():
        (ROOT / (name+'.json')).write_text(json.dumps(data,indent=2)+'\n')
    invalid = {}
    for name,key,value in [('bad_string','string',7),('bad_fret','fret',21),('negative_duration','duration_beats',-1),('negative_start','start_beat',-1)]:
        data=lesson([(1,0,0,1)])
        data['notes'][0][key]=value
        invalid[name]=data
    duplicate=lesson([(1,0,0,1),(2,0,0,1)])
    duplicate['notes'][1]['id']='n1'
    invalid['duplicate_id']=duplicate
    invalid['same_string_conflict']=lesson([(1,0,0,1),(1,3,0,1)])
    folder=ROOT/'invalid'
    folder.mkdir(exist_ok=True)
    for name,data in invalid.items():
        (folder/(name+'.json')).write_text(json.dumps(data,indent=2)+'\n')


if __name__ == '__main__':
    build()
