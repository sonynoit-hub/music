"""Generate the 32-measure mixed lesson and independent inspection checkpoints."""
import json
from fractions import Fraction
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from guitar_video_app.core.lesson_v2 import prepare, state


def build():
    notes = []

    def add(string, fret, start, duration, identity=None):
        notes.append(dict(id=identity or f'n{len(notes)+1:03d}', string=string, fret=fret,
                          start_beat=str(Fraction(str(start))), duration_beats=str(Fraction(str(duration)))))

    # Measures 1-4: opening rest, six open strings, then fret and string jumps.
    for i in range(6):
        add(i+1, 0, 1+i/2, .5)
    for i,fret in enumerate((1,3,5,7,9,12,15,20)):
        add(i%6+1, fret, 4+i, .75)
    for i in range(8):
        add(1 if i%2 else 6, (0,3,5,7)[i%4], 12+i/2, .25)

    # Measures 5-8: sixteenth through whole notes, dotted values and exact triplets.
    for i,(start,duration) in enumerate(((16,.25),(16.5,.5),(17,1),(18,2),(20,4),(24,1.5),(26,.75))):
        add(i%6+1, (0,2,3,5,7,9,12)[i], start, duration)
    for i in range(12):
        add(i%3+1, (0,3,5)[i%3], Fraction(28)+Fraction(i,3), Fraction(1,3))

    # Measures 9-12: two through six-note chords followed by independent endings.
    voicing = {1:0, 2:0, 3:1, 4:2, 5:2, 6:0}
    for size,start in zip(range(2,7),(32,34,36,38,40)):
        for string in range(1,size+1):
            add(string,voicing[string],start,1.5)
    for string in range(1,7):
        add(string,voicing[string],44,string/2,f'chord_end_s{string}')

    # Measures 13-16: sustained bass with shorter melody notes above it.
    for start in (48,52,56,60):
        add(6,0 if start%8==0 else 3,start,4,f'bass_{start}')
        add(4,2,start,2)
        for i in range(8):
            add(1+i%2,(0,3,5,3)[i%4],start+i/2,.375)

    # Measures 17-20: ascending and descending arpeggios, with overlapping tails.
    for block,start in enumerate((64,68,72,76)):
        order = list(range(6,0,-1)) if block%2==0 else list(range(1,7))
        for i,string in enumerate(order):
            add(string,voicing[string],start+i/2,2)

    # Measures 21-24: retriggers, fret changes, rests and a cross-page bass sustain.
    add(2,3,80,6,'long_retrigger')
    add(2,3,81,.5,'short_retrigger')
    add(2,5,82,1,'fret_change')
    add(2,0,83,.5,'open_change')
    # Measure 22 is completely silent.
    for i in range(8):
        add(1 if i%2 else 5,(0,5,7,9)[i%4],88+i/2,.25)
    add(6,0,95,3,'cross_page_bass')

    # Measures 25-28: simultaneous page onset, two-digit frets and sixteenth runs.
    for string,fret in ((1,12),(2,10),(3,9)):
        add(string,fret,96,1,f'page_chord_s{string}')
    for i in range(8):
        add(1+i%3,(9,10,12,15,20)[i%5],98+i/4,.25)
    for i in range(16):
        add(1, (10,12,15,12)[i%4],100+i/4,.25)
    for start in (104,106,108,110):
        for string,fret in ((1,12),(2,12),(3,12)):
            add(string,fret,start,1)

    # Measures 29-32: combined phrase, whole-note final chord, final silent measure.
    add(6,0,112,8,'final_bass')
    for i in range(16):
        add(1+i%3,(0,3,5,7)[i%4],112+i/2,.5)
    for string in range(1,7):
        add(string,voicing[string],120,4,f'final_chord_s{string}')
    data = dict(version=2, name='32-measure mixed guitar test', tempo_bpm=90, fps=60,
                time_signature=[4,4], string_numbering='1=high E, 6=low E', end_beat=128,
                sections=[dict(measures=[i*4+1,i*4+4],name=name) for i,name in enumerate((
                    'Single notes and mapping','Durations and triplets','Chords and independent endings',
                    'Bass and melody','Overlapping arpeggios','Retriggers and rests',
                    'Page boundaries and high frets','Combined ending'))],notes=notes)
    checkpoints = [
        dict(beat='0',active_ids=[]),
        dict(beat='44',active_ids=[f'chord_end_s{i}' for i in range(1,7)]),
        dict(beat='89/2',active_ids=[f'chord_end_s{i}' for i in range(2,7)]),
        dict(beat='47',active_ids=[]),
        dict(beat='81',active_ids=['short_retrigger']),
        dict(beat='163/2',active_ids=[]),
        dict(beat='85',active_ids=[]),
        dict(beat='95',active_ids=['cross_page_bass']),
        dict(beat='96',active_ids=['cross_page_bass','page_chord_s1','page_chord_s2','page_chord_s3']),
        dict(beat='97',active_ids=['cross_page_bass']),
        dict(beat='120',active_ids=[f'final_chord_s{i}' for i in range(1,7)]),
        dict(beat='124',active_ids=[]),
        dict(beat='128',active_ids=[]),
    ]
    compiled=prepare(data)
    for check in checkpoints:
        frame=Fraction(check['beat'])*compiled['frames_per_beat']
        assert set(n['id'] for n in state(compiled,frame)[2])==set(check['active_ids']),check
    folder=ROOT/'data/lesson_tests'
    (folder/'12_complex_32_measures.json').write_text(json.dumps(data,indent=2)+'\n')
    (folder/'12_complex_32_measures.expected.json').write_text(json.dumps(dict(checkpoints=checkpoints),indent=2)+'\n')
    print(f'Generated {len(notes)} notes, 32 measures, 90 BPM; {len(checkpoints)} checkpoints passed.')


if __name__ == '__main__':
    build()
