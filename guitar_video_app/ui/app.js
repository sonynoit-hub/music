const $ = id => document.getElementById(id);
let songs = [], current = null, blender = {ok:false}, busy = false, lesson = null, peaks = [], cursor = 0, loadToken = 0, tabHits = [], selectedTabNote = null, lastTransfer = null, renderJob = {status:'idle'}, renderTimer = null;
let tabGeom = null, drag = null, noteHistory = {undo:[], redo:[]};
let cameraInfo = null, barPick = null, barDrag = false;
const CHANGE_COLORS = {added:'#1f8a4c',fingering:'#2f67c9',moved:'#c07a12'};
const barsText = places => places.map(p=>p.bars[0]===p.bars[1]?`bar ${p.bars[0]}`:`bars ${p.bars[0]}–${p.bars[1]}`).join(', ');
const audio = $('audio');
const HAND_COLORS = {right:'#d9701a',left:'#2f6fd6'};
const isPiano = () => current?.instrument==='piano';
const onStage = () => ['visual','plumes'].includes(current?.piano_look);
const partName = () => isPiano()?'piano':'guitar';
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
function setBusy(value){busy=value;document.querySelectorAll('button').forEach(b=>b.disabled=value);$('handPosition').disabled=value||!current?.json_name;$('instrument').disabled=value||!current;if(!value){$('planHands').disabled=!current?.json_name;$('send').disabled=!current?.json_name||!current?.wav_name||!blender.ok;$('saveBlend').disabled=!blender.ok;$('previousPage').disabled=!lesson;$('nextPage').disabled=!lesson;$('generateMidi').disabled=$('chooseTab').disabled=$('playPause').disabled=!current?.wav_name;$('suggestTiming').disabled=$('applyTiming').disabled=$('tidyNotes').disabled=!current?.json_name;document.querySelectorAll('[data-style],[data-look],[data-colors]').forEach(b=>b.disabled=!current);$('undoReview').disabled=!current?.can_undo_review;$('undoEdit').disabled=!lesson||!noteHistory.undo.length;$('redoEdit').disabled=!lesson||!noteHistory.redo.length;syncAssetButtons();renderUI();}}
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
 const s=current?.summary;$('name').value=current?.name||'';$('name').disabled=!current;document.title=current?`${current.name} · Music Video Studio`:'Music Video Studio';$('offset').value=current?.offset||0;$('tempoInput').value=current?.summary?.bpm??'';$('firstBeat').value=current?.json_name&&s?firstBeatTime(s,current.offset||0):'';$('revision').textContent=current?`Revision ${current.revision}`:'No song selected';
 $('videoTitle').value=current?(current.title??current.name):'';$('videoSubtitle').value=current?.subtitle||'';$('videoTitle').disabled=$('videoSubtitle').disabled=!current;document.querySelectorAll('[data-style]').forEach(b=>{b.setAttribute('aria-pressed',String(b.dataset.style===(current?.guitar_style||'natural')));b.disabled=busy||!current;});document.querySelectorAll('[data-look]').forEach(b=>{b.setAttribute('aria-pressed',String(b.dataset.look===(current?.piano_look||'lesson')));b.disabled=busy||!current;});document.querySelectorAll('[data-colors]').forEach(b=>{b.setAttribute('aria-pressed',String(b.dataset.colors===(current?.piano_colors||'blue')));b.disabled=busy||!current;});
 $('midiName').textContent=current?.json_name?'Written from the lesson':current?.midi_name||'No file selected';$('jsonName').textContent=current?.json_name||'No file selected';$('wavName').textContent=current?.wav_name||'No file selected';for(const id of ['midiName','jsonName','wavName'])$(id).title=$(id).textContent;
 const fit=s?.source_format==='tab'?s.tab_fit:null,review=s?.tab_review;$('tabName').textContent=review?`${review.tab} · reviewed the lesson · found at ${barsText(review.places)}`:fit?`${current.json_name} · ${fit.matched} of ${fit.notes} notes heard`+(fit.adapted?` · ${fit.adapted.moved} moved, ${fit.adapted.added} added, ${fit.adapted.removed} removed to match the audio`:''):'No tab imported · a tab file is fitted to the audio, or reviews the current lesson';$('tabName').title=$('tabName').textContent;$('handPosition').value=current?.hand_position??'';
 $('reviewBar').hidden=!review;if(review){$('reviewSummary').textContent=`${review.tab} found at ${barsText(review.places)}; other bars keep their notes, fingered ${review.position?`around fret ${review.position}`:'at low frets'} like the tab.`+(review.transpose?` The audio sounds ${Math.abs(review.transpose)} semitone${Math.abs(review.transpose)>1?'s':''} ${review.transpose>0?'higher':'lower'} than the tab.`:'');for(const kind of ['added','fingering','moved','removed'])$('review'+kind[0].toUpperCase()+kind.slice(1)).textContent=review[kind];$('undoReview').disabled=busy||!current.can_undo_review;}
 const piano=isPiano();$('instrument').value=current?.instrument||'guitar';$('instrument').disabled=busy||!current;$('handPositionField').hidden=$('tabAsset').hidden=$('guitarStyle').hidden=piano;$('handsField').hidden=$('pianoLook').hidden=!piano;$('noteColors').hidden=!(piano&&onStage());document.querySelector('.video-title').hidden=piano&&onStage();$('undoEdit').hidden=$('redoEdit').hidden=piano;$('tablature').classList.toggle('piano',piano);
 $('handsInfo').textContent=s?.piano?`${s.piano.right} right · ${s.piano.left} left`+(s.piano.hands_from==='midi_tracks'?' · from MIDI tracks':''):'left and right';
 $('tabLabel').innerHTML=piano?'Piano · <b class="hand-right">right hand</b> · <b class="hand-left">left hand</b> <em class="tab-hint">· click a note to switch hands</em>':'Guitar · Standard tuning <em class="tab-hint">· drag a note to move it · double-click to add one</em>';
 $('notes').textContent=s?.notes??'—';$('tempo').textContent=s?`${s.bpm} BPM`+(s.tempo_changes?` + ${s.tempo_changes} change${s.tempo_changes>1?'s':''}`:''):'—';$('measures').textContent=s?.measures??'—';$('duration').textContent=s?clock(s.duration):'—';$('fps').textContent=s?`${s.fps} fps`:'—';$('signature').textContent=s?s.signature.join(' / '):'—';
 const mismatch=s&&current.audio_duration!=null&&Math.abs(current.audio_duration+current.offset-s.duration)>.1;
 $('durationWarning').hidden=!mismatch;$('durationWarning').textContent=mismatch?`Lesson ${s.duration.toFixed(2)} s · audio ends at ${(current.audio_duration+current.offset).toFixed(2)} s with offset.`:'';
 syncAssetButtons();library();connectionUI();
}
function updateSong(row){current=row;songs=songs.map(s=>s.id===row.id?row:s);fields();}
function assetUrl(kind,download=false){const path=kind==='json'?'lesson':kind==='wav'?'audio':'midi';return current?`/api/songs/${current.id}/${path}?r=${current.revision}${download?'&download=true':''}`:'#';}
function syncAssetButtons(){const available={Midi:!!(current?.midi_name||current?.json_name),Json:!!current?.json_name,Wav:!!current?.wav_name};for(const [suffix,enabled] of Object.entries(available)){const open=$('open'+suffix),download=$('download'+suffix);if(open)open.disabled=busy||!enabled;if(download)download.disabled=busy||!enabled;}}
function downloadAsset(kind){if(!current)return;const suffix=kind==='json'?'Json':kind==='wav'?'Wav':'Midi';let name=current?.[`${kind}_name`]||`lesson.${kind==='midi'?'mid':kind}`;if(kind==='wav')name=name.replace(/\.[^.]*$/,'')+'.wav';if(kind==='midi')name='';const link=document.createElement('a');link.href=assetUrl(kind,true);link.download=name;document.body.append(link);link.click();link.remove();message(`${suffix} download started.`);}
async function selectSong(row){
 const token=++loadToken;audio.pause();current=row;lesson=null;peaks=[];cursor=0;selectedTabNote=null;tabHits=[];drag=null;noteHistory={undo:[],redo:[]};cameraInfo=null;barPick=null;barDrag=false;hideTabEditor();fields();$('message').hidden=true;draw();
 if(row.wav_name){audio.src=`/api/songs/${row.id}/audio?r=${row.revision}`;audio.load();}else{audio.removeAttribute('src');audio.load();}
 if(row.json_name){try{const data=await api(`/api/songs/${row.id}/lesson?part=${partName()}&r=${row.revision}`);if(token!==loadToken)return;useLesson(data);draw();setBusy(busy);}catch(e){message(e.message,true);}}
 if(row.json_name&&isPiano()){try{const info=await api(`/api/songs/${row.id}/camera`);if(token!==loadToken)return;cameraInfo=info;draw();setBusy(busy);}catch(e){if(token===loadToken)message(e.message,true);}}
 if(row.wav_name){try{const bytes=await (await fetch(`/api/songs/${row.id}/audio?r=${row.revision}`)).arrayBuffer();const ctx=new AudioContext();const buffer=await ctx.decodeAudioData(bytes);await ctx.close();if(token!==loadToken)return;const samples=buffer.getChannelData(0);peaks=Array.from({length:500},(_,i)=>{let max=0;for(let j=Math.floor(i*samples.length/500);j<Math.floor((i+1)*samples.length/500);j+=8)max=Math.max(max,Math.abs(samples[j]));return max;});draw();}catch(e){if(token===loadToken)message('The browser could not decode the audio preview. '+e.message,true);}}
}
function useLesson(data){lesson=data;lesson.tempoMap=tempoMap(lesson);lesson.notes=lesson.notes.map(n=>({...n,start:beat(n.start_beat),end:beat(n.start_beat)+beat(n.duration_beats)})).sort((a,b)=>a.start-b.start);const slot=data.instrument==='piano'?'pitch':'string',last={};for(const n of lesson.notes){if(last[n[slot]])last[n[slot]].end=Math.min(last[n[slot]].end,n.start);last[n[slot]]=n;}if(data.instrument!=='piano')prepareNotation(lesson);}
async function persist(){if(!current)return;const name=$('name').value.trim();const offset=Number($('offset').value);if(!name)throw Error('Enter a song name.');if(!Number.isFinite(offset)||Math.abs(offset)>60)throw Error('Audio offset must be between -60 and 60 seconds.');const typed=$('videoTitle').value.trim(),title=current.title==null&&typed===current.name?null:typed,subtitle=$('videoSubtitle').value.trim();const row=await api(`/api/songs/${current.id}`,jsonOptions('PATCH',{name,offset,title,subtitle}));updateSong(row);draw();}
function canvas(id){const c=$(id),rect=c.getBoundingClientRect(),dpr=devicePixelRatio||1;c.width=Math.round(rect.width*dpr);c.height=Math.round(rect.height*dpr);const ctx=c.getContext('2d');ctx.scale(dpr,dpr);return {c,ctx,w:rect.width,h:rect.height};}
const OPEN_MIDI={1:64,2:59,3:55,4:50,5:45,6:40},PITCHES=['c','c#','d','d#','e','f','f#','g','g#','a','a#','b'];
const NOTE_VALUES=[[16,'w',0],[12,'h',1],[8,'h',0],[6,'q',1],[4,'q',0],[3,'8',1],[2,'8',0],[1,'16',0]];
let notationKey=null,notationNotes=[],notationCursorTop=0;
// Guitar notation is written an octave above sounding pitch; lesson timing is snapped to 8ths or 16ths for display only.
function writtenPitch(note){return OPEN_MIDI[note.string]+note.fret+12;}
// Same bass rule as is_bass in instruments/guitar/rules.py; grid is in 16ths: 2 unless over a tenth of notes sit on in-between 16ths.
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
 if(!lesson){tabGeom=null;$('pageLabel').textContent='Measures —';drawNotation();$('scoreCursor').hidden=true;return;}
 const measure=lesson.time_signature[0]*4/lesson.time_signature[1],pageBeats=measure*2;const beatNow=beatAt(lesson.tempoMap,cursor);
 const page=Math.min(Math.max(0,Math.ceil(beat(lesson.end_beat)/pageBeats)-1),Math.max(0,Math.floor((beatNow+1e-6)/pageBeats)));$('pageLabel').textContent=`Measures ${page*2+1}–${Math.min(page*2+2,current.summary.measures)}`;
 function xAt(b){const local=Math.max(0,Math.min(2,(b-page*pageBeats)/measure)),m=Math.min(1,Math.floor(local));return left+(right-left)*(m*.5+.012+.476*(local-m));}
 if(lesson.instrument==='piano'){tabGeom=null;drawPianoRoll(ctx,w,h,page,pageBeats,measure,xAt,beatNow);markPlayheadBar(Math.floor(beatNow/measure+1e-6)+1);return;}
 ctx.fillStyle='#343e38';ctx.font='bold 14px Georgia, serif';ctx.textAlign='center';ctx.textBaseline='middle';['T','A','B'].forEach((letter,i)=>ctx.fillText(letter,34,top+gap*(1+i*1.5)));
 tabGeom={page,pageBeats,measure,left,right,top,gap};
 const visible=lesson.notes.filter(n=>n.start>=page*pageBeats&&n.start<(page+1)*pageBeats).sort((a,b)=>a.start-b.start||a.string-b.string);
 ctx.font='15px Arial';ctx.textAlign='center';ctx.textBaseline='middle';let labels=visible.map(n=>{const text=String(n.fret),x=Math.max(left+(right-left)*.012,Math.min(right-(right-left)*.012,xAt(n.start))),y=top+(n.string-1)*gap,width=ctx.measureText(text).width+10;return {...n,text,x,rawX:x,y,width};});
 const denseGroups=[],edge=left+(right-left)*.012,rightEdge=right-(right-left)*.012,pad=8;for(let string=1;string<=6;string++){const row=labels.filter(n=>n.string===string).sort((a,b)=>a.rawX-b.rawX);for(let i=1;i<row.length;i++){const need=(row[i-1].width+row[i].width)/2+pad;if(row[i].x-row[i-1].x<need)row[i].x=row[i-1].x+need;}let overflow=row.length?row[row.length-1].x-rightEdge:0;if(overflow>0){for(const n of row)n.x-=overflow;for(let i=row.length-2;i>=0;i--){const need=(row[i].width+row[i+1].width)/2+pad;if(row[i+1].x-row[i].x<need)row[i].x=row[i+1].x-need;}}if(row.length&&row[0].x<edge){const shift=edge-row[0].x;for(const n of row)n.x+=shift;}let group=[];for(const n of row){const moved=Math.abs(n.x-n.rawX)>1;if(!group.length){group=moved?[n]:[];continue;}const prev=group[group.length-1],close=n.x-prev.x<(prev.width+n.width)/2+pad*2;if(moved&&close){group.push(n);}else{if(group.length>1)denseGroups.push(group);group=moved?[n]:[];}}if(group.length>1)denseGroups.push(group);}
 for(let i=0;i<6;i++){const y=top+i*gap;const gaps=labels.filter(n=>n.string===i+1).map(n=>[n.x-n.width/2,n.x+n.width/2]).sort((a,b)=>a[0]-b[0]);let start=left;ctx.strokeStyle='#b6bcb8';ctx.lineWidth=.6;for(const [a,b] of gaps){if(a>start){ctx.beginPath();ctx.moveTo(start,y);ctx.lineTo(Math.max(start,a),y);ctx.stroke();}start=Math.max(start,b);}if(start<right){ctx.beginPath();ctx.moveTo(start,y);ctx.lineTo(right,y);ctx.stroke();}}
 for(const x of [left,(left+right)/2,right]){ctx.strokeStyle='#8f9993';ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,top+5*gap);ctx.stroke();}
 for(const group of denseGroups){if(group.every(n=>Math.abs(n.x-n.rawX)<1))continue;const first=group[0],last=group[group.length-1],arcTop=Math.max(8,first.y-13),arcLift=Math.min(12,(last.x-first.x)/5+5);ctx.strokeStyle='#5c6862';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(first.x,arcTop);ctx.quadraticCurveTo((first.x+last.x)/2,arcTop-arcLift,last.x,arcTop);ctx.stroke();}
 tabHits=labels.map(n=>({id:n.id,x:n.x,y:n.y,w:Math.max(n.width,22),h:22}));
 const review=$('showChanges').checked&&current.summary?.tab_review,kinds=review?.changes||{};
 if(review)for(const g of review.removed_notes){const b=beat(g.start_beat);if(b<page*pageBeats||b>=(page+1)*pageBeats)continue;const x=xAt(b),y=top+(g.string-1)*gap,text=String(g.fret),width=ctx.measureText(text).width+6;if(labels.some(n=>n.string===g.string&&Math.abs(n.x-x)<(n.width+width)/2))continue;ctx.fillStyle='white';ctx.fillRect(x-width/2,y-8,width,16);ctx.globalAlpha=.6;ctx.fillStyle=ctx.strokeStyle='#c8453a';ctx.lineWidth=1.2;ctx.fillText(text,x,y);ctx.beginPath();ctx.moveTo(x-width/2,y);ctx.lineTo(x+width/2,y);ctx.stroke();ctx.globalAlpha=1;}
 for(const n of labels){const selected=selectedTabNote&&selectedTabNote.id===n.id,kind=kinds[n.id];ctx.globalAlpha=drag?.moved&&drag.note.id===n.id?.3:1;if(selected){ctx.fillStyle='#e6f3ef';ctx.fillRect(n.x-n.width/2,n.y-11,n.width,22);ctx.strokeStyle='#087c70';ctx.strokeRect(n.x-n.width/2,n.y-11,n.width,22);}else if(kind){ctx.fillStyle=CHANGE_COLORS[kind]+'1f';ctx.fillRect(n.x-n.width/2,n.y-10,n.width,20);}ctx.fillStyle=selected?'#075f55':n.start<=beatNow&&beatNow<n.end?'#087c70':CHANGE_COLORS[kind]||'#343e38';ctx.fillText(n.text,n.x,n.y);}
 ctx.globalAlpha=1;
 const ghost=drag?.moved&&drag.target?{...drag.target,text:String(drag.target.fret)}:selectedTabNote?.isNew?{string:selectedTabNote.string,start:selectedTabNote.start,text:$('editFret').value||'?',ok:true}:null;
 if(ghost&&ghost.start>=page*pageBeats&&ghost.start<(page+1)*pageBeats){const x=xAt(ghost.start),y=top+(ghost.string-1)*gap,width=Math.max(22,ctx.measureText(ghost.text).width+10),color=ghost.ok?'#087c70':'#c8453a';ctx.fillStyle=ghost.ok?'#e6f3ef':'#fbeceb';ctx.fillRect(x-width/2,y-11,width,22);ctx.setLineDash([3,2]);ctx.strokeStyle=color;ctx.lineWidth=1;ctx.strokeRect(x-width/2,y-11,width,22);ctx.setLineDash([]);ctx.fillStyle=color;ctx.fillText(ghost.text,x,y);}
 drawNotation(page,left,right,w,xAt);
 for(const p of notationNotes)p.el?.classList.toggle('playing',!p.rest&&p.beat<=beatNow&&beatNow<p.end);
 const notationHeight=$('notation').offsetHeight,cursorLine=$('scoreCursor');cursorLine.hidden=false;cursorLine.style.left=`${xAt(beatNow)-.75}px`;const cursorTop=notationHeight?notationCursorTop:notationHeight+top-6;cursorLine.style.top=`${cursorTop}px`;cursorLine.style.height=`${notationHeight+top+5*gap+6-cursorTop}px`;
}
// Rows are semitones over the song's range (at least two octaves); columns share the tab's time axis.
function drawPianoRoll(ctx,w,h,page,pageBeats,measure,xAt,beatNow){
 const box=$('notation');box.innerHTML='';box.style.height='0px';notationKey=null;notationNotes=[];
 const left=78,right=w-20,top=10,bottom=h-10,first=page*pageBeats,last=first+pageBeats,black=p=>[1,3,6,8,10].includes(p%12);
 const pitches=lesson.notes.map(n=>n.pitch);let low=Math.min(...pitches)-2,high=Math.max(...pitches)+2;
 if(high-low<24){low=Math.round((low+high)/2-12);high=low+24;}
 const row=(bottom-top)/(high-low+1),y=p=>top+(high-p)*row;
 ctx.textAlign='right';ctx.textBaseline='middle';ctx.font='10px Arial';
 for(let p=low;p<=high;p++){ctx.fillStyle=black(p)?'#f0f3f2':'#ffffff';ctx.fillRect(left,y(p),right-left,row);ctx.fillStyle=black(p)?'#343e38':'#ffffff';ctx.fillRect(left-30,y(p),black(p)?18:30,row);
  if(p%12===0){ctx.strokeStyle='#d5dbd8';ctx.lineWidth=.6;ctx.beginPath();ctx.moveTo(left-30,y(p)+row);ctx.lineTo(right,y(p)+row);ctx.stroke();ctx.fillStyle='#78877d';ctx.fillText(`C${p/12-1}`,left-34,y(p)+row/2);}}
 ctx.strokeStyle='#c9d0cc';ctx.lineWidth=1;ctx.strokeRect(left-30,top,30,bottom-top);
 for(let m=0;m<2;m++)for(let b=1;b<measure;b++){const x=xAt(first+m*measure+b);ctx.strokeStyle='#e3e8e6';ctx.lineWidth=.6;ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,bottom);ctx.stroke();}
 for(const x of [left,(left+right)/2,right]){ctx.strokeStyle='#8f9993';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,bottom);ctx.stroke();}
 tabHits=[];
 for(const n of lesson.notes){if(n.end<=first||n.start>=last)continue;
  const x0=xAt(Math.max(n.start,first)),x1=Math.max(x0+4,xAt(Math.min(n.end,last)-1e-6)-1),top0=y(n.pitch)+1,height=Math.max(3,row-2),playing=n.start<=beatNow&&beatNow<n.end;
  ctx.globalAlpha=playing?1:.8;ctx.fillStyle=HAND_COLORS[n.hand];ctx.beginPath();if(ctx.roundRect)ctx.roundRect(x0,top0,x1-x0,height,2);else ctx.rect(x0,top0,x1-x0,height);ctx.fill();
  if(playing){ctx.strokeStyle='#1d2622';ctx.lineWidth=1.2;ctx.stroke();}
  tabHits.push({id:n.id,x:(x0+x1)/2,y:top0+height/2,w:Math.max(x1-x0,8),h:Math.max(height,8)});}
 ctx.globalAlpha=1;
 const cursorLine=$('scoreCursor');cursorLine.hidden=false;cursorLine.style.left=`${xAt(beatNow)-.75}px`;cursorLine.style.top=`${top}px`;cursorLine.style.height=`${bottom-top}px`;
}
// Camera shots (PIANO_VISUAL stage): stored as shots starting on bars, edited one bar at a time; neighbouring bars with the same camera and move are one shot.
const SHOT_COLORS={wide:'#6b7a8f',hero:'#168676',along:'#7a5bd1',high:'#c07a12',close:'#c8453a',side:'#2f67c9'};
const MOVE_MARK={static:'',push:'⇢',drift:'∿',arc:'⌒'};
const shotList=()=>cameraInfo?.camera_shots?.shots||null;
const showShots=()=>isPiano()&&onStage()&&!!shotList()&&!!lesson;
const shotEnd=(shots,i)=>i+1<shots.length?shots[i+1].start_bar:cameraInfo.bars+1;
const shotAtBar=(shots,bar)=>shots.reduce((found,s,i)=>s.start_bar<=bar?i:found,0);
const pickedBars=()=>barPick?[Math.min(barPick.anchor,barPick.end),Math.max(barPick.anchor,barPick.end)]:null;
function barPlan(shots){const bars=[];shots.forEach((s,i)=>{for(let b=s.start_bar;b<shotEnd(shots,i);b++)bars.push({camera:s.camera,move:s.move,transition:s.transition});});return bars;}
function joinBars(bars){const shots=[];bars.forEach((b,k)=>{const last=shots[shots.length-1];if(last&&last.camera===b.camera&&last.move===b.move)return;shots.push({start_bar:k+1,camera:b.camera,move:b.move,transition:k?b.transition:'cut'});});return shots;}
const barRange=(a,b)=>a===b?`Bar ${a}`:`Bars ${a}–${b}`;
function renderStrip(shots,bars){
 const [a,b]=pickedBars(),strip=$('barStrip'),now=Number(strip.dataset.now)||0;
 strip.innerHTML=bars.map((x,k)=>{const bar=k+1,i=shotAtBar(shots,bar),head=shots[i].start_bar===bar,blend=head&&i>0&&x.transition==='blend',picked=bar>=a&&bar<=b;
  const cls=['bar-cell',head?'head':'',head&&i>0?'start':'',blend?'blend':'',picked?'picked':'',bar===now?'now':''].filter(Boolean).join(' ');
  const title=`Bar ${bar} · ${x.camera} · ${x.move}${head&&i>0?` · ${x.transition==='blend'?'blends':'cuts'} in`:''}`;
  return `<button type="button" class="${cls}" data-bar="${bar}" role="option" aria-selected="${picked}" title="${title}" style="--c:${SHOT_COLORS[x.camera]};--p:${blend?SHOT_COLORS[shots[i-1].camera]:SHOT_COLORS[x.camera]}"><b>${bar}</b><span>${x.camera}</span><i>${MOVE_MARK[x.move]}</i></button>`;}).join('');
}
function markPlayheadBar(bar){const strip=$('barStrip');if($('shotLaneBox').hidden||strip.dataset.now===String(bar))return;strip.dataset.now=bar;strip.querySelectorAll('.now').forEach(c=>c.classList.remove('now'));strip.querySelector(`[data-bar="${bar}"]`)?.classList.add('now');}
function cameraUI(){
 const stage=isPiano()&&onStage()&&!!current?.json_name,shots=shotList(),box=$('shotLaneBox');$('cameraBox').hidden=!stage;
 document.querySelectorAll('[data-camera-mode]').forEach(b=>{b.setAttribute('aria-pressed',String(b.dataset.cameraMode===(shots?'shots':'wide')));b.disabled=busy||!cameraInfo;});
 $('cameraNote').textContent=shots?`${shots.length} shot${shots.length>1?'s':''}, cut on bar lines; pick cameras under the piano roll.`:'One fixed view of the whole stage. Shots switch angles on bar lines.';
 box.hidden=!showShots();$('autoShots').disabled=busy||!cameraInfo;
 if(box.hidden)return;
 const bars=barPlan(shots),count=bars.length;
 if(barPick){barPick.anchor=Math.min(barPick.anchor,count);barPick.end=Math.min(barPick.end,count);}else barPick={anchor:1,end:shotEnd(shots,0)-1};
 renderStrip(shots,bars);
 const [a,b]=pickedBars(),picked=bars.slice(a-1,b),same=k=>picked.every(x=>x[k]===picked[0][k])?picked[0][k]:'';
 const first=shotAtBar(shots,a),last=shotAtBar(shots,b),starts=shots.filter(s=>s.start_bar>1&&s.start_bar>=a&&s.start_bar<=b);
 $('shotTitle').textContent=barRange(a,b);
 $('shotSub').textContent=first===last?`· shot ${first+1} of ${shots.length} (${barRange(shots[first].start_bar,shotEnd(shots,first)-1).toLowerCase()})`:`· shots ${first+1}–${last+1} of ${shots.length}`;
 document.querySelectorAll('[data-shot-camera]').forEach(btn=>{btn.setAttribute('aria-pressed',String(btn.dataset.shotCamera===same('camera')));btn.disabled=busy;});
 $('shotMove').value=same('move');$('shotMove').disabled=busy;
 $('shotTransition').value=starts[0]?.transition||'cut';$('shotTransition').disabled=busy||!starts.length;
 $('shotTransition').title=starts.length?`How the shot${starts.length>1?'s':''} starting in ${barRange(a,b).toLowerCase()} begin${starts.length>1?'':'s'}`:a===1?'The song always opens with a cut.':`${barRange(a,b)} continue${a===b?'s':''} the shot from bar ${shots[first].start_bar}. Pick another camera or move to start a new shot here.`;
 $('selectShot').disabled=busy;$('testShot').disabled=busy||renderJob.status==='running'||!current?.wav_name;
}
function useCamera(reply){cameraInfo=reply;updateSong(reply.song);draw();}
function saveShots(shots,done){action(async()=>{const reply=await api(`/api/songs/${current.id}/camera`,jsonOptions('PUT',{version:1,shots}));useCamera(reply);message(`${done} Send to Blender or render to see it.`);});}
function editBars(change,done){const shots=shotList(),range=pickedBars();if(!shots||!range)return;const [a,b]=range,fresh=shots.some(s=>s.start_bar===a)?{}:{transition:'cut'},next=joinBars(barPlan(shots).map((x,k)=>k+1>=a&&k+1<=b?{...x,...change,...fresh}:x));if(JSON.stringify(next)===JSON.stringify(shots))return;saveShots(next,done);}
function autoShots(){action(async()=>{if(!current)return;if(shotList()&&!confirm('Replace your shots with Auto suggestions from the music?'))return;const reply=await api(`/api/songs/${current.id}/camera/auto`,{method:'POST'});barPick=null;useCamera(reply);message(`Auto suggested ${reply.camera_shots.shots.length} shots from the music: cuts on bar lines, following the playing hands. Click bars under the piano roll to change them.`);});}
function selectWholeShot(bar){const shots=shotList();if(!shots)return;const i=shotAtBar(shots,bar);barPick={anchor:shots[i].start_bar,end:shotEnd(shots,i)-1};cameraUI();}
const barUnder=e=>{const cell=document.elementFromPoint(e.clientX,e.clientY)?.closest?.('[data-bar]');return cell&&$('barStrip').contains(cell)?Number(cell.dataset.bar):null;};
$('barStrip').onpointerdown=e=>{const bar=barUnder(e);if(!bar||busy||e.button!==0||!shotList())return;e.preventDefault();barPick=e.shiftKey&&barPick?{anchor:barPick.anchor,end:bar}:{anchor:bar,end:bar};barDrag=true;try{e.currentTarget.setPointerCapture(e.pointerId);}catch{}cameraUI();};
$('barStrip').onpointermove=e=>{if(!barDrag||!barPick)return;const bar=barUnder(e);if(bar&&bar!==barPick.end){barPick.end=bar;cameraUI();}};
$('barStrip').onpointerup=$('barStrip').onpointercancel=()=>{barDrag=false;};
$('barStrip').ondblclick=e=>{const bar=barUnder(e);if(bar)selectWholeShot(bar);};
$('barStrip').onkeydown=e=>{if(!barPick||!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();const end=Math.max(1,Math.min(cameraInfo.bars,barPick.end+(e.key==='ArrowRight'?1:-1)));barPick={anchor:e.shiftKey?barPick.anchor:end,end};cameraUI();$('barStrip').querySelector(`[data-bar="${end}"]`)?.focus();};
$('selectShot').onclick=()=>{const range=pickedBars();if(range)selectWholeShot(range[0]);};
$('autoShots').onclick=autoShots;
document.querySelectorAll('[data-camera-mode]').forEach(b=>b.onclick=()=>{if(!current||b.getAttribute('aria-pressed')==='true')return;if(b.dataset.cameraMode==='shots')return autoShots();
 action(async()=>{if(!confirm('Go back to the single wide view? Your shots are deleted.'))return;const reply=await api(`/api/songs/${current.id}/camera`,{method:'DELETE'});barPick=null;useCamera(reply);message('Camera set to the single wide view. Send to Blender or render to see it.');});});
document.querySelectorAll('[data-shot-camera]').forEach(b=>{b.style.setProperty('--c',SHOT_COLORS[b.dataset.shotCamera]);b.onclick=()=>{const range=pickedBars();if(range)editBars({camera:b.dataset.shotCamera},`${barRange(...range)} use${range[0]===range[1]?'s':''} the ${b.querySelector('strong').textContent} camera.`);};});
$('shotMove').onchange=()=>{const range=pickedBars();if(range&&$('shotMove').value)editBars({move:$('shotMove').value},`${barRange(...range)} move: ${$('shotMove').selectedOptions[0].text.toLowerCase()}.`);};
$('shotTransition').onchange=()=>{const shots=shotList(),range=pickedBars();if(!shots||!range)return;const [a,b]=range,value=$('shotTransition').value,next=shots.map(s=>s.start_bar>1&&s.start_bar>=a&&s.start_bar<=b?{...s,transition:value}:s);saveShots(next,`Shots starting in ${barRange(a,b).toLowerCase()}: ${$('shotTransition').selectedOptions[0].text.toLowerCase()}.`);};
$('testShot').onclick=()=>{const range=pickedBars();if(range)startRender('test',range[0]);};
$('playPause').onclick=()=>{if(!audio.src)return;if(audio.paused)audio.play();else audio.pause();};
function playIcon(){$('playPause').innerHTML=`<i data-lucide="${audio.paused?'play':'pause'}"></i>`;$('playPause').setAttribute('aria-label',audio.paused?'Play':'Pause');icons();}
for(const kind of ['play','pause','ended','emptied'])audio.addEventListener(kind,playIcon);
document.addEventListener('keydown',e=>{if(e.key!==' '||e.metaKey||e.ctrlKey||e.altKey||e.target.closest?.('input,select,textarea,button,dialog,[role=listbox]'))return;e.preventDefault();$('playPause').click();});
audio.addEventListener('timeupdate',()=>{cursor=Math.max(0,audio.currentTime+(current?.offset||0));draw();});audio.addEventListener('loadedmetadata',draw);
$('waveform').onclick=e=>{if(Number.isFinite(audio.duration)){const r=e.currentTarget.getBoundingClientRect();audio.currentTime=Math.max(0,Math.min(audio.duration,(e.clientX-r.left)/r.width*audio.duration));}};
const LENGTHS=[['1/4','16th'],['1/2','8th'],['3/4','dotted 8th'],['1','quarter'],['3/2','dotted quarter'],['2','half'],['3','dotted half'],['4','whole']];
const gcd=(a,b)=>b?gcd(b,a%b):a;
function fraction(value,denominator=48){const n=Math.round(value*denominator),g=gcd(Math.abs(n),denominator);return denominator/g===1?String(n/g):`${n/g}/${denominator/g}`;}
const snapBeat=(b,free)=>free?Math.round(b*48)/48:Math.round(b*4)/4;
const measureBeats=()=>lesson.time_signature[0]*4/lesson.time_signature[1];
function where(start){const measure=measureBeats(),bar=Math.floor(start/measure+1e-9)+1;return {bar,beat:+(start-(bar-1)*measure+1).toFixed(3)};}
function tabPoint(e){const r=$('tablature').getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top};}
function tabHit(p){return tabHits.find(n=>p.x>=n.x-n.w/2&&p.x<=n.x+n.w/2&&p.y>=n.y-n.h/2&&p.y<=n.y+n.h/2);}
// Inverse of xAt in draw(): the page's two measures each fill .476 of the width after a .012 margin.
function tabTarget(p,free){const g=tabGeom,inner=(p.x-g.left)/(g.right-g.left),m=inner<.5?0:1,local=Math.max(0,Math.min(2-1e-9,m+(inner-m*.5-.012)/.476)),first=g.page*g.pageBeats;const start=Math.max(first,Math.min(first+g.pageBeats-(free?1/48:1/4),snapBeat(first+local*g.measure,free)));return {start,string:Math.max(1,Math.min(6,Math.round((p.y-g.top)/g.gap)+1))};}
// Moving to another string keeps the pitch: the fret follows the string.
function placeNote(note,string,start){const fret=OPEN_MIDI[note.string]+note.fret-OPEN_MIDI[string],clash=lesson.notes.some(n=>n.id!==note.id&&n.string===string&&Math.abs(n.start-start)<1e-6),playable=fret>=0&&fret<=20;return {string,fret,start,ok:playable&&!clash,why:!playable?`That pitch can't be played on string ${string}.`:clash?`String ${string} already has a note there.`:''};}
function snapshot(){return {notes:lesson.notes.map(n=>({id:n.id,string:n.string,fret:n.fret,start_beat:n.start_beat,duration_beats:n.duration_beats})),end_beat:lesson.end_beat};}
function followNote(note){const span=measureBeats()*2,page=Math.floor(note.start/span+1e-9);if(page===Math.floor((beatAt(lesson.tempoMap,cursor)+1e-6)/span))return;cursor=secondsAt(lesson.tempoMap,page*span);if(audio.src)audio.currentTime=Math.max(0,cursor-(current.offset||0));}
async function reloadLesson(row,selectId){updateSong(row);const data=await api(`/api/songs/${row.id}/lesson?part=${partName()}&r=${row.revision}`);useLesson(data);const note=selectId&&lesson.notes.find(n=>n.id===selectId);if(note){followNote(note);showTabEditor(note);}else hideTabEditor();draw();}
function editNotes(url,options,done,selectId){if(busy||!current||!lesson)return;const before=snapshot();action(async()=>{const row=await api(url,options);noteHistory.undo.push(before);noteHistory.redo=[];await reloadLesson(row,selectId??row.note_id);message(done);});}
function moveNote(note,target){const same=Math.abs(target.start-note.start)<1e-6,at=where(target.start);editNotes(`/api/songs/${current.id}/notes`,jsonOptions('PATCH',{note_id:note.id,string:target.string,fret:target.fret,start_beat:same?note.start_beat:fraction(target.start)}),`Note moved to string ${target.string}, fret ${target.fret}, bar ${at.bar} beat ${at.beat}. Undo with ⌘Z.`,note.id);}
function deleteNote(note){editNotes(`/api/songs/${current.id}/notes/${encodeURIComponent(note.id)}`,{method:'DELETE'},'Tab note deleted. Undo with ⌘Z.',null);}
function undoEdit(redo){const from=redo?noteHistory.redo:noteHistory.undo,to=redo?noteHistory.undo:noteHistory.redo;if(busy||!current||!lesson||!from.length)return;const now=snapshot(),keep=selectedTabNote?.isNew?null:selectedTabNote?.id;action(async()=>{const row=await api(`/api/songs/${current.id}/notes`,jsonOptions('PUT',from[from.length-1]));to.push(now);from.pop();await reloadLesson(row,keep);message(redo?'Note edit redone.':'Note edit undone.');});}
function switchHand(note){const hand=note.hand==='right'?'left':'right';action(async()=>{const row=await api(`/api/songs/${current.id}/hands`,jsonOptions('POST',{note_id:note.id,hand}));await reloadLesson(row);message(`Note moved to the ${hand} hand. Plan hands keeps your choice.`);});}
$('tablature').onpointerdown=e=>{if(!lesson||busy||e.button!==0)return;const p=tabPoint(e),hit=tabHit(p),note=hit&&lesson.notes.find(n=>n.id===hit.id);if(!note)return;if(lesson.instrument==='piano'){switchHand(note);return;}showTabEditor(note);drag={note,x:p.x,y:p.y,moved:false,target:null};try{e.currentTarget.setPointerCapture(e.pointerId);}catch{}};
$('tablature').onpointermove=e=>{if(!lesson)return;const p=tabPoint(e);if(!drag){e.currentTarget.classList.toggle('over-note',!!tabHit(p));return;}if(!drag.moved&&Math.hypot(p.x-drag.x,p.y-drag.y)<4)return;drag.moved=true;e.currentTarget.classList.add('dragging');const t=tabTarget(p,e.shiftKey);if(Math.abs(t.start-snapBeat(drag.note.start,e.shiftKey))<1e-9)t.start=drag.note.start;drag.target=placeNote(drag.note,t.string,t.start);draw();};
$('tablature').onpointerup=e=>{if(!drag)return;const {note,moved,target}=drag;drag=null;e.currentTarget.classList.remove('dragging');if(!moved||!target||(target.string===note.string&&Math.abs(target.start-note.start)<1e-6)){draw();return;}if(!target.ok){message(target.why,true);draw();return;}moveNote(note,target);};
$('tablature').onpointercancel=e=>{drag=null;e.currentTarget.classList.remove('dragging');draw();};
$('tablature').ondblclick=e=>{if(!lesson||busy||!tabGeom||lesson.instrument==='piano')return;const p=tabPoint(e);if(tabHit(p))return;const t=tabTarget(p,e.shiftKey);showTabEditor({isNew:true,string:t.string,fret:'',start:t.start,duration_beats:'1'});$('editFret').focus();};
function lengthOptions(value){const v=beat(value),known=LENGTHS.find(([b])=>Math.abs(beat(b)-v)<1e-6);$('editLength').replaceChildren(...[...LENGTHS,...(known?[]:[[String(value),`${+v.toFixed(3)} beats`]])].map(([b,label])=>new Option(label,b)));$('editLength').value=known?known[0]:String(value);}
function showTabEditor(note){selectedTabNote=note;const at=where(note.start);$('editString').value=$('editString').dataset.was=note.string;$('editFret').value=note.fret;$('editBar').value=at.bar;$('editBeat').value=at.beat;$('editBeat').max=measureBeats()+.99;lengthOptions(note.duration_beats);$('deleteTabNote').hidden=!!note.isNew;$('saveTabNote').innerHTML=`<i data-lucide="${note.isNew?'plus':'save'}"></i> ${note.isNew?'Add':'Save'}`;$('tabEditor').hidden=false;draw();icons();}
function hideTabEditor(){selectedTabNote=null;if($('tabEditor'))$('tabEditor').hidden=true;draw();}
$('editString').onchange=()=>{const was=Number($('editString').dataset.was),now=Number($('editString').value);if($('editFret').value!==''&&OPEN_MIDI[was]&&OPEN_MIDI[now]){const fret=OPEN_MIDI[was]+Number($('editFret').value)-OPEN_MIDI[now];if(fret>=0&&fret<=20)$('editFret').value=fret;}$('editString').dataset.was=now;if(selectedTabNote?.isNew){selectedTabNote.string=now;draw();}};
$('editFret').oninput=()=>{if(selectedTabNote?.isNew)draw();};
$('tabEditor').onkeydown=e=>{if(e.key==='Enter'&&e.target.matches('input,select')){e.preventDefault();$('saveTabNote').click();}else if(e.key==='Escape'){e.preventDefault();hideTabEditor();}};
document.addEventListener('keydown',e=>{if(!lesson||busy||e.target.closest?.('input,select,textarea,dialog'))return;const mod=e.metaKey||e.ctrlKey,key=e.key.toLowerCase();
 if(mod&&key==='z'){e.preventDefault();undoEdit(e.shiftKey);return;}if(mod&&key==='y'){e.preventDefault();undoEdit(true);return;}
 const note=selectedTabNote;if(!note||note.isNew||mod)return;
 if(e.key==='Escape'){hideTabEditor();return;}
 if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();deleteNote(note);return;}
 if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();const start=Math.max(0,snapBeat(note.start+(e.shiftKey?1:.25)*(e.key==='ArrowLeft'?-1:1),false));if(Math.abs(start-note.start)<1e-6)return;const target=placeNote(note,note.string,start);if(target.ok)moveNote(note,target);else message(target.why,true);return;}
 if(e.key==='ArrowUp'||e.key==='ArrowDown'){e.preventDefault();const dir=e.key==='ArrowUp'?-1:1;for(let s=note.string+dir;s>=1&&s<=6;s+=dir){const target=placeNote(note,s,note.start);if(target.ok){moveNote(note,target);return;}}message(`No string ${dir<0?'above':'below'} can play this pitch here.`,true);}
});
function pageMove(direction){if(!lesson)return;const span=lesson.time_signature[0]*4/lesson.time_signature[1]*2,page=Math.floor((beatAt(lesson.tempoMap,cursor)+.01)/span)+direction;cursor=Math.max(0,Math.min(current.summary.duration-.001,secondsAt(lesson.tempoMap,page*span)));if(audio.src)audio.currentTime=Math.max(0,cursor-current.offset);draw();}
$('previousPage').onclick=()=>pageMove(-1);$('nextPage').onclick=()=>pageMove(1);
$('connect').onclick=()=>action(async()=>{blender=await api('/api/blender/connect',{method:'POST'});connectionUI();message('Blender connected.');});
$('name').onkeydown=e=>{if(e.key==='Enter')e.target.blur();if(e.key==='Escape'){e.target.value=current?.name||'';e.target.blur();}};
$('name').onchange=()=>{if(!$('name').value.trim()){$('name').value=current?.name||'';return;}action(async()=>{await persist();message('Song name saved.');});};$('offset').onchange=()=>action(persist);
document.querySelectorAll('[data-style]').forEach(b=>b.onclick=()=>action(async()=>{if(!current||b.getAttribute('aria-pressed')==='true')return;const row=await api(`/api/songs/${current.id}/style`,jsonOptions('POST',{style:b.dataset.style}));songs=songs.map(s=>s.id===row.id?row:s);await selectSong(row);message(`Guitar style set to ${b.querySelector('strong').textContent}. Send to Blender or render to see it.`);}));
document.querySelectorAll('[data-look]').forEach(b=>b.onclick=()=>action(async()=>{if(!current||b.getAttribute('aria-pressed')==='true')return;const row=await api(`/api/songs/${current.id}/piano-look`,jsonOptions('POST',{look:b.dataset.look}));songs=songs.map(s=>s.id===row.id?row:s);await selectSong(row);message(`Piano look set to ${b.querySelector('strong').textContent}. For Send to Blender, open outputs/${b.dataset.look==='lesson'?'piano-vertical':'piano-visual'}.blend in Blender; renders use it automatically.`);}));
document.querySelectorAll('[data-colors]').forEach(b=>b.onclick=()=>action(async()=>{if(!current||b.getAttribute('aria-pressed')==='true')return;const row=await api(`/api/songs/${current.id}/piano-colors`,jsonOptions('POST',{colors:b.dataset.colors}));songs=songs.map(s=>s.id===row.id?row:s);await selectSong(row);message(`Note colour set to ${b.querySelector('strong').textContent}. Send to Blender or render to see it.`);}));
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
 cameraUI();
}
async function refreshRender(){const before=renderJob.status;try{renderJob=await api('/api/render');}catch{}renderUI();clearTimeout(renderTimer);if(renderJob.status==='running')renderTimer=setTimeout(refreshRender,1000);else if(before==='running'&&renderJob.status==='done')message('Render finished. Open or download the video in the Render video panel.');else if(before==='running'&&renderJob.status==='failed')message(`Render failed: ${renderJob.error}`,true);}
function startRender(mode,startBar=null){action(async()=>{if(!current)throw Error('Select a song first.');await persist();renderJob=await api(`/api/songs/${current.id}/render`,jsonOptions('POST',startBar?{mode,start_bar:startBar}:{mode}));const stage=isPiano()&&onStage(),look=(current.piano_look==='plumes'?'plumes':'musical notes')+({white:' in white',gold:' in gold',hands:' coloured by hand'}[current.piano_colors]||'')+(stage&&shotList()?' and camera shots':''),from=startBar?` from bar ${startBar}`:'';message(mode==='full'?(stage?`Rendering the full song with ${look} in background Blender (about 2 minutes per second of song)…`:'Rendering the full song in background Blender…'):(stage?`Rendering a 4-second half-size draft${from} with ${look} in background Blender…`:'Rendering a 4-second test in background Blender…'));refreshRender();});}
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
$('deleteTabNote').onclick=()=>{if(selectedTabNote&&!selectedTabNote.isNew)deleteNote(selectedTabNote);};
$('saveTabNote').onclick=()=>{const note=selectedTabNote;if(!current||!lesson||!note)return message('Select a tab note first.',true);const string=Number($('editString').value),fret=Number($('editFret').value),bar=Number($('editBar').value),inBar=Number($('editBeat').value),measure=measureBeats();
 if(!Number.isInteger(string)||string<1||string>6)return message('String must be 1 to 6.',true);if($('editFret').value===''||!Number.isInteger(fret)||fret<0||fret>20)return message('Fret must be 0 to 20.',true);if(!Number.isInteger(bar)||bar<1)return message('Bar must be 1 or later.',true);if(!(inBar>=1&&inBar<measure+1))return message(`Beat must be from 1 to below ${measure+1} (quarter-note beats in the bar).`,true);
 const start=Math.round(((bar-1)*measure+inBar-1)*48)/48,start_beat=!note.isNew&&Math.abs(start-note.start)<1e-6?note.start_beat:fraction(start),duration_beats=$('editLength').value;
 if(lesson.notes.some(n=>n.id!==note.id&&n.string===string&&Math.abs(n.start-start)<1e-6))return message(`String ${string} already has a note there.`,true);
 if(note.isNew)editNotes(`/api/songs/${current.id}/notes`,jsonOptions('POST',{string,fret,start_beat,duration_beats}),`Note added: string ${string}, fret ${fret}, bar ${bar} beat ${inBar}. Undo with ⌘Z.`);
 else editNotes(`/api/songs/${current.id}/notes`,jsonOptions('PATCH',{note_id:note.id,string,fret,start_beat,duration_beats}),'Tab note updated. Undo with ⌘Z.',note.id);};
