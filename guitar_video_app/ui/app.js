const $ = id => document.getElementById(id);
let songs = [], current = null, blender = {ok:false}, busy = false, lesson = null, peaks = [], cursor = 0, loadToken = 0, tabHits = [], selectedTabNote = null, lastTransfer = null, renderJob = {status:'idle'}, renderTimer = null;
const audio = $('audio');
const beat = x => typeof x === 'string' && x.includes('/') ? x.split('/').map(Number).reduce((a,b)=>a/b) : Number(x);
function tempoMap(data){const points=[[0,Number(data.tempo_bpm)],...(data.tempo_changes||[]).map(c=>[beat(c.beat),Number(c.bpm)])];let seconds=0;return points.map(([b,bpm],i)=>{if(i)seconds+=(b-points[i-1][0])*60/points[i-1][1];return {beat:b,seconds,bpm};});}
const segmentAt = (map,key,value) => map.reduce((found,s)=>s[key]<=value?s:found,map[0]);
const beatAt = (map,seconds) => {const s=segmentAt(map,'seconds',seconds);return s.beat+(seconds-s.seconds)*s.bpm/60;};
const secondsAt = (map,b) => {const s=segmentAt(map,'beat',b);return s.seconds+(b-s.beat)*60/s.bpm;};
const clock = seconds => {seconds=Math.max(0,seconds||0);return `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(Math.floor(seconds%60)).padStart(2,'0')}`;};
function icons(){lucide.createIcons();}
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';$('message').hidden=false;}
async function api(url,options={}){const response=await fetch(url,options);const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));return data;}
function jsonOptions(method,data){return {method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)};}
function setBusy(value){busy=value;document.querySelectorAll('button').forEach(b=>b.disabled=value);if(!value){$('send').disabled=!current?.json_name||!current?.wav_name||!blender.ok;$('saveBlend').disabled=!blender.ok;$('previousPage').disabled=!lesson;$('nextPage').disabled=!lesson;$('generateMidi').disabled=!current?.wav_name;$('suggestTiming').disabled=$('applyTiming').disabled=$('tidyNotes').disabled=!current?.json_name;syncAssetButtons();renderUI();}}
async function action(fn){if(busy)return;setBusy(true);$('message').textContent='';$('message').hidden=true;try{await fn();}catch(e){message(e.message,true);}finally{setBusy(false);}}
function isSynced(){return current && blender.ok && blender.song_id===current.id && blender.revision===current.revision;}
function connectionUI(){
 $('connectionDot').className=`dot ${blender.ok?'teal':''}`;$('connectionLabel').textContent=blender.ok?'Blender connected':'Blender disconnected';$('connect').innerHTML=`<i data-lucide="${blender.ok?'refresh-cw':'plug'}"></i> ${blender.ok?'Refresh':'Connect'}`;
 $('sceneName').textContent=blender.scene||'—';$('cameraName').textContent=blender.camera||'—';$('blendFile').textContent=blender.file?.split('/').pop()||'—';
 const sent=isSynced()&&lastTransfer?.song===current.id&&lastTransfer.revision===current.revision?` · sent ${lastTransfer.time} · ${lastTransfer.notes} notes`:'';
 $('syncStatus').textContent=isSynced()?'Up to date in Blender'+sent:current?.synced_revision?'Changes not applied':'Not sent to Blender';$('syncStatus').className=isSynced()?'synced':'';
 icons();if(!busy)setBusy(false);
}
async function refreshConnection(){try{blender=await api('/api/blender');}catch{blender={ok:false};}connectionUI();}
function library(){
 $('songs').replaceChildren();const query=$('search').value.toLowerCase();
 for(const row of songs.filter(s=>s.name.toLowerCase().includes(query))){const button=document.createElement('button');button.className='song'+(row.id===current?.id?' selected':'');button.innerHTML='<i data-lucide="music-2"></i><span><strong></strong><small></small></span>';button.querySelector('strong').textContent=row.name;button.querySelector('small').textContent=row.summary?`${row.summary.notes} notes · ${row.summary.measures} measures`:'No lesson imported';button.onclick=()=>{if(!busy)selectSong(row);};$('songs').append(button);}
 if(!$('songs').children.length){const empty=document.createElement('p');empty.className='empty';empty.textContent='No matching songs';$('songs').append(empty);}
 document.querySelectorAll('.song').forEach(b=>b.disabled=busy);icons();
}
function fields(){
 const s=current?.summary;$('name').value=current?.name||'';$('name').disabled=!current;document.title=current?`${current.name} · Guitar Lesson Studio`:'Guitar Lesson Studio';$('offset').value=current?.offset||0;$('tempoInput').value=current?.summary?.bpm??'';$('firstBeat').value=current?.json_name&&s?firstBeatTime(s,current.offset||0):'';$('revision').textContent=current?`Revision ${current.revision}`:'No song selected';
 $('videoTitle').value=current?(current.title??current.name):'';$('videoSubtitle').value=current?.subtitle||'';$('videoTitle').disabled=$('videoSubtitle').disabled=!current;
 $('midiName').textContent=current?.midi_name||'No file selected';$('jsonName').textContent=current?.json_name||'No file selected';$('wavName').textContent=current?.wav_name||'No file selected';
 $('notes').textContent=s?.notes??'—';$('tempo').textContent=s?`${s.bpm} BPM`+(s.tempo_changes?` + ${s.tempo_changes} change${s.tempo_changes>1?'s':''}`:''):'—';$('measures').textContent=s?.measures??'—';$('duration').textContent=s?clock(s.duration):'—';$('fps').textContent=s?`${s.fps} fps`:'—';$('signature').textContent=s?s.signature.join(' / '):'—';
 const layer=s?.music_layer||{};$('musicLayerFormat').textContent=layer.format?layer.format.toUpperCase():'—';$('layerTracks').textContent=layer.tracks??'—';$('layerBeats').textContent=layer.beats??'—';$('layerTempo').textContent=layer.tempo_changes??'—';$('layerSignature').textContent=layer.time_signature_changes??'—';
 const mismatch=s&&current.audio_duration!=null&&Math.abs(current.audio_duration+current.offset-s.duration)>.1;
 $('durationWarning').hidden=!mismatch;$('durationWarning').textContent=mismatch?`Lesson ${s.duration.toFixed(2)} s · audio ends at ${(current.audio_duration+current.offset).toFixed(2)} s with offset.`:'';
 syncAssetButtons();library();connectionUI();
}
function updateSong(row){current=row;songs=songs.map(s=>s.id===row.id?row:s);fields();}
function assetUrl(kind,download=false){const path=kind==='json'?'lesson':kind==='wav'?'audio':'midi';return current?`/api/songs/${current.id}/${path}?r=${current.revision}${download?'&download=true':''}`:'#';}
function syncAssetButtons(){const available={Midi:!!current?.midi_name,Json:!!current?.json_name,Wav:!!current?.wav_name};for(const [suffix,enabled] of Object.entries(available)){const open=$('open'+suffix),download=$('download'+suffix);if(open)open.disabled=busy||!enabled;if(download)download.disabled=busy||!enabled;}}
function downloadAsset(kind){if(!current)return;const suffix=kind==='json'?'Json':kind==='wav'?'Wav':'Midi';let name=current?.[`${kind}_name`]||`lesson.${kind==='midi'?'mid':kind}`;if(kind==='wav')name=name.replace(/\.[^.]*$/,'')+'.wav';const link=document.createElement('a');link.href=assetUrl(kind,true);link.download=name;document.body.append(link);link.click();link.remove();message(`${suffix} download started.`);}
async function selectSong(row){
 const token=++loadToken;audio.pause();current=row;lesson=null;peaks=[];cursor=0;selectedTabNote=null;tabHits=[];hideTabEditor();fields();$('message').hidden=true;draw();
 if(row.wav_name){audio.src=`/api/songs/${row.id}/audio?r=${row.revision}`;audio.load();}else{audio.removeAttribute('src');audio.load();}
 if(row.json_name){try{const data=await api(`/api/songs/${row.id}/lesson?r=${row.revision}`);if(token!==loadToken)return;lesson=data;lesson.tempoMap=tempoMap(lesson);lesson.notes=lesson.notes.map(n=>({...n,start:beat(n.start_beat),end:beat(n.start_beat)+beat(n.duration_beats)})).sort((a,b)=>a.start-b.start);const last={};for(const n of lesson.notes){if(last[n.string])last[n.string].end=Math.min(last[n.string].end,n.start);last[n.string]=n;}prepareNotation(lesson);draw();setBusy(busy);}catch(e){message(e.message,true);}}
 if(row.wav_name){try{const bytes=await (await fetch(`/api/songs/${row.id}/audio?r=${row.revision}`)).arrayBuffer();const ctx=new AudioContext();const buffer=await ctx.decodeAudioData(bytes);await ctx.close();if(token!==loadToken)return;const samples=buffer.getChannelData(0);peaks=Array.from({length:500},(_,i)=>{let max=0;for(let j=Math.floor(i*samples.length/500);j<Math.floor((i+1)*samples.length/500);j+=8)max=Math.max(max,Math.abs(samples[j]));return max;});draw();}catch(e){if(token===loadToken)message('The browser could not decode the audio preview. '+e.message,true);}}
}
async function persist(){if(!current)return;const name=$('name').value.trim();const offset=Number($('offset').value);if(!name)throw Error('Enter a song name.');if(!Number.isFinite(offset)||Math.abs(offset)>60)throw Error('Audio offset must be between -60 and 60 seconds.');const typed=$('videoTitle').value.trim(),title=current.title==null&&typed===current.name?null:typed,subtitle=$('videoSubtitle').value.trim();const row=await api(`/api/songs/${current.id}`,jsonOptions('PATCH',{name,offset,title,subtitle}));updateSong(row);draw();}
function canvas(id){const c=$(id),rect=c.getBoundingClientRect(),dpr=devicePixelRatio||1;c.width=Math.round(rect.width*dpr);c.height=Math.round(rect.height*dpr);const ctx=c.getContext('2d');ctx.scale(dpr,dpr);return {c,ctx,w:rect.width,h:rect.height};}
const OPEN_MIDI={1:64,2:59,3:55,4:50,5:45,6:40},PITCHES=['c','c#','d','d#','e','f','f#','g','g#','a','a#','b'];
const NOTE_VALUES=[[16,'w',0],[12,'h',1],[8,'h',0],[6,'q',1],[4,'q',0],[3,'8',1],[2,'8',0],[1,'16',0]];
let notationKey=null,notationNotes=[],notationCursorTop=0;
// Guitar notation is written an octave above sounding pitch; lesson timing is snapped to 8ths or 16ths for display only.
function writtenPitch(note){return OPEN_MIDI[note.string]+note.fret+12;}
// Same bass rule as is_bass in core/retime.py; grid is in 16ths: 2 unless over a tenth of notes sit on in-between 16ths.
function prepareNotation(data){
 const pitch=n=>OPEN_MIDI[n.string]+n.fret,notes=data.notes,measure=data.time_signature[0]*4/data.time_signature[1];
 for(const n of notes)n.bass=n.string>=5||(n.string===4&&(n.end-n.start>=1||Math.abs(n.start/measure-Math.round(n.start/measure))<1e-6)&&!notes.some(o=>o!==n&&pitch(o)<pitch(n)&&Math.floor(o.start/measure+1e-6)===Math.floor(n.start/measure+1e-6)&&o.start<=n.start&&n.start<o.end));
 const offbeat=notes.filter(n=>Math.abs(n.start*4-Math.round(n.start*4))<=.4&&Math.round(n.start*4)%2).length;
 data.grid=offbeat<=notes.length/10?2:1;
}
function splitValues(pos,length,beatUnits){const pieces=[];while(length>0){const room=pos%beatUnits?beatUnits-pos%beatUnits:length;const [len,duration,dots]=NOTE_VALUES.find(([v])=>v<=Math.min(length,room));pieces.push({pos,len,duration,dots});pos+=len;length-=len;}return pieces;}
function staffStep(pitch){return 'cdefgab'.indexOf(PITCHES[pitch%12][0])+7*Math.floor(pitch/12);}
function measureEvents(index,bass){
 const [num,den]=lesson.time_signature,units=num*16/den,base=index*units,g=lesson.grid||1,q=b=>Math.round(b*4/g)*g;
 const notes=lesson.notes.filter(n=>!!n.bass===bass).map(n=>({n,s:q(n.start),e:Math.max(q(n.start)+1,q(n.end))})).filter(x=>x.s>=base&&x.s<base+units);
 const onsets=[...new Set(notes.map(x=>x.s))].sort((a,b)=>a-b),events=[];let pos=0;
 onsets.forEach((onset,i)=>{const at=onset-base,next=i+1<onsets.length?onsets[i+1]-base:units,chord=notes.filter(x=>x.s===onset);if(at>pos)events.push({pos,len:at-pos});const end=Math.min(next,Math.max(...chord.map(x=>x.e))-base);events.push({pos:at,len:end-at,notes:chord.map(x=>x.n)});pos=end;});
 if(pos<units)events.push({pos,len:units-pos});
 return {events,units,beatUnits:16/den};
}
function drawNotation(page,left,right,w,xAt){
 const box=$('notation');
 if(!lesson||!window.Vex){box.innerHTML='';notationNotes=[];notationKey=null;return;}
 const key=`${current.id}|${current.revision}|${page}|${Math.round(w)}`;if(key===notationKey)return;
 notationKey=key;notationNotes=[];box.innerHTML='';
 const VF=Vex.Flow,[num,den]=lesson.time_signature,measure=num*4/den;
 // Size the staff to the whole song's range so the tab does not jump between pages.
 const steps=lesson.notes.map(n=>staffStep(writtenPitch(n))),above=Math.max(30,(Math.max(...steps)-staffStep(77))*5+40),below=Math.max(30,(staffStep(64)-Math.min(...steps))*5+40);
 const renderer=new VF.Renderer(box,VF.Renderer.Backends.SVG);renderer.resize(w,above+40+below);box.style.height=`${above+40+below}px`;
 const ctx=renderer.getContext(),stave=new VF.Stave(6,above-40,right-6);stave.addClef('treble').addTimeSignature(`${num}/${den}`).setContext(ctx).draw();
 const lineTop=stave.getYForLine(0),lineBottom=stave.getYForLine(4);ctx.fillRect((left+right)/2,lineTop,1,lineBottom-lineTop);notationCursorTop=lineTop-12;
 // Melody stems up and bass stems down, with hidden bass rests.
 const parts=[{bass:false,stem:VF.Stem.UP,rest:'b/4'},{bass:true,stem:VF.Stem.DOWN,rest:null}];
 for(let m=0;m<2;m++){
  const index=page*2+m;if(index>=(current.summary?.measures||0))continue;
  const start=index*measure,voices=[],beams=[],ties=[],placed=[];
  for(const part of parts){
   const {events,units,beatUnits}=measureEvents(index,part.bass),wholeRest=events.length===1&&!events[0].notes,tickables=[];
   for(const event of events){
    const keys=event.notes?[...new Set(event.notes.map(writtenPitch))].sort((a,b)=>a-b).map(p=>`${PITCHES[p%12]}/${Math.floor(p/12)-1}`):[part.rest||'b/4'];
    const pieces=wholeRest?[{pos:0,len:units,duration:'w',dots:0}]:splitValues(event.pos,event.len,beatUnits);let previous=null;
    for(const piece of pieces){
     const begin=start+piece.pos/4;
     if(!event.notes&&!part.rest){tickables.push(new VF.GhostNote({duration:piece.duration,dots:piece.dots}));continue;}
     const note=new VF.StaveNote({keys,duration:piece.duration+(event.notes?'':'r'),dots:piece.dots,stem_direction:part.stem,clef:'treble'});
     if(piece.dots)VF.Dot.buildAndAttach([note],{all:true});
     tickables.push(note);placed.push({sn:note,rest:!event.notes,beat:begin,end:begin+piece.len/4,x:wholeRest?(xAt(start)+xAt(start+measure-1e-6))/2:xAt(begin)});
     if(previous&&event.notes){const indices=keys.map((_,i)=>i);ties.push(new VF.StaveTie({first_note:previous,last_note:note,first_indices:indices,last_indices:indices}));}
     previous=note;
    }
   }
   voices.push(new VF.Voice({num_beats:num,beat_value:den}).setMode(VF.Voice.Mode.SOFT).addTickables(tickables));
   beams.push(...VF.Beam.generateBeams(tickables.filter(t=>t instanceof VF.StaveNote),{groups:VF.Beam.getDefaultBeamGroups(`${num}/${den}`),stem_direction:part.stem}));
  }
  VF.Accidental.applyAccidentals(voices,'C');
  new VF.Formatter().joinVoices(voices).format(voices,(right-left)/2);
  // Place each note at its tab column so both staves share one time axis and cursor.
  for(const voice of voices)for(const t of voice.getTickables()){t.setStave(stave);}
  for(const p of placed){const tc=p.sn.getTickContext();tc.setX(tc.getX()+p.x-(p.sn.getAbsoluteX()+p.sn.getGlyphWidth()/2));}
  voices.forEach(v=>v.draw(ctx,stave));beams.forEach(b=>b.setContext(ctx).draw());ties.forEach(t=>t.setContext(ctx).draw());
  for(const p of placed)p.el=p.sn.getSVGElement();notationNotes.push(...placed);
 }
}
function draw(){
 let {ctx,w,h}=canvas('waveform');ctx.fillStyle='#eef3f0';ctx.fillRect(0,0,w,h);let progress=audio.duration?audio.currentTime/audio.duration:0;
 const max=Math.max(.01,...peaks);for(let i=0;i<peaks.length;i++){const x=i*w/peaks.length;const size=Math.max(2,peaks[i]/max*(h-24));ctx.fillStyle=x<w*progress?'#168676':'#b7cec3';ctx.fillRect(x,h/2-size/2,Math.max(1,w/peaks.length-1),size);}if(!peaks.length){ctx.fillStyle='#b7cec3';ctx.fillRect(12,h/2,w-24,1);}ctx.fillStyle='#168676';ctx.fillRect(w*progress,0,1,h);
 $('playTime').textContent=`${clock(audio.currentTime)} / ${clock(current?.audio_duration)}`;
 ({ctx,w,h}=canvas('tablature'));ctx.fillStyle='white';ctx.fillRect(0,0,w,h);const left=78,right=w-20,top=28,gap=18;
 if(!lesson){$('pageLabel').textContent='Measures —';drawNotation();$('scoreCursor').hidden=true;return;}
 ctx.fillStyle='#343e38';ctx.font='bold 14px Georgia, serif';ctx.textAlign='center';ctx.textBaseline='middle';['T','A','B'].forEach((letter,i)=>ctx.fillText(letter,34,top+gap*(1+i*1.5)));
 const measure=lesson.time_signature[0]*4/lesson.time_signature[1],pageBeats=measure*2;const beatNow=beatAt(lesson.tempoMap,cursor);
 const page=Math.min(Math.max(0,Math.ceil(beat(lesson.end_beat)/pageBeats)-1),Math.max(0,Math.floor((beatNow+1e-6)/pageBeats)));$('pageLabel').textContent=`Measures ${page*2+1}–${Math.min(page*2+2,current.summary.measures)}`;
 function xAt(b){const local=Math.max(0,Math.min(2,(b-page*pageBeats)/measure)),m=Math.min(1,Math.floor(local));return left+(right-left)*(m*.5+.012+.476*(local-m));}
 const visible=lesson.notes.filter(n=>n.start>=page*pageBeats&&n.start<(page+1)*pageBeats).sort((a,b)=>a.start-b.start||a.string-b.string);
 ctx.font='15px Arial';ctx.textAlign='center';ctx.textBaseline='middle';let labels=visible.map(n=>{const text=String(n.fret),x=Math.max(left+(right-left)*.012,Math.min(right-(right-left)*.012,xAt(n.start))),y=top+(n.string-1)*gap,width=ctx.measureText(text).width+10;return {...n,text,x,rawX:x,y,width};});
 const denseGroups=[],edge=left+(right-left)*.012,rightEdge=right-(right-left)*.012,pad=8;for(let string=1;string<=6;string++){const row=labels.filter(n=>n.string===string).sort((a,b)=>a.rawX-b.rawX);for(let i=1;i<row.length;i++){const need=(row[i-1].width+row[i].width)/2+pad;if(row[i].x-row[i-1].x<need)row[i].x=row[i-1].x+need;}let overflow=row.length?row[row.length-1].x-rightEdge:0;if(overflow>0){for(const n of row)n.x-=overflow;for(let i=row.length-2;i>=0;i--){const need=(row[i].width+row[i+1].width)/2+pad;if(row[i+1].x-row[i].x<need)row[i].x=row[i+1].x-need;}}if(row.length&&row[0].x<edge){const shift=edge-row[0].x;for(const n of row)n.x+=shift;}let group=[];for(const n of row){const moved=Math.abs(n.x-n.rawX)>1;if(!group.length){group=moved?[n]:[];continue;}const prev=group[group.length-1],close=n.x-prev.x<(prev.width+n.width)/2+pad*2;if(moved&&close){group.push(n);}else{if(group.length>1)denseGroups.push(group);group=moved?[n]:[];}}if(group.length>1)denseGroups.push(group);}
 for(let i=0;i<6;i++){const y=top+i*gap;const gaps=labels.filter(n=>n.string===i+1).map(n=>[n.x-n.width/2,n.x+n.width/2]).sort((a,b)=>a[0]-b[0]);let start=left;ctx.strokeStyle='#b6bcb8';ctx.lineWidth=.6;for(const [a,b] of gaps){if(a>start){ctx.beginPath();ctx.moveTo(start,y);ctx.lineTo(Math.max(start,a),y);ctx.stroke();}start=Math.max(start,b);}if(start<right){ctx.beginPath();ctx.moveTo(start,y);ctx.lineTo(right,y);ctx.stroke();}}
 for(const x of [left,(left+right)/2,right]){ctx.strokeStyle='#8f9993';ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,top+5*gap);ctx.stroke();}
 for(const group of denseGroups){if(group.every(n=>Math.abs(n.x-n.rawX)<1))continue;const first=group[0],last=group[group.length-1],arcTop=Math.max(8,first.y-13),arcLift=Math.min(12,(last.x-first.x)/5+5);ctx.strokeStyle='#5c6862';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(first.x,arcTop);ctx.quadraticCurveTo((first.x+last.x)/2,arcTop-arcLift,last.x,arcTop);ctx.stroke();}
 tabHits=labels.map(n=>({id:n.id,x:n.x,y:n.y,w:Math.max(n.width,22),h:22}));
 for(const n of labels){const selected=selectedTabNote&&selectedTabNote.id===n.id;if(selected){ctx.fillStyle='#e6f3ef';ctx.fillRect(n.x-n.width/2,n.y-11,n.width,22);ctx.strokeStyle='#087c70';ctx.strokeRect(n.x-n.width/2,n.y-11,n.width,22);}ctx.fillStyle=selected?'#075f55':n.start<=beatNow&&beatNow<n.end?'#087c70':'#343e38';ctx.fillText(n.text,n.x,n.y);}
 drawNotation(page,left,right,w,xAt);
 for(const p of notationNotes)p.el?.classList.toggle('playing',!p.rest&&p.beat<=beatNow&&beatNow<p.end);
 const notationHeight=$('notation').offsetHeight,cursorLine=$('scoreCursor');cursorLine.hidden=false;cursorLine.style.left=`${xAt(beatNow)-.75}px`;const cursorTop=notationHeight?notationCursorTop:notationHeight+top-6;cursorLine.style.top=`${cursorTop}px`;cursorLine.style.height=`${notationHeight+top+5*gap+6-cursorTop}px`;
}
audio.addEventListener('timeupdate',()=>{cursor=Math.max(0,audio.currentTime+(current?.offset||0));draw();});audio.addEventListener('loadedmetadata',draw);
$('waveform').onclick=e=>{if(Number.isFinite(audio.duration)){const r=e.currentTarget.getBoundingClientRect();audio.currentTime=Math.max(0,Math.min(audio.duration,(e.clientX-r.left)/r.width*audio.duration));}};
$('tablature').onclick=e=>{if(!lesson)return;const r=e.currentTarget.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;const hit=tabHits.find(n=>x>=n.x-n.w/2&&x<=n.x+n.w/2&&y>=n.y-n.h/2&&y<=n.y+n.h/2);if(!hit)return;const note=lesson.notes.find(n=>n.id===hit.id);if(note)showTabEditor(note);};
function showTabEditor(note){selectedTabNote=note;$('selectedNote').textContent=`${note.id} · beat ${note.start}`;$('editString').value=note.string;$('editFret').value=note.fret;$('tabEditor').hidden=false;draw();icons();}
function hideTabEditor(){selectedTabNote=null;if($('tabEditor'))$('tabEditor').hidden=true;draw();}
function pageMove(direction){if(!lesson)return;const span=lesson.time_signature[0]*4/lesson.time_signature[1]*2,page=Math.floor((beatAt(lesson.tempoMap,cursor)+.01)/span)+direction;cursor=Math.max(0,Math.min(current.summary.duration-.001,secondsAt(lesson.tempoMap,page*span)));if(audio.src)audio.currentTime=Math.max(0,cursor-current.offset);draw();}
$('previousPage').onclick=()=>pageMove(-1);$('nextPage').onclick=()=>pageMove(1);
$('connect').onclick=()=>action(async()=>{blender=await api('/api/blender/connect',{method:'POST'});connectionUI();message('Blender connected.');});
$('name').onkeydown=e=>{if(e.key==='Enter')e.target.blur();if(e.key==='Escape'){e.target.value=current?.name||'';e.target.blur();}};
$('name').onchange=()=>{if(!$('name').value.trim()){$('name').value=current?.name||'';return;}action(async()=>{await persist();message('Song name saved.');});};$('offset').onchange=()=>action(persist);
for(const id of ['videoTitle','videoSubtitle']){$(id).onkeydown=e=>{if(e.key==='Enter')e.target.blur();};$(id).onchange=()=>action(async()=>{await persist();message('Video title saved. Send to Blender or render to see it.');});}
$('send').onclick=()=>action(async()=>{await persist();message('Sending lesson and audio to Blender…');const result=await api(`/api/songs/${current.id}/send`,{method:'POST'});lastTransfer={song:result.song.id,revision:result.song.revision,time:new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}),notes:result.blender.note_count};updateSong(result.song);await refreshConnection();message('Lesson and audio applied. Blender is at frame 0. Save the Blender file to keep this transfer.');});
$('saveBlend').onclick=()=>action(async()=>{await api('/api/blender/save',{method:'POST'});message('Blender file saved.');});
function renderUI(){
 const job=renderJob,running=job.status==='running',ready=!!current?.json_name&&!!current?.wav_name,label=job.mode==='full'?'full song':'4 s test';
 $('renderTest').disabled=$('renderFull').disabled=busy||running||!ready;$('renderCancel').disabled=!running;
 $('renderState').textContent={idle:'Idle',running:'Rendering',done:'Done',failed:'Failed',cancelled:'Cancelled'}[job.status]||job.status;
 $('renderProgress').hidden=!running;
 if(running){const total=job.frame_end-job.frame_start+1,done=job.frame==null?0:job.frame-job.frame_start;$('renderBar').style.width=`${Math.min(100,Math.round(100*done/total))}%`;$('renderText').textContent=`${job.song_name} · ${label} · frame ${job.frame??'—'} / ${job.frame_end} · ${clock(Date.now()/1000-job.started)} elapsed`;}
 const note=job.status==='done'?`${job.song_name} · ${label} · ${job.name}`:job.status==='failed'?`Render failed: ${job.error}`:job.status==='cancelled'?'Render cancelled.':'';
 $('renderNote').hidden=!note;$('renderNote').textContent=note;$('renderNote').className='render-note'+(job.status==='failed'?' error':'');
 $('renderResult').hidden=job.status!=='done';
 if(job.status==='done'){$('renderOpen').href=`/api/render/video?id=${job.id}`;$('renderDownload').href=`/api/render/video?id=${job.id}&download=true`;}
}
async function refreshRender(){const before=renderJob.status;try{renderJob=await api('/api/render');}catch{}renderUI();clearTimeout(renderTimer);if(renderJob.status==='running')renderTimer=setTimeout(refreshRender,1000);else if(before==='running'&&renderJob.status==='done')message('Render finished. Open or download the video in the Render video panel.');else if(before==='running'&&renderJob.status==='failed')message(`Render failed: ${renderJob.error}`,true);}
function startRender(mode){action(async()=>{if(!current)throw Error('Select a song first.');await persist();renderJob=await api(`/api/songs/${current.id}/render`,jsonOptions('POST',{mode}));message(mode==='full'?'Rendering the full song in background Blender…':'Rendering a 4-second test in background Blender…');refreshRender();});}
// Audio time of the first measure start at or after the audio begins (lesson beat 0 is at -offset).
function firstBeatTime(summary,offset){const measureSeconds=summary.signature[0]*4/summary.signature[1]*60/Number(summary.bpm);return +(-offset+Math.ceil(offset/measureSeconds-1e-6)*measureSeconds).toFixed(3);}
$('importLink').onclick=()=>action(async()=>{if(!current)throw Error('Create a song first.');const url=$('linkUrl').value.trim();if(!url)throw Error('Paste a YouTube, Instagram or TikTok link.');const replaced=!!current.wav_name;if(replaced&&!confirm("Replace this song's audio? Its MIDI and lesson JSON will be cleared."))return;message('Downloading audio from the link…');const row=await api(`/api/songs/${current.id}/assets/link`,jsonOptions('POST',{url}));songs=songs.map(s=>s.id===row.id?row:s);await selectSong(row);$('linkUrl').value='';message(replaced?'Audio replaced from the link. Previous MIDI and lesson JSON were cleared; generate MIDI again for this audio.':'Audio imported from the link. Next, generate MIDI from it.');});
$('linkUrl').onkeydown=e=>{if(e.key==='Enter')$('importLink').click();};
$('usePlayhead').onclick=()=>{$('firstBeat').value=audio.currentTime.toFixed(3);};
$('suggestTiming').onclick=()=>action(async()=>{const s=await api(`/api/songs/${current.id}/timing-suggestion`);$('tempoInput').value=s.tempo_bpm;$('firstBeat').value=s.first_beat;message(`Suggested ${s.tempo_bpm} BPM with the first beat at ${s.first_beat} s. Check it against the audio, then Apply timing.`);});
$('applyTiming').onclick=()=>action(async()=>{const tempo_bpm=Number($('tempoInput').value),first_beat=Number($('firstBeat').value);if(!(tempo_bpm>=20&&tempo_bpm<=300))throw Error('Tempo must be between 20 and 300 BPM.');if($('firstBeat').value===''||!Number.isFinite(first_beat))throw Error('Enter the first beat time in seconds.');await persist();const row=await api(`/api/songs/${current.id}/timing`,jsonOptions('POST',{tempo_bpm,first_beat}));songs=songs.map(s=>s.id===row.id?row:s);await selectSong(row);message(`Lesson re-timed to ${row.summary.bpm} BPM. Notes keep their audio timing; send to Blender again to update the scene.`);});
$('tidyNotes').onclick=()=>action(async()=>{if(!confirm('Tidy notes? Set the correct tempo first. Notes within 45 ms of a 16th move onto it, duplicates are merged, and each note holds until the next one in its voice.'))return;const row=await api(`/api/songs/${current.id}/tidy`,jsonOptions('POST',{}));const t=row.tidy;songs=songs.map(s=>s.id===row.id?row:s);await selectSong(row);message(`Tidied: ${t.snapped} notes snapped (max ${t.max_shift_ms} ms), ${t.not_snapped} left off-grid, ${t.removed} duplicates merged, ${t.lengthened+t.shortened} lengths adjusted. Send to Blender again to update the scene.`);});
$('renderTest').onclick=()=>startRender('test');$('renderFull').onclick=()=>startRender('full');
$('renderCancel').onclick=async()=>{try{renderJob=await api('/api/render/cancel',{method:'POST'});}catch(e){message(e.message,true);}refreshRender();};
$('cancelTabNote').onclick=hideTabEditor;
$('saveTabNote').onclick=()=>action(async()=>{if(!current||!selectedTabNote)throw Error('Select a tab note first.');const string=Number($('editString').value),fret=Number($('editFret').value);if(!Number.isInteger(string)||string<1||string>6)throw Error('String must be 1 to 6.');if(!Number.isInteger(fret)||fret<0||fret>20)throw Error('Fret must be 0 to 20.');const row=await api(`/api/songs/${current.id}/notes`,jsonOptions('PATCH',{note_id:selectedTabNote.id,string,fret}));songs=songs.map(s=>s.id===row.id?row:s);await selectSong(row);message('Tab note updated.');});
$('generateMidi').onclick=()=>action(async()=>{if(!current)throw Error('Create a song first.');if(!current.wav_name)throw Error('Import WAV or MP3 audio first.');message('Generating MIDI from the audio locally…');const row=await api(`/api/songs/${current.id}/generate-midi`,{method:'POST'});songs=songs.map(s=>s.id===row.id?row:s);await selectSong(row);const c=row.cleanup,t=row.timing;message(`MIDI generated: ${c.kept} notes kept (${c.overtones_removed+c.echoes_removed} false notes removed, ${c.rejoined} ringing notes rejoined, ${c.recovered+(t?.restored||0)} missed repeats restored).`+(t?` Tempo ${t.tempo_bpm} BPM${t.tempo_changes?` with ${t.tempo_changes} tempo change${t.tempo_changes>1?'s':''}`:''}, ${t.snapped} notes snapped to ${t.grid==='1/2'?'8ths':'16ths'}.`:' Set the tempo manually.'));});
for(const kind of ['midi','json','wav']){const suffix=kind==='json'?'Json':kind==='wav'?'Wav':'Midi';$('open'+suffix).onclick=()=>{if(current?.[`${kind}_name`])window.open(assetUrl(kind),'_blank');};$('download'+suffix).onclick=()=>downloadAsset(kind);}
for(const kind of ['midi','json','wav']){const suffix=kind==='json'?'Json':kind==='wav'?'Wav':'Midi';$('choose'+suffix).onclick=()=>$(kind+'File').click();$(kind+'File').onchange=()=>action(async()=>{const file=$(kind+'File').files[0];if(!file)return;if(!current)throw Error('Create a song first.');const replacedWav=kind==='wav'&&!!current.wav_name;const form=new FormData();form.append('file',file);const row=await api(`/api/songs/${current.id}/assets/${kind}`,{method:'POST',body:form});songs=songs.map(s=>s.id===row.id?row:s);await selectSong(row);const converted=kind==='wav'&&/\.mp3$/i.test(file.name)?' (MP3 converted to WAV)':'';message(kind==='midi'?'MIDI analyzed and lesson JSON created.':replacedWav?`Audio replaced${converted}. Previous MIDI and lesson JSON were cleared; generate MIDI again for this audio.`:kind==='wav'?`Audio imported${converted}.`:`${kind.toUpperCase()} imported and validated.`);$(kind+'File').value='';});}
$('search').oninput=library;$('newSong').onclick=()=>{$('newDialog').showModal();$('newName').value='';$('newName').focus();};$('closeDialog').onclick=$('cancelDialog').onclick=()=>$('newDialog').close();
$('newForm').onsubmit=e=>{e.preventDefault();action(async()=>{const row=await api('/api/songs',jsonOptions('POST',{name:$('newName').value.trim()}));songs.unshift(row);$('newDialog').close();await selectSong(row);});};
new ResizeObserver(draw).observe($('tablature'));
(async()=>{try{songs=await api('/api/songs');if(songs.length)await selectSong(songs[0]);else fields();await refreshConnection();await refreshRender();}catch(e){message(e.message,true);}icons();})();
setInterval(()=>{if(!busy&&!document.hidden)refreshConnection();},12000);
document.addEventListener('visibilitychange',()=>{if(!busy&&!document.hidden)refreshConnection();});
