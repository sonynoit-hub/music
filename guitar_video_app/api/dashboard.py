"""Local song library and Blender transfer dashboard."""
import io
import json
import math
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import threading
import time
import uuid
import wave
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from guitar_video_app.core.audio_transcription import TranscriptionUnavailable, transcribe_wav_to_midi
from guitar_video_app.core.lesson_v2 import prepare
from guitar_video_app.core.music_analyzer import normalize_midi_file
from guitar_video_app.core.normalized_to_lesson_v2 import normalized_to_lesson_v2

ROOT = Path(__file__).resolve().parents[2]
STORE = Path(os.environ.get('GUITAR_DASHBOARD_STORE', ROOT/'data/dashboard'))
STORE.mkdir(parents=True,exist_ok=True)
STATIC = ROOT/'guitar_video_app/ui'
TRANSFER_LOCK = threading.Lock()
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


def summary(data):
    if len(data.get('notes',[]))>5000:
        raise ValueError('This preview supports up to 5,000 notes per lesson.')
    lesson=prepare(data)
    strings=sorted({note['string'] for note in lesson['notes']})
    return dict(notes=len(lesson['notes']),bpm=data['tempo_bpm'],fps=lesson['fps'],
                duration=float(lesson['end']*lesson['frames_per_beat']/lesson['fps']),
                measures=math.ceil(lesson['end']/lesson['measure']),signature=data['time_signature'],
                music_layer=dict(format='v2',tracks=len(strings),beats=float(lesson['end']),
                                 tempo_changes=1,time_signature_changes=1,audio_offset=0))


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
    return await call_next(request)


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
    if current['name']!=payload.name or current['offset']!=payload.offset:
        with db() as conn:
            conn.execute('UPDATE songs SET name=?,offset=?,revision=revision+1,updated=? WHERE id=?',
                         (payload.name.strip() or 'Untitled song',payload.offset,time.time(),identity))
    return public(song(identity))


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


@app.post('/api/songs/{identity}/assets/{kind}')
async def upload(identity: str,kind: str,file: UploadFile):
    current=song(identity)
    if kind not in ('midi','json','wav'):
        raise HTTPException(400,'Expected MIDI, JSON or WAV')
    content=await file.read(256*1024*1024+1)
    if len(content)>256*1024*1024:
        raise HTTPException(413,'File exceeds 256 MB')
    try:
        if kind=='json':
            lesson_data,details=normalize_dashboard_json(content)
            content=(json.dumps(lesson_data,indent=2)+'\n').encode()
        elif kind=='wav':
            with wave.open(io.BytesIO(content)) as wav:
                if wav.getnchannels() not in (1,2) or not wav.getnframes():
                    raise ValueError('Choose a nonempty mono or stereo PCM WAV.')
                duration=wav.getnframes()/wav.getframerate()
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
    with db() as conn:
        if kind=='midi':
            return result
        elif kind=='json':
            conn.execute('UPDATE songs SET json_path=?,json_name=?,summary=?,revision=revision+1,updated=? WHERE id=?',
                         (str(path),Path(file.filename or 'lesson.json').name,json.dumps(details),time.time(),identity))
        else:
            if current.get('wav_path'):
                conn.execute('''UPDATE songs
                                SET wav_path=?,wav_name=?,audio_duration=?,
                                    midi_path=NULL,midi_name=NULL,
                                    json_path=NULL,json_name=NULL,summary=NULL,
                                    synced_revision=NULL,revision=revision+1,updated=?
                                WHERE id=?''',
                             (str(path),Path(file.filename or 'audio.wav').name,duration,time.time(),identity))
            else:
                conn.execute('UPDATE songs SET wav_path=?,wav_name=?,audio_duration=?,revision=revision+1,updated=? WHERE id=?',
                             (str(path),Path(file.filename or 'audio.wav').name,duration,time.time(),identity))
    return public(song(identity))


@app.post('/api/songs/{identity}/generate-midi')
def generate_midi(identity: str):
    row=song(identity)
    if not row['wav_path']:
        raise HTTPException(400,'Import WAV audio first')
    folder=STORE/identity
    try:
        midi_path=transcribe_wav_to_midi(row['wav_path'],folder/'generated-midi')
        stored_path=folder/f'{uuid.uuid4().hex}.mid'
        shutil.copy2(midi_path,stored_path)
        return store_midi_analysis(identity,stored_path,stored_path.name,Path(row['wav_name'] or stored_path.name).stem,tolerate_unplayable=True)
    except TranscriptionUnavailable as exc:
        raise HTTPException(501,str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500,f'MIDI generation failed: {exc}') from exc


@app.get('/api/songs/{identity}/audio')
def audio(identity: str, download: bool = False):
    row=song(identity)
    if not row['wav_path']:
        raise HTTPException(404,'No audio')
    return FileResponse(row['wav_path'],media_type='audio/wav',filename=row.get('wav_name') or 'audio.wav',
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
        try:
            result=bridge(dict(command='dashboard_sync',json_path=row['json_path'],wav_path=row['wav_path'],
                               song_id=identity,revision=row['revision'],offset_seconds=row['offset'],timeout=60))
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


@app.get('/api/preview')
def preview():
    return FileResponse(ROOT/'outputs/lesson-v2-chords.png')


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
