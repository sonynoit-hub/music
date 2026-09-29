"""Local song library and Blender transfer dashboard."""
import collections
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
from typing import Literal
import uuid
import wave
from contextlib import contextmanager
from fractions import Fraction

from fastapi import FastAPI, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from guitar_video_app.core.audio_transcription import TranscriptionUnavailable, transcribe_wav_to_midi
from guitar_video_app.core.lesson_v2 import beat as lesson_beat, prepare, seconds_at, tempo_map
from guitar_video_app.core.retime import (choose_grid, fit_tempo_map, restore_repeats, retime_lesson,
                                          suggest_grid, tidy_lesson)
from guitar_video_app.core.transcription_cleanup import clean_transcribed_midi
from guitar_video_app.integrations.link_audio import LinkAudioError, download_audio
from guitar_video_app.core.music_analyzer import normalize_midi_file
from guitar_video_app.core.normalized_to_lesson_v2 import normalized_to_lesson_v2

ROOT = Path(__file__).resolve().parents[2]
STORE = Path(os.environ.get('GUITAR_DASHBOARD_STORE', ROOT/'data/dashboard'))
STORE.mkdir(parents=True,exist_ok=True)
STATIC = ROOT/'guitar_video_app/ui'
TRANSFER_LOCK = threading.Lock()
BLENDER = Path(os.environ.get('GUITAR_BLENDER', '/Applications/Blender.app/Contents/MacOS/Blender'))
RENDER_SCENE = ROOT/'outputs/v4-vertical.blend'
RENDER_SCRIPT = ROOT/'scripts/render_lesson.py'
RENDER_FPS = 30
RENDER_TEST_SECONDS = 4
RENDER_LOCK = threading.Lock()
FRAME_LINE = re.compile(r'^Frame written:\s*(\d+)')
# Messages from the user's Blender startup script; they do not affect background renders.
HARMLESS_RENDER_ERRORS = ('_RestrictData', 'Address already in use')
render_job = {}
render_process = None
app = FastAPI(title='Guitar Lesson Studio',docs_url=None,redoc_url=None)


@contextmanager
def db():
    conn=sqlite3.connect(STORE/'library.sqlite3',timeout=10)
    conn.row_factory=sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


with db() as conn:
    conn.execute('''CREATE TABLE IF NOT EXISTS songs (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, json_path TEXT, wav_path TEXT,
        json_name TEXT, wav_name TEXT, summary TEXT, audio_duration REAL,
        offset REAL NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1,
        synced_revision INTEGER, updated REAL NOT NULL)''')
    columns={row['name'] for row in conn.execute('PRAGMA table_info(songs)')}
    if 'midi_path' not in columns:
        conn.execute('ALTER TABLE songs ADD COLUMN midi_path TEXT')
    if 'midi_name' not in columns:
        conn.execute('ALTER TABLE songs ADD COLUMN midi_name TEXT')
    # NULL title means "use the song name"; an empty string hides it.
    for column in ('title','subtitle'):
        if column not in columns:
            conn.execute(f'ALTER TABLE songs ADD COLUMN {column} TEXT')


def summary(data):
    if len(data.get('notes',[]))>5000:
        raise ValueError('This preview supports up to 5,000 notes per lesson.')
    lesson=prepare(data)
    strings=sorted({note['string'] for note in lesson['notes']})
    return dict(notes=len(lesson['notes']),bpm=data['tempo_bpm'],fps=lesson['fps'],
                tempo_changes=len(lesson['tempo_map'])-1,
                duration=float(seconds_at(lesson['tempo_map'],lesson['end'])),
                measures=math.ceil(lesson['end']/lesson['measure']),signature=data['time_signature'],
                music_layer=dict(format='v2',tracks=len(strings),beats=float(lesson['end']),
                                 tempo_changes=len(lesson['tempo_map']),time_signature_changes=1,audio_offset=0))