$('undoEdit').onclick=()=>undoEdit(false);$('redoEdit').onclick=()=>undoEdit(true);
$('generateMidi').onclick=()=>action(async()=>{if(!current)throw Error('Create a song first.');if(!current.wav_name)throw Error('Import WAV or MP3 audio first.');message('Generating MIDI from the audio locally…');const row=await api(`/api/songs/${current.id}/generate-midi`,{method:'POST'});songs=songs.map(s=>s.id===row.id?row:s);await selectSong(row);const c=row.cleanup,t=row.timing;message(`MIDI generated: ${c.kept} notes kept (${c.overtones_removed+c.echoes_removed} false notes removed, ${c.rejoined} ringing notes rejoined, ${c.recovered+(t?.restored||0)} missed repeats restored).`+(t?` Tempo ${t.tempo_bpm} BPM${t.tempo_changes?` with ${t.tempo_changes} tempo change${t.tempo_changes>1?'s':''}`:''}, ${t.snapped} notes snapped to ${t.grid==='1/2'?'8ths':'16ths'}.`:' Set the tempo manually.'));});
$('chooseTab').onclick=()=>$('tabFile').click();
$('showChanges').onchange=draw;
$('undoReview').onclick=()=>action(async()=>{if(!current?.can_undo_review)throw Error('There is no tab review to undo.');if(!confirm('Undo the tab review? The lesson from before the review comes back; note edits made since the review are lost.'))return;const row=await api(`/api/songs/${current.id}/review/undo`,{method:'POST'});songs=songs.map(s=>s.id===row.id?row:s);await selectSong(row);message('Tab review undone: the previous lesson is back. Send to Blender again to update the scene.');});
$('tabFile').onchange=()=>action(async()=>{const file=$('tabFile').files[0];$('tabFile').value='';if(!file)return;if(!current?.wav_name)throw Error('Import the audio first; the tab is fitted to it.');message(current.json_name?'Reviewing the lesson with the tab and the audio…':'Fitting the tab to the audio…');const form=new FormData();form.append('file',file);const row=await api(`/api/songs/${current.id}/assets/tab`,{method:'POST',body:form});songs=songs.map(s=>s.id===row.id?row:s);await selectSong(row);
 const r=row.tab_review;if(r){const places=r.places.map(p=>`${p.bars[0]===p.bars[1]?`bar ${p.bars[0]}`:`bars ${p.bars[0]}–${p.bars[1]}`} (${p.heard} of ${p.notes} notes heard)`).join(', '),weak=r.places.some(p=>p.heard<.6*p.notes);message(`Lesson reviewed with the tab. Found at ${places}; those bars now follow the tab, corrected to what the recording plays. ${r.kept} notes unchanged, ${r.fingering} re-fingered, ${r.moved} moved, ${r.added} added, ${r.removed} removed. Other bars keep their notes, fingered ${r.position?`around fret ${r.position}`:'at low frets'} like the tab. Changes are highlighted in the tab; Undo review puts the previous lesson back.`+(r.transpose?` The audio sounds ${Math.abs(r.transpose)} semitone${Math.abs(r.transpose)>1?'s':''} ${r.transpose>0?'higher (capo?)':'lower'} than the tab.`:'')+(weak?' Many tab notes were not heard: check that the tab matches this recording.':''),weak||!!r.transpose);return;}
 const f=row.tab_fit,heard=f.matched/f.notes;const a=f.adapted||{moved:0,added:0,removed:0};message(`Tab fitted: ${f.matched} of ${f.notes} notes heard in the audio (average ${f.mean_error_ms} ms off), about ${f.tempo_bpm} BPM, starting at ${f.audio_start} s. Adapted to the playing: ${a.moved} moved, ${a.added} added, ${a.removed} not played and removed.`+(f.transpose?` The audio sounds ${Math.abs(f.transpose)} semitone${Math.abs(f.transpose)>1?'s':''} ${f.transpose>0?'higher (capo?)':'lower'} than the tab.`:'')+(heard<.6?' Many notes were not heard: check that the tab matches this recording.':''),heard<.6||!!f.transpose);});
