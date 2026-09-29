"""Verify the generated MIDI and WAV against the current complex JSON lesson."""
import array
import json
from pathlib import Path
import sys
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import mido
from guitar_video_app.core.lesson_v2 import prepare
from guitar_video_app.core.note_mapping import STANDARD_TUNING

data=json.loads((ROOT/'data/lesson_tests/12_complex_32_measures.json').read_text())
lesson=prepare(data)
midi=mido.MidiFile(ROOT/'outputs/complex_32_measures.mid')
expected=sorted((round(n[k]*960),n['string']-1,STANDARD_TUNING[n['string']]+n['fret'],on)
                for n in lesson['notes'] for k,on in [('start',True),('end',False)])
actual=[]
for track in midi.tracks:
    tick=0
    for msg in track:
        tick+=msg.time
        if msg.type in ('note_on','note_off'):
            actual.append((tick,msg.channel,msg.note,msg.type=='note_on' and msg.velocity>0))
assert sorted(actual)==expected
assert abs(midi.length-128*60/90)<.001
with wave.open(str(ROOT/'outputs/complex_32_measures.wav')) as wav:
    assert wav.getnchannels()==2 and wav.getsampwidth()==2
    assert abs(wav.getnframes()/wav.getframerate()-128*60/90)<1/wav.getframerate()
    samples=array.array('h',wav.readframes(wav.getnframes()))
    if sys.byteorder!='little':samples.byteswap()
    peak=max(abs(x) for x in samples)
    assert 100 < peak < 32767, f'Silent or clipped audio: {peak}'
    # Opening rest and final silent measure should remain silent after release.
    assert max(abs(x) for x in samples[:22050]) < 10
    assert max(abs(x) for x in samples[-44100:]) < 10
print(f'PASS: {len(actual)//2} MIDI notes match JSON pitches/start/end; stereo WAV, 85.333 seconds, peak {peak}/32767, rests verified.')