def normalize_dashboard_json(content):
    data=json.loads(content)
    source_format='v2'
    normalized_layer=None
    if data.get('schema_version')=='1.0':
        source_format='normalized'
        normalized_layer=dict(format='normalized',
                              tracks=len(data.get('tracks',[])),
                              beats=len(data.get('beats',[])),
                              measures=len(data.get('measures',[])),
                              tempo_changes=len(data.get('timing',{}).get('tempo_changes',[])),
                              time_signature_changes=len(data.get('timing',{}).get('time_signature_changes',[])),
                              audio_offset=data.get('audio',{}).get('audio_offset',0))
        data=normalized_to_lesson_v2(data,fps=60)
    details=summary(data)
    details['source_format']=source_format
    if normalized_layer:
        details['music_layer']=normalized_layer
    return data,details


def dashboard_music_layer(normalized):
    return dict(format='midi',
                tracks=len(normalized.get('tracks',[])),
                beats=len(normalized.get('beats',[])),
                measures=len(normalized.get('measures',[])),
                tempo_changes=len(normalized.get('timing',{}).get('tempo_changes',[])),
                time_signature_changes=len(normalized.get('timing',{}).get('time_signature_changes',[])),
                audio_offset=normalized.get('audio',{}).get('audio_offset',0))


def analyze_dashboard_midi(path, title, *, tolerate_unplayable=False):
    normalized=normalize_midi_file(path,title=title,tolerate_unplayable=tolerate_unplayable)
    normalized_data=json.loads(json.dumps({
        'schema_version': normalized.schema_version,
        'song': normalized.song,
        'timing': normalized.timing,
        'tracks': [track.__dict__ for track in normalized.tracks],
        'notes': [note.__dict__ for note in normalized.notes],
        'measures': [measure.__dict__ for measure in normalized.measures],
        'beats': [beat.__dict__ for beat in normalized.beats],
        'audio': normalized.audio,
        'guitar': normalized.guitar,
    }))
    lesson_data=normalized_to_lesson_v2(normalized_data,fps=60,name=title,skip_unmapped=tolerate_unplayable)
    details=summary(lesson_data)
    details['source_format']='midi'
    details['music_layer']=dashboard_music_layer(normalized_data)
    if tolerate_unplayable:
        details['mapping_mode']='tolerant'
        details['music_layer']['mapped_notes']=len(lesson_data.get('notes',[]))
        details['music_layer']['detected_notes']=len(normalized_data.get('notes',[]))
    return normalized_data,lesson_data,details


def store_midi_analysis(identity, midi_path, midi_name, title, *, tolerate_unplayable=False):
    row=song(identity)
    folder=STORE/identity
    normalized_data,lesson_data,details=analyze_dashboard_midi(midi_path,title,tolerate_unplayable=tolerate_unplayable)
    lesson_path=folder/f'{uuid.uuid4().hex}.json'
    normalized_path=folder/f'{uuid.uuid4().hex}.normalized.json'
    lesson_path.write_text(json.dumps(lesson_data,indent=2)+'\n',encoding='utf-8')
    normalized_path.write_text(json.dumps(normalized_data,indent=2)+'\n',encoding='utf-8')
    with db() as conn:
        conn.execute('UPDATE songs SET midi_path=?,midi_name=?,json_path=?,json_name=?,summary=?,revision=revision+1,updated=? WHERE id=?',
                     (str(midi_path),midi_name,str(lesson_path),lesson_path.name,json.dumps(details),time.time(),identity))
    return public(song(identity))


def trim_to_last_measure(data):
    """End the lesson at the bar line after its last note, dropping empty trailing measures."""
    measure=Fraction(data['time_signature'][0]*4,data['time_signature'][1])
    last=max(lesson_beat(n['start_beat'])+lesson_beat(n['duration_beats']) for n in data['notes'])
    data['end_beat']=str(math.ceil(last/measure)*measure)