$('instrument').onchange=()=>action(async()=>{const instrument=$('instrument').value;if(!current)return;const row=await api(`/api/songs/${current.id}/instrument`,jsonOptions('POST',{instrument}));songs=songs.map(s=>s.id===row.id?row:s);await selectSong(row);
 const s=row.summary?.piano;message(instrument==='piano'?(row.json_name?`Song switched to piano: ${s.right} notes for the right hand, ${s.left} for the left`+(s.hands_from==='midi_tracks'?' (from the MIDI tracks).':'.')+' Click a note to switch its hand.':'Song switched to piano. MIDI imports will plan left and right hands.'):(row.json_name?`Song switched to guitar`+(row.changed?`: ${row.changed} notes got new strings and frets.`:'.'):'Song switched to guitar.'));}).finally(()=>{$('instrument').value=current?.instrument||'guitar';});
$('planHands').onclick=()=>action(async()=>{const row=await api(`/api/songs/${current.id}/hands/plan`,{method:'POST'});await reloadLesson(row);message(`Hands planned again: ${row.changed} notes changed hand. Notes whose hand you chose stayed.`);});
$('handPosition').onchange=()=>action(async()=>{const value=$('handPosition').value,position=value===''?null:Number(value);if((current.summary?.source_format==='tab'||current.summary?.tab_review)&&!confirm("Replace the tab's fingering with generated fingering? Import the tab again to get it back.")){$('handPosition').value=current.hand_position??'';return;}const row=await api(`/api/songs/${current.id}/fingering`,jsonOptions('POST',{position}));songs=songs.map(s=>s.id===row.id?row:s);await selectSong(row);message(`Fingering updated around ${position?`the ${$('handPosition').selectedOptions[0].text}`:'low frets'}: ${row.moved} notes moved. Send to Blender again to update the scene.`);});
for(const kind of ['midi','json','wav']){const suffix=kind==='json'?'Json':kind==='wav'?'Wav':'Midi';$('open'+suffix).onclick=()=>{if(current?.[`${kind}_name`]||(kind==='midi'&&current?.json_name))window.open(assetUrl(kind),'_blank');};$('download'+suffix).onclick=()=>downloadAsset(kind);}
for(const kind of ['midi','json','wav']){const suffix=kind==='json'?'Json':kind==='wav'?'Wav':'Midi';$('choose'+suffix).onclick=()=>$(kind+'File').click();$(kind+'File').onchange=()=>action(async()=>{const file=$(kind+'File').files[0];if(!file)return;if(!current)throw Error('Create a song first.');const replacedWav=kind==='wav'&&!!current.wav_name;const form=new FormData();form.append('file',file);const row=await api(`/api/songs/${current.id}/assets/${kind}`,{method:'POST',body:form});songs=songs.map(s=>s.id===row.id?row:s);await selectSong(row);const converted=kind==='wav'&&/\.mp3$/i.test(file.name)?' (MP3 converted to WAV)':'';message(kind==='midi'?'MIDI analyzed and lesson JSON created.':replacedWav?`Audio replaced${converted}. Previous MIDI and lesson JSON were cleared; generate MIDI again for this audio.`:kind==='wav'?`Audio imported${converted}.`:`${kind.toUpperCase()} imported and validated.`);$(kind+'File').value='';});}
$('search').oninput=library;$('newSong').onclick=()=>{$('newDialog').showModal();$('newName').value='';$('newName').focus();};$('closeDialog').onclick=$('cancelDialog').onclick=()=>$('newDialog').close();
$('newForm').onsubmit=e=>{e.preventDefault();action(async()=>{const row=await api('/api/songs',jsonOptions('POST',{name:$('newName').value.trim()}));songs.unshift(row);$('newDialog').close();await selectSong(row);});};
new ResizeObserver(draw).observe($('tablature'));
(async()=>{try{songs=await api('/api/songs');if(songs.length)await selectSong(songs[0]);else fields();await refreshConnection();await refreshRender();}catch(e){message(e.message,true);}icons();})();
setInterval(()=>{if(!busy&&!document.hidden)refreshConnection();},12000);
document.addEventListener('visibilitychange',()=>{if(!busy&&!document.hidden)refreshConnection();});
