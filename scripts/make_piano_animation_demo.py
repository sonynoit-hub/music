"""Blender demo with baked animation and a synthetic guide WAV; no external sound assets."""
import argparse
import array
import json
import math
from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from mathutils import Vector
from guitar_video_app.integrations import piano_scene, piano_lesson, piano_effects
from guitar_video_app.instruments.piano.view import prepare
from guitar_video_app.instruments.piano.performance import performance


def build(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    data=dict(version=1,instrument='piano',name='Piano motion study',fps=24,
              tempo_bpm=120,time_signature=[4,4],end_beat=24,notes=[],
              pedal_events=[dict(type='sustain',start_beat=5,duration_beats=3),
                            dict(type='sustain',start_beat=13,duration_beats=5)])
    def note(pitch,start,duration,hand,velocity=80):
        data['notes'].append(dict(id=f'n{len(data["notes"]):03d}',pitch=pitch,
                                 start_beat=start,duration_beats=duration,hand=hand,velocity=velocity))
    for i,pitch in enumerate((60,64,67,72,71,67,64,62)):
        note(pitch,1+i*.5,.4,'right',65+i*5)
    for start,chord in ((1,(48,55)),(5,(45,52)),(9,(41,48)),(13,(43,50)),(17,(48,55))):
        for pitch in chord: note(pitch,start,1.4,'left',72)
    for start,chord in ((5,(60,64,69)),(9,(60,65,69)),(13,(59,62,67)),(17,(60,64,67,72))):
        for pitch in chord: note(pitch,start,1.5,'right',88)
    for i in range(6): note(72,7+i*.5,.3,'right',75+i*4)
    for i,pitch in enumerate((67,69,71,74,72,67)):
        note(pitch,14+i*.5,.4,'right',85)
    prepared=prepare(data)
    notes,_=performance(data,prepared)
    (out/'piano-demo.json').write_text(json.dumps(data,indent=2))
    rate=22050
    samples=[0.0]*(rate*12)
    for event in notes:
        frequency=440*2**((event['pitch']-69)/12)
        duration=event['sound_end']-event['start']
        for i in range(int((duration+.3)*rate)):
            index=round(event['start']*rate)+i
            if index>=len(samples): break
            t=i/rate
            envelope=min(1,t/.008)*math.exp(-1.25*t)*max(0,min(1,(duration+.3-t)/.3))
            tone=sum(math.sin(2*math.pi*frequency*h*t)/h**2 for h in (1,2,3,4))
            samples[index]+=tone*envelope*event['velocity']/127*.12
    pcm=array.array('h',(int(max(-1,min(1,x))*26000) for x in samples))
    if sys.byteorder!='little': pcm.byteswap()
    wav=out/'piano-demo-guide.wav'
    with wave.open(str(wav),'wb') as stream:
        stream.setparams((1,2,rate,0,'NONE','not compressed'))
        stream.writeframes(pcm.tobytes())
    scene=piano_scene.build_scene()
    piano_lesson.install_piano(data)
    scene.render.fps=24
    scene.frame_start=0
    scene.frame_end=287
    # Bake a self-contained review file that plays without trusting embedded Python.
    baked={}
    for pitch in range(21,109):
        obj=bpy.data.objects[piano_scene.key_name(pitch)]
        baked[pitch]=obj.data.materials[0].copy()
    for frame in range(288):
        scene.frame_set(frame)
        piano_effects.bake_frame(frame)
        for pitch,mat in baked.items():
            obj=bpy.data.objects[piano_scene.key_name(pitch)]
            source=obj.data.materials[0]
            color=tuple(source.diffuse_color)
            mat.diffuse_color=color
            mat.keyframe_insert('diffuse_color',frame=frame)
            shader=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
            shader.inputs['Base Color'].default_value=color
            shader.inputs['Base Color'].keyframe_insert('default_value',frame=frame)
            obj.keyframe_insert('rotation_euler',frame=frame)
    bpy.app.handlers.frame_change_post[:]=[h for h in bpy.app.handlers.frame_change_post
                                         if getattr(h,'__name__','')!=piano_lesson.HANDLER]
    bpy.data.texts[piano_lesson.LOADER].use_module=False
    for pitch,mat in baked.items(): bpy.data.objects[piano_scene.key_name(pitch)].data.materials[0]=mat
    target=Vector((0,.38,.3))
    for name,pos,frame in (('ThreeQuarter',(2.5,-3.7,2.6),0),
                           ('Front',(0,-3.8,1.5),96),
                           ('Overhead',(.05,.1,4.5),192),
                           ('Side',(-2.8,-2.2,1.7),240)):
        cam=bpy.data.objects.new('Piano_Demo_'+name,bpy.data.cameras.new('Piano_Demo_'+name))
        scene.collection.objects.link(cam)
        cam.location=pos
        cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
        cam.data.lens={'ThreeQuarter':65,'Front':58,'Overhead':48,'Side':55}[name]
        marker=scene.timeline_markers.new(name,frame=frame)
        marker.camera=cam
        if frame==0: scene.camera=cam
    editor=scene.sequence_editor_create()
    editor.strips.new_sound('Synthetic guide WAV',str(wav),channel=1,frame_start=0)
    scene.render.resolution_x=800
    scene.render.resolution_y=800
    scene.render.resolution_percentage=100
    scene.render.engine='CYCLES'
    scene.cycles.samples=16
    scene.cycles.use_denoising=True
    scene.render.image_settings.file_format='PNG'
    scene.frame_set(132)
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'piano-animation.blend'))
    print('Saved baked piano animation and guide WAV',flush=True)
    return scene


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    build(args.out)