def auto_time_transcription(identity,onsets=()):
    """Fit tempo, downbeat and per-measure tempo changes to a fresh transcription, restore
    missed repeats from the model's onsets (audio seconds), then tidy it; notes keep their audio times."""
    row=song(identity)
    path=Path(row['json_path'])
    data=json.loads(path.read_text(encoding='utf-8'))
    tempos=tempo_map(data)
    bpm,first=suggest_grid([float(seconds_at(tempos,lesson_beat(n['start_beat']))) for n in data['notes']])
    zero=retime_lesson(data,bpm,first)
    grid=choose_grid(data)
    changes=fit_tempo_map(data,grid)
    restored=restore_repeats(data,[(time-float(zero),pitch,strength) for time,pitch,strength in onsets],grid)
    stats=tidy_lesson(data,grid=grid)
    trim_to_last_measure(data)
    previous=row.get('summary') or {}
    details=dict(summary(data),source_format=previous.get('source_format'),music_layer=previous.get('music_layer'))
    path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    with db() as conn:
        conn.execute('UPDATE songs SET summary=?,offset=?,synced_revision=NULL,revision=revision+1,updated=? WHERE id=?',
                     (json.dumps(details),round(-float(zero),6),time.time(),identity))
    return dict(tempo_bpm=bpm,tempo_changes=changes,restored=restored,**stats)


def song(identity):
    with db() as conn:
        row=conn.execute('SELECT * FROM songs WHERE id=?',(identity,)).fetchone()
    if not row:
        raise HTTPException(404,'Song not found')
    result=dict(row)
    result['summary']=json.loads(result['summary']) if result['summary'] else None
    return result


def public(row):
    return {k:v for k,v in row.items() if k not in ('json_path','wav_path','midi_path')}


def bridge(command,port=8765):
    timeout=command.get('timeout',5)
    with socket.create_connection(('127.0.0.1',port),timeout=3) as sock:
        sock.settimeout(timeout+2)
        sock.sendall((json.dumps(command)+'\n').encode())
        data=b''
        while not data.endswith(b'\n'):
            chunk=sock.recv(65536)
            if not chunk:
                break
            data+=chunk
        result=json.loads(data)
    if not result.get('ok'):
        raise ValueError(result.get('error','Blender request failed'))
    return result


@app.middleware('http')
async def local_requests(request: Request, call_next):
    host=request.headers.get('host','').split(':')[0]
    if host not in ('127.0.0.1','localhost','testserver'):
        return JSONResponse({'detail':'Local access only'},status_code=403)
    origin=request.headers.get('origin')
    if origin and origin != f'http://{request.headers.get("host")}':
        return JSONResponse({'detail':'Cross-origin requests are disabled'},status_code=403)
    response=await call_next(request)
    if request.url.path=='/' or request.url.path.startswith('/static/'):
        response.headers['Cache-Control']='no-cache'
    return response


@app.get('/')
def index():
    return FileResponse(STATIC/'index.html')


@app.get('/api/songs')
def songs():
    with db() as conn:
        ids=[row['id'] for row in conn.execute('SELECT id FROM songs ORDER BY updated DESC')]
    return [public(song(identity)) for identity in ids]


class SongInput(BaseModel):
    name: str = Field(min_length=1,max_length=120)
    offset: float = Field(default=0,ge=-60,le=60,allow_inf_nan=False)
    title: str | None = Field(default=None,max_length=120)
    subtitle: str | None = Field(default=None,max_length=120)


def video_title(row):
    """Title and subtitle drawn above the guitar."""
    title=row['name'] if row.get('title') is None else row['title']
    return title.strip(),(row.get('subtitle') or '').strip()


def render_path(folder, name, mode):
    """Video file named after the song; a number is added instead of replacing an earlier render."""
    stem=re.sub(r'[\x00-\x1f/\\:*?"<>|]+',' ',name)
    stem=re.sub(r'\s+',' ',stem).strip(' .')[:100] or 'Song'
    if mode=='test':
        stem+=' (test)'
    path,count=folder/f'{stem}.mp4',2
    while path.exists():
        path,count=folder/f'{stem} {count}.mp4',count+1
    return path


class TimingInput(BaseModel):
    tempo_bpm: float = Field(ge=20,le=300,allow_inf_nan=False)
    first_beat: float = Field(ge=-60,le=3600,allow_inf_nan=False)


class TabNoteEdit(BaseModel):
    note_id: str = Field(min_length=1,max_length=80)
    string: int = Field(ge=1,le=6)
    fret: int = Field(ge=0,le=20)


@app.post('/api/songs')
def create(payload: SongInput):
    identity=uuid.uuid4().hex
    with db() as conn:
        conn.execute('INSERT INTO songs(id,name,offset,updated) VALUES(?,?,?,?)',
                     (identity,payload.name.strip() or 'Untitled song',payload.offset,time.time()))
    return public(song(identity))


@app.patch('/api/songs/{identity}')
def update(identity: str,payload: SongInput):
    current=song(identity)
    title=current['title'] if payload.title is None else payload.title.strip()
    subtitle=current['subtitle'] if payload.subtitle is None else payload.subtitle.strip()
    if (current['name'],current['offset'],current['title'],current['subtitle'])!=(payload.name,payload.offset,title,subtitle):
        with db() as conn:
            conn.execute('UPDATE songs SET name=?,offset=?,title=?,subtitle=?,revision=revision+1,updated=? WHERE id=?',
                         (payload.name.strip() or 'Untitled song',payload.offset,title,subtitle,time.time(),identity))
    return public(song(identity))


@app.get('/api/songs/{identity}/timing-suggestion')
def timing_suggestion(identity: str):
    row=song(identity)
    if not row['json_path']:
        raise HTTPException(400,'Import or generate lesson JSON first')
    data=json.loads(Path(row['json_path']).read_text(encoding='utf-8'))
    tempos=tempo_map(data)
    try:
        bpm,first=suggest_grid([float(seconds_at(tempos,lesson_beat(n['start_beat'])))-row['offset'] for n in data['notes']])
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    return dict(tempo_bpm=bpm,first_beat=first)


@app.post('/api/songs/{identity}/timing')
def update_timing(identity: str,payload: TimingInput):
    """Re-grid the lesson; first_beat is in audio seconds and notes keep their audio times."""
    row=song(identity)
    if not row['json_path']:
        raise HTTPException(400,'Import or generate lesson JSON first')
    path=Path(row['json_path'])
    data=json.loads(path.read_text(encoding='utf-8'))
    try:
        zero=retime_lesson(data,payload.tempo_bpm,payload.first_beat+row['offset'])
        details=summary(data)
    except ValueError as exc:
        raise HTTPException(400,f'Invalid timing: {exc}') from exc
    offset=round(row['offset']-float(zero),6)
    if abs(offset)>60:
        raise HTTPException(400,'The first beat is too far from the start of the audio.')
    previous=row.get('summary') or {}
    for field in ('source_format','music_layer'):
        if previous.get(field):
            details[field]=previous[field]
    path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    with db() as conn:
        conn.execute('UPDATE songs SET summary=?,offset=?,synced_revision=NULL,revision=revision+1,updated=? WHERE id=?',
                     (json.dumps(details),offset,time.time(),identity))
    return public(song(identity))


class TidyInput(BaseModel):
    snap: bool = True
    duplicates: bool = True
    lengths: bool = True


@app.post('/api/songs/{identity}/tidy')
def tidy_notes(identity: str,payload: TidyInput):
    row=song(identity)
    if not row['json_path']:
        raise HTTPException(400,'Import or generate lesson JSON first')
    path=Path(row['json_path'])
    data=json.loads(path.read_text(encoding='utf-8'))
    try:
        stats=tidy_lesson(data,snap=payload.snap,duplicates=payload.duplicates,lengths=payload.lengths)
        details=summary(data)
    except ValueError as exc:
        raise HTTPException(400,f'Could not tidy notes: {exc}') from exc
    previous=row.get('summary') or {}
    for field in ('source_format','music_layer'):
        if previous.get(field):
            details[field]=previous[field]
    path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    with db() as conn:
        conn.execute('UPDATE songs SET summary=?,synced_revision=NULL,revision=revision+1,updated=? WHERE id=?',
                     (json.dumps(details),time.time(),identity))
    return dict(public(song(identity)),tidy=stats)


@app.patch('/api/songs/{identity}/notes')
def update_note(identity: str,payload: TabNoteEdit):
    row=song(identity)
    if not row['json_path']:
        raise HTTPException(400,'Import or generate lesson JSON first')
    path=Path(row['json_path'])
    data=json.loads(path.read_text(encoding='utf-8'))
    changed=False
    for note in data.get('notes',[]):
        if str(note.get('id'))==payload.note_id:
            note['string']=payload.string
            note['fret']=payload.fret
            changed=True
            break
    if not changed:
        raise HTTPException(404,'Note not found')
    details=summary(data)
    if row.get('summary'):
        previous=row['summary']
        if previous.get('source_format'):
            details['source_format']=previous['source_format']
        if previous.get('music_layer'):
            details['music_layer']=previous['music_layer']
    path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    with db() as conn:
        conn.execute('UPDATE songs SET summary=?,synced_revision=NULL,revision=revision+1,updated=? WHERE id=?',
                     (json.dumps(details),time.time(),identity))
    return public(song(identity))


def audio_to_wav(content, filename):
    with tempfile.TemporaryDirectory() as folder:
        source=Path(folder)/f'source{Path(filename).suffix.lower() or ".mp3"}'
        target=Path(folder)/'audio.wav'
        source.write_bytes(content)
        try:
            result=subprocess.run(['afconvert','-f','WAVE','-d','LEI16',str(source),str(target)],
                                  capture_output=True,text=True,timeout=120)
        except FileNotFoundError as exc:
            raise ValueError('MP3 import needs the macOS afconvert tool.') from exc
        if result.returncode or not target.exists():
            raise ValueError('Choose a WAV or MP3 file.')
        return target.read_bytes()


def store_audio(identity, content, name):
    """Save WAV bytes as the song's audio; replacing audio clears its MIDI and lesson."""
    current=song(identity)
    try:
        with wave.open(io.BytesIO(content)) as wav:
            if wav.getnchannels() not in (1,2) or not wav.getnframes():
                raise ValueError('Choose a nonempty mono or stereo WAV or MP3.')
            duration=wav.getnframes()/wav.getframerate()
    except Exception as exc:
        raise HTTPException(400,f'Invalid audio: {exc}') from exc
    folder=STORE/identity
    folder.mkdir(exist_ok=True)
    path=folder/f'{uuid.uuid4().hex}.wav'
    path.write_bytes(content)
    with db() as conn:
        if current.get('wav_path'):
            conn.execute('''UPDATE songs
                            SET wav_path=?,wav_name=?,audio_duration=?,
                                midi_path=NULL,midi_name=NULL,
                                json_path=NULL,json_name=NULL,summary=NULL,
                                synced_revision=NULL,revision=revision+1,updated=?
                            WHERE id=?''',
                         (str(path),name,duration,time.time(),identity))
        else:
            conn.execute('UPDATE songs SET wav_path=?,wav_name=?,audio_duration=?,revision=revision+1,updated=? WHERE id=?',
                         (str(path),name,duration,time.time(),identity))
    return public(song(identity))


class LinkInput(BaseModel):
    url: str = Field(min_length=8,max_length=2000)


@app.post('/api/songs/{identity}/assets/link')
def import_link(identity: str,payload: LinkInput):
    current=song(identity)
    try:
        content,title=download_audio(payload.url)
    except LinkAudioError as exc:
        raise HTTPException(400,str(exc)) from exc
    row=store_audio(identity,content,f'{title[:100]}.wav')
    if current['name']=='Untitled song':
        with db() as conn:
            conn.execute('UPDATE songs SET name=? WHERE id=?',(title[:120],identity))
        row=public(song(identity))
    return row


@app.post('/api/songs/{identity}/assets/{kind}')
async def upload(identity: str,kind: str,file: UploadFile):
    song(identity)
    if kind not in ('midi','json','wav'):
        raise HTTPException(400,'Expected MIDI, JSON or audio')
    content=await file.read(256*1024*1024+1)
    if len(content)>256*1024*1024:
        raise HTTPException(413,'File exceeds 256 MB')
    if kind=='wav':
        if content[:4]!=b'RIFF':
            try:
                content=audio_to_wav(content,file.filename or 'audio.mp3')
            except ValueError as exc:
                raise HTTPException(400,f'Invalid audio: {exc}') from exc
        return store_audio(identity,content,Path(file.filename or 'audio.wav').name)
    try:
        if kind=='json':
            lesson_data,details=normalize_dashboard_json(content)
            content=(json.dumps(lesson_data,indent=2)+'\n').encode()
    except Exception as exc:
        raise HTTPException(400,f'Invalid {kind.upper()}: {exc}') from exc
    folder=STORE/identity
    folder.mkdir(exist_ok=True)
    suffix='mid' if kind=='midi' else kind
    path=folder/f'{uuid.uuid4().hex}.{suffix}'
    if kind=='midi':
        path.write_bytes(content)
        try:
            result=store_midi_analysis(identity,path,Path(file.filename or 'lesson.mid').name,Path(file.filename or path.name).stem)
        except Exception as exc:
            try:
                result=store_midi_analysis(identity,path,Path(file.filename or 'lesson.mid').name,Path(file.filename or path.name).stem,tolerate_unplayable=True)
            except Exception:
                path.unlink(missing_ok=True)
                raise HTTPException(400,f'Invalid MIDI: {exc}') from exc
    else:
        path.write_bytes(content)
    if kind=='midi':
        return result
    with db() as conn:
        conn.execute('UPDATE songs SET json_path=?,json_name=?,summary=?,revision=revision+1,updated=? WHERE id=?',
                     (str(path),Path(file.filename or 'lesson.json').name,json.dumps(details),time.time(),identity))
    return public(song(identity))


@app.post('/api/songs/{identity}/generate-midi')
def generate_midi(identity: str):
    row=song(identity)
    if not row['wav_path']:
        raise HTTPException(400,'Import WAV or MP3 audio first')
    folder=STORE/identity
    try:
        midi_path=transcribe_wav_to_midi(row['wav_path'],folder/'generated-midi')
        stored_path=folder/f'{uuid.uuid4().hex}.mid'
        cleanup=clean_transcribed_midi(midi_path,stored_path)
        store_midi_analysis(identity,stored_path,stored_path.name,Path(row['wav_name'] or stored_path.name).stem,tolerate_unplayable=True)
        onsets_path=midi_path.with_suffix('.onsets.json')
        onsets=json.loads(onsets_path.read_text(encoding='utf-8')) if onsets_path.exists() else []
        try:
            timing=auto_time_transcription(identity,onsets)
        except ValueError:
            timing=None
        return dict(public(song(identity)),cleanup=cleanup,timing=timing)
    except TranscriptionUnavailable as exc:
        raise HTTPException(501,str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500,f'MIDI generation failed: {exc}') from exc


@app.get('/api/songs/{identity}/audio')
def audio(identity: str, download: bool = False):
    row=song(identity)
    if not row['wav_path']:
        raise HTTPException(404,'No audio')
    return FileResponse(row['wav_path'],media_type='audio/wav',filename=Path(row.get('wav_name') or 'audio').with_suffix('.wav').name,
                        content_disposition_type='attachment' if download else 'inline')


@app.get('/api/songs/{identity}/lesson')
def lesson(identity: str, download: bool = False):
    row=song(identity)
    if not row['json_path']:
        raise HTTPException(404,'No lesson')
    return FileResponse(row['json_path'],media_type='application/json',filename=row.get('json_name') or 'lesson.json',
                        content_disposition_type='attachment' if download else 'inline')


@app.get('/api/songs/{identity}/midi')
def midi(identity: str, download: bool = False):
    row=song(identity)
    if not row['midi_path']:
        raise HTTPException(404,'No MIDI')
    return FileResponse(row['midi_path'],media_type='audio/midi',filename=row.get('midi_name') or 'lesson.mid',
                        content_disposition_type='attachment' if download else 'inline')


@app.get('/api/blender')
def connection():
    try:
        return bridge({'command':'dashboard_status','timeout':3})
    except Exception:
        return dict(ok=False,error='Blender bridge is disconnected')


@app.post('/api/blender/connect')
def connect():
    current=connection()
    if current['ok']:
        return current
    # Bootstrap only our fixed bridge through the already enabled local Blender MCP.
    code=(f'import sys; sys.path.insert(0,{str(ROOT)!r})\n'
          'from guitar_video_app.integrations.blender_bridge_server import start_bridge\n'
          'print(start_bridge())\n')
    try:
        with socket.create_connection(('127.0.0.1',9876),timeout=3) as sock:
            sock.settimeout(10)
            sock.sendall(json.dumps({'type':'execute_code','params':{'code':code}}).encode())
            data=b''
            while True:
                chunk=sock.recv(65536)
                if not chunk:
                    break
                data+=chunk
                try:
                    json.loads(data)
                    break
                except ValueError:
                    pass
        result=connection()
        if not result['ok']:
            raise ValueError('Bridge did not start')
        return result
    except Exception as exc:
        raise HTTPException(503,'Open Blender and start its MCP connection, or run scripts/start_dashboard_bridge.py in Blender.') from exc


@app.post('/api/songs/{identity}/send')
def send(identity: str):
    row=song(identity)
    if not row['json_path'] or not row['wav_path']:
        raise HTTPException(400,'Import both lesson JSON and WAV first')
    try:
        summary(json.loads(Path(row['json_path']).read_text()))
        if not TRANSFER_LOCK.acquire(blocking=False):
            raise HTTPException(409,'Another transfer is in progress')
        title,subtitle=video_title(row)
        try:
            result=bridge(dict(command='dashboard_sync',json_path=row['json_path'],wav_path=row['wav_path'],
                               song_id=identity,revision=row['revision'],offset_seconds=row['offset'],
                               title=title,subtitle=subtitle,timeout=60))
        finally:
            TRANSFER_LOCK.release()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503,f'Blender transfer failed: {exc}') from exc
    with db() as conn:
        conn.execute('UPDATE songs SET synced_revision=? WHERE id=?',(row['revision'],identity))
    return dict(song=public(song(identity)),blender=result)


@app.post('/api/blender/save')
def save_blender():
    try:
        return bridge({'command':'dashboard_save','timeout':30})
    except Exception as exc:
        raise HTTPException(503,str(exc)) from exc


class RenderInput(BaseModel):
    mode: Literal['test','full'] = 'test'


def render_status():
    if not render_job:
        return dict(status='idle')
    job={k:v for k,v in render_job.items() if k!='output'}
    job['name']=Path(render_job['output']).name
    return job


def watch_render(process, job):
    tail=collections.deque(maxlen=40)
    for line in process.stdout:
        tail.append(line.rstrip())
        match=FRAME_LINE.search(line)
        if match:
            job['frame']=int(match.group(1))
    code=process.wait()
    with RENDER_LOCK:
        output=Path(job['output'])
        if job['status']=='cancelled':
            output.unlink(missing_ok=True)
        elif code==0 and output.exists() and output.stat().st_size:
            job['status']='done'
            job['frame']=job['frame_end']
        else:
            job['status']='failed'
            errors=[line for line in tail if 'Error' in line and not any(h in line for h in HARMLESS_RENDER_ERRORS)]
            job['error']=errors[-1] if errors else f'Blender exited with code {code}'
        job['finished']=time.time()


@app.post('/api/songs/{identity}/render')
def start_render(identity: str, payload: RenderInput):
    global render_job, render_process
    row=song(identity)
    if not row['json_path'] or not row['wav_path']:
        raise HTTPException(400,'Import both lesson JSON and WAV first')
    if not BLENDER.exists():
        raise HTTPException(503,f'Blender was not found at {BLENDER}')
    data=json.loads(Path(row['json_path']).read_text())
    data['fps']=RENDER_FPS
    try:
        last=prepare(data)['frame_end']
    except Exception as exc:
        raise HTTPException(400,f'This lesson cannot render at {RENDER_FPS} fps: {exc}') from exc
    end=min(last,RENDER_FPS*RENDER_TEST_SECONDS-1) if payload.mode=='test' else last
    with RENDER_LOCK:
        if render_job.get('status')=='running':
            raise HTTPException(409,'A render is already running')
        folder=STORE/identity/'renders'
        folder.mkdir(parents=True,exist_ok=True)
        output=render_path(folder,row['name'],payload.mode)
        title,subtitle=video_title(row)
        command=[str(BLENDER),'-b',str(RENDER_SCENE),'--python-exit-code','1','--python',str(RENDER_SCRIPT),'--',
                 '--json',row['json_path'],'--wav',row['wav_path'],'--offset',str(row['offset']),
                 '--out',str(output),'--fps',str(RENDER_FPS),'--start','0','--end',str(end),
                 f'--title={title}',f'--subtitle={subtitle}']
        render_process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                        text=True,bufsize=1,cwd=ROOT)
        render_job=dict(id=uuid.uuid4().hex,song_id=identity,song_name=row['name'],revision=row['revision'],
                        mode=payload.mode,status='running',frame=None,frame_start=0,frame_end=end,
                        fps=RENDER_FPS,started=time.time(),finished=None,output=str(output),error=None)
        threading.Thread(target=watch_render,args=(render_process,render_job),daemon=True).start()
        return render_status()


@app.get('/api/render')
def get_render():
    return render_status()


@app.post('/api/render/cancel')
def cancel_render():
    with RENDER_LOCK:
        if render_job.get('status')!='running':
            raise HTTPException(409,'No render is running')
        render_job['status']='cancelled'
        render_process.terminate()
        return render_status()


@app.get('/api/render/video')
def render_video(download: bool = False):
    if render_job.get('status')!='done':
        raise HTTPException(404,'No finished render')
    path=Path(render_job['output'])
    return FileResponse(path,media_type='video/mp4',filename=path.name,
                        content_disposition_type='attachment' if download else 'inline')


def seed():
    source=ROOT/'data/lesson_tests/12_complex_32_measures.json'
    wav=ROOT/'outputs/complex_32_measures.wav'
    with db() as conn:
        if conn.execute('SELECT count(*) FROM songs').fetchone()[0] or not source.exists() or not wav.exists():
            return
        identity='complex-32-measures'
        folder=STORE/identity
        folder.mkdir(exist_ok=True)
        shutil.copy2(source,folder/'lesson.json')
        shutil.copy2(wav,folder/'audio.wav')
        with wave.open(str(wav)) as audio:
            duration=audio.getnframes()/audio.getframerate()
        conn.execute('INSERT INTO songs(id,name,json_path,wav_path,json_name,wav_name,summary,audio_duration,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                     (identity,'32-measure guitar study',str(folder/'lesson.json'),str(folder/'audio.wav'),source.name,wav.name,
                      json.dumps(summary(json.loads(source.read_text()))),duration,time.time()))


seed()
app.mount('/static',StaticFiles(directory=STATIC),name='static')
