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
from urllib.parse import quote
import uuid
import wave
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from guitar_video_app.instruments import (activate, active_instrument, as_lesson, check_lesson, lesson_rules,
                                          part_view, parts, sync_parts)
from guitar_video_app.instruments.guitar.mapper import normalize_midi_file
from guitar_video_app.instruments.guitar.normalized import lesson_from_normalized
from guitar_video_app.instruments.guitar.refinger import refinger_part
from guitar_video_app.instruments.guitar.tab import import_tab_to_audio, read_tab, review_with_tab
from guitar_video_app.instruments.guitar.tuning import pitch_of
from guitar_video_app.instruments.guitar.view import (PART as GUITAR, guitar_view, prepare as prepare_guitar_view,
                                                      set_notes, set_position)
from guitar_video_app.instruments.piano import PIANO
from guitar_video_app.instruments.piano.normalized import lesson_from_normalized as piano_lesson_from_normalized
from guitar_video_app.instruments.piano.view import piano_view, prepare as prepare_piano_view, set_hand
from guitar_video_app.integrations.link_audio import LinkAudioError, download_audio
from guitar_video_app.music.analyzer import analyze_midi_file
from guitar_video_app.music.alignment import played_notes
from guitar_video_app.music.audio_transcription import TranscriptionUnavailable, transcribe_wav_to_midi
from guitar_video_app.music.lesson import extend_to_bar, new_note_id, trim_to_last_measure
from guitar_video_app.music.midi_export import music_midi
from guitar_video_app.music.retime import (choose_grid, fit_tempo_map, restore_repeats, retime_lesson,
                                           suggest_grid, tidy_lesson, trim_leading_measures)
from guitar_video_app.music.tempo import beat as lesson_beat, seconds_at, tempo_map
from guitar_video_app.music.transcription_cleanup import clean_transcribed_midi

ROOT = Path(__file__).resolve().parents[2]
STORE = Path(os.environ.get('GUITAR_DASHBOARD_STORE', ROOT/'data/dashboard'))
STORE.mkdir(parents=True,exist_ok=True)
STATIC = ROOT/'guitar_video_app/ui'
TRANSFER_LOCK = threading.Lock()
BLENDER = Path(os.environ.get('GUITAR_BLENDER', '/Applications/Blender.app/Contents/MacOS/Blender'))
RENDER_SCENE = ROOT/'outputs/v4-vertical.blend'
PIANO_RENDER_SCENE = ROOT/'outputs/piano-vertical.blend'
PIANO_VISUAL_SCENE = ROOT/'outputs/piano-visual.blend'
RENDER_SCRIPT = ROOT/'scripts/render_lesson.py'
PIANO_VISUAL_SCRIPT = ROOT/'scripts/render_piano_visual.py'
# EEVEE particle renders take seconds per frame, so the 4 s test is a half-size draft.
PIANO_VISUAL_TEST_OPTIONS = ('--scale','50','--samples','32')
RENDER_FPS = 30
RENDER_TEST_SECONDS = 4
RENDER_LOCK = threading.Lock()
FRAME_LINE = re.compile(r'^Frame written:\s*(\d+)')
FRAME_RANGE_LINE = re.compile(r'^Frame range:\s*(\d+)-(\d+)')
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
    # Preferred index-finger fret for generated fingering; NULL is the automatic low-fret choice.
    if 'hand_position' not in columns:
        conn.execute('ALTER TABLE songs ADD COLUMN hand_position INTEGER')
    # Video look (guitar_style.STYLES); NULL is 'natural', the scene's own colors.
    if 'guitar_style' not in columns:
        conn.execute('ALTER TABLE songs ADD COLUMN guitar_style TEXT')
    # Piano scene for Send to Blender and renders: NULL is the lesson keyboard, 'visual' is PIANO_VISUAL with rising
    # notes and 'plumes' is PIANO_VISUAL with plumes.
    if 'piano_look' not in columns:
        conn.execute('ALTER TABLE songs ADD COLUMN piano_look TEXT')
    # The lesson fields before the last tab review (JSON), for Undo.
    if 'previous_state' not in columns:
        conn.execute('ALTER TABLE songs ADD COLUMN previous_state TEXT')
    # Instrument that plays the song (instruments.INSTRUMENTS); NULL is guitar.
    if 'instrument' not in columns:
        conn.execute('ALTER TABLE songs ADD COLUMN instrument TEXT')


def summary(lesson, source_format='v2'):
    """Library details of a V3 lesson; tracks counts the slots in use (the guitar's strings).
    A piano lesson adds how many notes each hand plays and where the hands came from."""
    music=lesson['music']
    if len(music.get('notes',[]))>5000:
        raise ValueError('This preview supports up to 5,000 notes per lesson.')
    played=check_lesson(lesson)
    rules=lesson_rules(lesson)
    slots={rules.slot(note) for note in played['notes']}
    details=dict(notes=len(played['notes']),bpm=music['tempo_bpm'],fps=played['fps'],
                 tempo_changes=len(played['tempo_map'])-1,
                 duration=float(seconds_at(played['tempo_map'],played['end'])),
                 measures=math.ceil(played['end']/played['measure']),signature=music['time_signature'],
                 music_layer=dict(format=source_format,tracks=len(slots),beats=float(played['end']),
                                  tempo_changes=len(played['tempo_map']),time_signature_changes=1,audio_offset=0))
    if active_instrument(lesson)=='piano':
        part=parts(lesson)[0][1]
        hands=collections.Counter(entry['hand'] for entry in part['notes'].values())
        details['piano']=dict(left=hands['left'],right=hands['right'],hands_from=part.get('hands_from','planned'),
                              chosen=sum(1 for entry in part['notes'].values() if entry.get('by')=='user'))
    return details


def song_instrument(row):
    return row.get('instrument') or 'guitar'


def read_lesson(path):
    """The stored lesson as V3; a V2 file is converted and is written as V3 on its next save."""
    return as_lesson(json.loads(Path(path).read_text(encoding='utf-8')))


def lesson_json(lesson):
    sync_parts(lesson)
    return json.dumps(lesson,indent=2)+'\n'


def write_lesson(path, lesson):
    Path(path).write_text(lesson_json(lesson),encoding='utf-8')


def guitar_part(lesson):
    if GUITAR not in lesson.get('parts',{}):
        raise HTTPException(400,'This lesson has no guitar part.')
    return lesson['parts'][GUITAR]


def write_guitar_view(identity, lesson):
    """The guitar view (V2) that Blender and the renderer read, beside the song's lesson."""
    try:
        view=guitar_view(lesson)
    except (KeyError,ValueError) as exc:
        raise HTTPException(400,f'This lesson cannot be drawn on the guitar: {exc}') from exc
    path=STORE/identity/'guitar_view.json'
    path.write_text(json.dumps(view,indent=2)+'\n',encoding='utf-8')
    return path,view


def write_piano_view(identity, lesson):
    """The piano view that the piano scene and the renderer read, beside the song's lesson."""
    if active_instrument(lesson)!='piano':
        raise HTTPException(400,'This lesson has no piano part; switch the song to piano first.')
    try:
        view=piano_view(lesson,parts(lesson)[0][0])
    except (KeyError,ValueError) as exc:
        raise HTTPException(400,f'This lesson cannot be drawn on the piano: {exc}') from exc
    path=STORE/identity/'piano_view.json'
    path.write_text(json.dumps(view,indent=2)+'\n',encoding='utf-8')
    return path,view


def write_view(identity, lesson, instrument):
    return write_piano_view(identity,lesson) if instrument=='piano' else write_guitar_view(identity,lesson)


def normalize_dashboard_json(content, instrument='guitar'):
    """The V3 lesson and summary of imported JSON. A lesson with parts brings its own instrument;
    normalized JSON and a lesson with no part are made for instrument."""
    data=json.loads(content)
    source_format='v3' if isinstance(data,dict) and data.get('version')==3 else 'v2'
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
        lesson=piano_lesson_from_normalized(data,fps=60) if instrument=='piano' else lesson_from_normalized(data,fps=60)
    else:
        lesson=as_lesson(data)
        if not lesson['parts']:
            activate(lesson,instrument)
    details=summary(lesson,'v3' if source_format=='v3' else 'v2')
    details['source_format']=source_format
    if normalized_layer:
        details['music_layer']=normalized_layer
    return lesson,details


def dashboard_music_layer(normalized):
    return dict(format='midi',
                tracks=len(normalized.get('tracks',[])),
                beats=len(normalized.get('beats',[])),
                measures=len(normalized.get('measures',[])),
                tempo_changes=len(normalized.get('timing',{}).get('tempo_changes',[])),
                time_signature_changes=len(normalized.get('timing',{}).get('time_signature_changes',[])),
                audio_offset=normalized.get('audio',{}).get('audio_offset',0))


def analyze_dashboard_midi(path, title, *, tolerate_unplayable=False, instrument='guitar'):
    """Normalized song JSON, lesson and summary of a MIDI file. Guitar maps every note to a string
    and fret (unplayable notes raise, or with tolerate_unplayable are left out); piano leaves out
    notes beyond its 88 keys and takes the hands from the MIDI tracks or plans them."""
    if instrument=='piano':
        normalized=analyze_midi_file(path,title=title)
    else:
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
        'pedal_events': normalized.pedal_events,
        'guitar': normalized.guitar,
    }))
    if instrument=='piano':
        lesson_data=piano_lesson_from_normalized(normalized_data,fps=60,name=title)
    else:
        lesson_data=lesson_from_normalized(normalized_data,fps=60,name=title,skip_unmapped=tolerate_unplayable)
    details=summary(lesson_data)
    details['source_format']='midi'
    details['music_layer']=dashboard_music_layer(normalized_data)
    if tolerate_unplayable or len(lesson_data['music']['notes'])<len(normalized_data.get('notes',[])):
        details['mapping_mode']='tolerant'
        details['music_layer']['mapped_notes']=len(lesson_data['music']['notes'])
        details['music_layer']['detected_notes']=len(normalized_data.get('notes',[]))
    return normalized_data,lesson_data,details


def store_midi_analysis(identity, midi_path, midi_name, title, *, tolerate_unplayable=False):
    row=song(identity)
    folder=STORE/identity
    normalized_data,lesson_data,details=analyze_dashboard_midi(midi_path,title,tolerate_unplayable=tolerate_unplayable,
                                                               instrument=song_instrument(row))
    lesson_path=folder/f'{uuid.uuid4().hex}.json'
    normalized_path=folder/f'{uuid.uuid4().hex}.normalized.json'
    write_lesson(lesson_path,lesson_data)
    normalized_path.write_text(json.dumps(normalized_data,indent=2)+'\n',encoding='utf-8')
    with db() as conn:
        conn.execute('UPDATE songs SET midi_path=?,midi_name=?,json_path=?,json_name=?,summary=?,revision=revision+1,updated=? WHERE id=?',
                     (str(midi_path),midi_name,str(lesson_path),lesson_path.name,json.dumps(details),time.time(),identity))
    return public(song(identity))


def auto_time_transcription(identity,onsets=()):
    """Fit tempo, downbeat and per-measure tempo changes to a fresh transcription, restore
    missed repeats from the model's onsets (audio seconds), then tidy it; notes keep their audio times."""
    row=song(identity)
    path=Path(row['json_path'])
    lesson=read_lesson(path)
    music,rules=lesson['music'],lesson_rules(lesson)
    tempos=tempo_map(music)
    bpm,first=suggest_grid([float(seconds_at(tempos,lesson_beat(n['start_beat']))) for n in music['notes']])
    zero=retime_lesson(music,bpm,first)
    grid=choose_grid(music)
    changes=fit_tempo_map(music,grid)
    restored=restore_repeats(music,[(time-float(zero),pitch,strength) for time,pitch,strength in onsets],grid,rules)
    stats=tidy_lesson(music,grid=grid,rules=rules)
    trim_to_last_measure(music)
    removed=trim_leading_measures(music)
    if active_instrument(lesson)=='piano':
        PIANO.assign(lesson,parts(lesson)[0][1])
    elif row.get('hand_position'):
        refinger_part(music,guitar_part(lesson),row['hand_position'])
    previous=row.get('summary') or {}
    details=dict(summary(lesson),source_format=previous.get('source_format'),music_layer=previous.get('music_layer'))
    write_lesson(path,lesson)
    with db() as conn:
        conn.execute('UPDATE songs SET summary=?,offset=?,synced_revision=NULL,revision=revision+1,updated=? WHERE id=?',
                     (json.dumps(details),round(-float(zero+removed),6),time.time(),identity))
    return dict(tempo_bpm=music['tempo_bpm'],tempo_changes=changes,restored=restored,**stats)


def song_transcription(row):
    """Basic Pitch onset peaks (audio seconds, pitch, strength) and cleaned notes (start, end,
    pitch) of the song's audio, transcribing the audio first when it has not been done yet."""
    folder=STORE/row['id']/'generated-midi'
    raw=folder/f"{Path(row['wav_path']).stem}_basic_pitch.mid"
    if not raw.exists() or not raw.with_suffix('.onsets.json').exists():
        raw=transcribe_wav_to_midi(row['wav_path'],folder)
    with tempfile.TemporaryDirectory() as scratch:
        cleaned=Path(scratch)/'clean.mid'
        clean_transcribed_midi(raw,cleaned)
        played=played_notes(cleaned)
    return json.loads(raw.with_suffix('.onsets.json').read_text(encoding='utf-8')),played


def import_tab(identity, content, name):
    """Make the song's lesson from a tab file fitted to its audio: tempo map and audio offset
    come from the audio, then notes move, are added or removed to match what is played; the
    tab supplies fingering. A song that already has a lesson is reviewed instead
    (review_with_tab): the tab's bars are replaced wherever the recording plays them and the
    other notes stay, re-fingered like the tab. The previous lesson is kept for Undo."""
    row=song(identity)
    if song_instrument(row)!='guitar':
        raise HTTPException(400,'Tab files are for guitar songs; switch the song to guitar first.')
    if not row['wav_path']:
        raise HTTPException(400,'Import the audio first; the tab is fitted to it.')
    try:
        tab=read_tab(json.loads(content))
    except (ValueError,TypeError) as exc:
        raise HTTPException(400,f'Invalid tab: {exc}') from exc
    review=fit=None
    try:
        onsets,played=song_transcription(row)
        if row['json_path']:
            current=read_lesson(row['json_path'])
            guitar_part(current)
            lesson_data,offset,review=review_with_tab(current,row['offset'],tab,onsets,played)
        else:
            lesson_data,fit=import_tab_to_audio(tab,onsets,played)
            offset=-fit['audio_start']
    except TranscriptionUnavailable as exc:
        raise HTTPException(501,str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400,f'Could not fit the tab to the audio: {exc}') from exc
    if abs(offset)>60:
        raise HTTPException(400,'The lesson would start more than 60 seconds away from the audio; trim the audio first.')
    folder=STORE/identity
    folder.mkdir(exist_ok=True)
    (folder/f'{uuid.uuid4().hex}.tab.json').write_bytes(content)
    lesson_path=folder/f'{uuid.uuid4().hex}.json'
    write_lesson(lesson_path,lesson_data)
    previous=row.get('summary') or {}
    if review:
        details=dict(summary(lesson_data),source_format=previous.get('source_format'),
                     music_layer=previous.get('music_layer'),tab_review=dict(review,tab=name))
        state=json.dumps({k:row[k] for k in ('json_path','json_name','summary','offset','hand_position','title','subtitle')})
    else:
        details,state=dict(summary(lesson_data),source_format='tab',tab_fit=fit),None
    title=tab.get('title',row['title'])
    subtitle=tab.get('artist',row['subtitle'])
    with db() as conn:
        conn.execute('''UPDATE songs SET json_path=?,json_name=?,summary=?,offset=?,title=?,subtitle=?,hand_position=NULL,
                        previous_state=?,synced_revision=NULL,revision=revision+1,updated=? WHERE id=?''',
                     (str(lesson_path),name,json.dumps(details),offset,title,subtitle,state,time.time(),identity))
    return dict(public(song(identity)),**({'tab_review':review} if review else {'tab_fit':fit}))


def song(identity):
    with db() as conn:
        row=conn.execute('SELECT * FROM songs WHERE id=?',(identity,)).fetchone()
    if not row:
        raise HTTPException(404,'Song not found')
    result=dict(row)
    result['summary']=json.loads(result['summary']) if result['summary'] else None
    return result


def public(row):
    result={k:v for k,v in row.items() if k not in ('json_path','wav_path','midi_path','previous_state')}
    result['can_undo_review']=bool(row.get('previous_state') and (row.get('summary') or {}).get('tab_review'))
    return result


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


def file_stem(name):
    """Song name usable as a file name."""
    stem=re.sub(r'[\x00-\x1f/\\:*?"<>|]+',' ',name)
    return re.sub(r'\s+',' ',stem).strip(' .')[:100] or 'Song'


def content_disposition_header(disposition, name):
    quoted=quote(name)
    return f"{disposition}; filename*=utf-8''{quoted}" if quoted!=name else f'{disposition}; filename="{name}"'


def render_path(folder, name, mode):
    """Video file named after the song; a number is added instead of replacing an earlier render."""
    stem=file_stem(name)
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
    start_beat: str | None = Field(default=None,max_length=40)
    duration_beats: str | None = Field(default=None,max_length=40)


class TabNoteNew(BaseModel):
    string: int = Field(ge=1,le=6)
    fret: int = Field(ge=0,le=20)
    start_beat: str = Field(max_length=40)
    duration_beats: str = Field(max_length=40)


class TabNotes(BaseModel):
    notes: list[dict] = Field(min_length=1)
    end_beat: str | None = Field(default=None,max_length=40)


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
    music=read_lesson(row['json_path'])['music']
    tempos=tempo_map(music)
    try:
        bpm,first=suggest_grid([float(seconds_at(tempos,lesson_beat(n['start_beat'])))-row['offset'] for n in music['notes']])
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
    lesson=read_lesson(path)
    try:
        zero=retime_lesson(lesson['music'],payload.tempo_bpm,payload.first_beat+row['offset'])
        details=summary(lesson)
    except ValueError as exc:
        raise HTTPException(400,f'Invalid timing: {exc}') from exc
    offset=round(row['offset']-float(zero),6)
    if abs(offset)>60:
        raise HTTPException(400,'The first beat is too far from the start of the audio.')
    previous=row.get('summary') or {}
    for field in ('source_format','music_layer','tab_fit'):
        if previous.get(field):
            details[field]=previous[field]
    write_lesson(path,lesson)
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
    lesson=read_lesson(path)
    try:
        stats=tidy_lesson(lesson['music'],snap=payload.snap,duplicates=payload.duplicates,lengths=payload.lengths,
                          rules=lesson_rules(lesson))
        details=summary(lesson)
    except ValueError as exc:
        raise HTTPException(400,f'Could not tidy notes: {exc}') from exc
    previous=row.get('summary') or {}
    for field in ('source_format','music_layer','tab_fit'):
        if previous.get(field):
            details[field]=previous[field]
    write_lesson(path,lesson)
    with db() as conn:
        conn.execute('UPDATE songs SET summary=?,synced_revision=NULL,revision=revision+1,updated=? WHERE id=?',
                     (json.dumps(details),time.time(),identity))
    return dict(public(song(identity)),tidy=stats)


class StyleInput(BaseModel):
    style: Literal['natural','black','white','red','blue']


@app.post('/api/songs/{identity}/style')
def update_style(identity: str,payload: StyleInput):
    """Guitar colors and background for Send to Blender and renders; the lesson is unchanged."""
    row=song(identity)
    style=None if payload.style=='natural' else payload.style
    if row.get('guitar_style')!=style:
        with db() as conn:
            conn.execute('UPDATE songs SET guitar_style=?,revision=revision+1,updated=? WHERE id=?',
                         (style,time.time(),identity))
    return public(song(identity))


class PianoLookInput(BaseModel):
    look: Literal['lesson','visual','plumes']


@app.post('/api/songs/{identity}/piano-look')
def update_piano_look(identity: str,payload: PianoLookInput):
    """Lesson keyboard, or the PIANO_VISUAL stage with rising notes ('visual') or plumes, for Send to Blender and
    renders; the lesson is unchanged."""
    row=song(identity)
    look=None if payload.look=='lesson' else payload.look
    if row.get('piano_look')!=look:
        with db() as conn:
            conn.execute('UPDATE songs SET piano_look=?,revision=revision+1,updated=? WHERE id=?',
                         (look,time.time(),identity))
    return public(song(identity))


def piano_visual(row):
    return song_instrument(row)=='piano' and row.get('piano_look') in ('visual','plumes')


def piano_effect(row):
    return 'plumes' if row.get('piano_look')=='plumes' else 'notes'


class FingeringInput(BaseModel):
    position: int | None = None


@app.post('/api/songs/{identity}/fingering')
def update_fingering(identity: str,payload: FingeringInput):
    """Re-plan strings and frets around a preferred hand position; kept for later generated lessons."""
    row=song(identity)
    if not row['json_path']:
        raise HTTPException(400,'Import or generate lesson JSON first')
    require_guitar(row)
    path=Path(row['json_path'])
    lesson=read_lesson(path)
    try:
        moved=refinger_part(lesson['music'],guitar_part(lesson),payload.position)
        details=summary(lesson)
    except ValueError as exc:
        raise HTTPException(400,f'Could not change the fingering: {exc}') from exc
    for field,value in (row.get('summary') or {}).items():
        if field in ('source_format','music_layer','tab_fit'):
            details[field]=value
    write_lesson(path,lesson)
    with db() as conn:
        conn.execute('UPDATE songs SET summary=?,hand_position=?,synced_revision=NULL,revision=revision+1,updated=? WHERE id=?',
                     (json.dumps(details),payload.position,time.time(),identity))
    return dict(public(song(identity)),moved=moved)


def require_guitar(row):
    if song_instrument(row)!='guitar':
        raise HTTPException(400,'This is for guitar songs; this song is played on the piano.')


def lesson_for_edit(identity, guitar=False):
    row=song(identity)
    if not row['json_path']:
        raise HTTPException(400,'Import or generate lesson JSON first')
    if guitar:
        require_guitar(row)
    return row,read_lesson(row['json_path'])


def edit_beat(value,name):
    try:
        position=lesson_beat(value)
    except ValueError as exc:
        raise HTTPException(400,f'{name} must be a number or fraction of beats.') from exc
    if position<0:
        raise HTTPException(400,f'{name} cannot be negative.')
    return str(position)


def save_edited_notes(row,lesson):
    """Validate and store a lesson after note edits; the lesson end moves to the bar line after
    a note that now ends past it. The import and review details of the summary are kept."""
    music=lesson['music']
    if not music.get('notes'):
        raise HTTPException(400,'A lesson needs at least one note.')
    extend_to_bar(music)
    try:
        check_lesson(lesson)
    except (ValueError,KeyError,TypeError) as exc:
        raise HTTPException(400,f'Invalid note edit: {exc}') from exc
    details=summary(lesson)
    for field,value in (row.get('summary') or {}).items():
        if field in ('source_format','music_layer','tab_fit','tab_review'):
            details[field]=value
    write_lesson(row['json_path'],lesson)
    with db() as conn:
        conn.execute('UPDATE songs SET summary=?,synced_revision=NULL,revision=revision+1,updated=? WHERE id=?',
                     (json.dumps(details),time.time(),row['id']))
    return public(song(row['id']))


@app.patch('/api/songs/{identity}/notes')
def update_note(identity: str,payload: TabNoteEdit):
    """Move a note to another string and fret (its pitch follows), and optionally in time."""
    row,lesson=lesson_for_edit(identity,guitar=True)
    guitar_part(lesson)
    note=next((n for n in lesson['music']['notes'] if str(n.get('id'))==payload.note_id),None)
    if note is None:
        raise HTTPException(404,'Note not found')
    set_position(lesson,note,payload.string,payload.fret)
    if payload.start_beat is not None:
        note['start_beat']=edit_beat(payload.start_beat,'Start beat')
    if payload.duration_beats is not None:
        note['duration_beats']=edit_beat(payload.duration_beats,'Length')
    return save_edited_notes(row,lesson)


@app.post('/api/songs/{identity}/notes')
def add_note(identity: str,payload: TabNoteNew):
    row,lesson=lesson_for_edit(identity,guitar=True)
    guitar_part(lesson)
    notes=lesson['music'].setdefault('notes',[])
    note=dict(id=new_note_id(notes,'e'),start_beat=edit_beat(payload.start_beat,'Start beat'),
              duration_beats=edit_beat(payload.duration_beats,'Length'))
    set_position(lesson,note,payload.string,payload.fret)
    notes.append(note)
    rules=lesson_rules(lesson)
    notes.sort(key=lambda n:(lesson_beat(n['start_beat']),rules.order(n)))
    return dict(save_edited_notes(row,lesson),note_id=note['id'])


@app.put('/api/songs/{identity}/notes')
def replace_notes(identity: str,payload: TabNotes):
    """Put back a whole note list (and lesson end) saved by the dashboard's note Undo / Redo;
    notes are guitar-view notes (id, string, fret, start_beat, duration_beats)."""
    row,lesson=lesson_for_edit(identity,guitar=True)
    guitar_part(lesson)
    keys=('id','string','fret','start_beat','duration_beats')
    if any(any(k not in n for k in keys) for n in payload.notes):
        raise HTTPException(400,'Every note needs id, string, fret, start_beat and duration_beats.')
    try:
        set_notes(lesson,[{k:n[k] for k in keys} for n in payload.notes])
    except (KeyError,TypeError) as exc:
        raise HTTPException(400,'Every note needs a string from 1 to 6 and a fret from 0 to 20.') from exc
    if payload.end_beat is not None:
        lesson['music']['end_beat']=edit_beat(payload.end_beat,'Lesson end')
    return save_edited_notes(row,lesson)


@app.delete('/api/songs/{identity}/notes/{note_id}')
def delete_note(identity: str,note_id: str):
    row,lesson=lesson_for_edit(identity)
    music=lesson['music']
    notes=[note for note in music.get('notes',[]) if str(note.get('id'))!=note_id]
    if len(notes)==len(music.get('notes',[])):
        raise HTTPException(404,'Note not found')
    music['notes']=notes
    return save_edited_notes(row,lesson)


class InstrumentInput(BaseModel):
    instrument: Literal['guitar','piano']


@app.post('/api/songs/{identity}/instrument')
def update_instrument(identity: str,payload: InstrumentInput):
    """Play the song on another instrument. The lesson keeps a part per instrument, so switching
    back finds the earlier strings and frets or hands; a new part is planned from the music."""
    row=song(identity)
    if song_instrument(row)==payload.instrument:
        return dict(public(row),changed=0)
    changed=0
    if row['json_path']:
        path=Path(row['json_path'])
        lesson=read_lesson(path)
        options={}
        if payload.instrument=='guitar':
            part=lesson['parts'].get(GUITAR,{})
            pitches={n['id']:n['pitch'] for n in lesson['music']['notes']}
            options=dict(position=row.get('hand_position'),
                         keep={i for i,p in part.get('positions',{}).items() if pitch_of(p['string'],p['fret'])==pitches.get(i)})
        try:
            changed=activate(lesson,payload.instrument,**options)
            details=summary(lesson)
        except (KeyError,ValueError) as exc:
            raise HTTPException(400,f'Could not switch to {payload.instrument}: {exc}') from exc
        for field,value in (row.get('summary') or {}).items():
            if field in ('source_format','music_layer','tab_fit','tab_review'):
                details[field]=value
        write_lesson(path,lesson)
        with db() as conn:
            conn.execute('UPDATE songs SET summary=? WHERE id=?',(json.dumps(details),identity))
    with db() as conn:
        conn.execute('UPDATE songs SET instrument=?,synced_revision=NULL,revision=revision+1,updated=? WHERE id=?',
                     (None if payload.instrument=='guitar' else payload.instrument,time.time(),identity))
    return dict(public(song(identity)),changed=changed)


def piano_lesson(identity):
    row,lesson=lesson_for_edit(identity)
    if song_instrument(row)!='piano' or active_instrument(lesson)!='piano':
        raise HTTPException(400,'This song is not played on the piano.')
    return row,lesson,parts(lesson)[0][1]


class HandInput(BaseModel):
    note_id: str = Field(min_length=1,max_length=80)
    hand: Literal['left','right']


@app.post('/api/songs/{identity}/hands')
def update_hand(identity: str,payload: HandInput):
    """Choose the hand of one piano note; planning the hands again keeps it."""
    row,lesson,_=piano_lesson(identity)
    note=next((n for n in lesson['music']['notes'] if str(n.get('id'))==payload.note_id),None)
    if note is None:
        raise HTTPException(404,'Note not found')
    set_hand(lesson,note,payload.hand,name=parts(lesson)[0][0])
    return save_edited_notes(row,lesson)


@app.post('/api/songs/{identity}/hands/plan')
def plan_song_hands(identity: str):
    """Plan the piano hands again; hands chosen in the dashboard or read from MIDI tracks stay."""
    row,lesson,part=piano_lesson(identity)
    try:
        changed=PIANO.assign(lesson,part)
    except ValueError as exc:
        raise HTTPException(400,f'Could not plan the hands: {exc}') from exc
    return dict(save_edited_notes(row,lesson),changed=changed)


@app.post('/api/songs/{identity}/review/undo')
def undo_review(identity: str):
    """Put back the lesson, offset, hand position and titles from before the last tab review;
    note edits made since the review are lost."""
    row=song(identity)
    if not public(row)['can_undo_review']:
        raise HTTPException(400,'There is no tab review to undo.')
    state=json.loads(row['previous_state'])
    if not state.get('json_path') or not Path(state['json_path']).exists():
        raise HTTPException(400,'The lesson from before the review is no longer stored.')
    with db() as conn:
        conn.execute('''UPDATE songs SET json_path=?,json_name=?,summary=?,offset=?,hand_position=?,title=?,subtitle=?,
                        previous_state=NULL,synced_revision=NULL,revision=revision+1,updated=? WHERE id=?''',
                     (state['json_path'],state['json_name'],json.dumps(state['summary']) if state['summary'] else None,
                      state['offset'],state['hand_position'],state['title'],state['subtitle'],time.time(),identity))
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
    row=song(identity)
    if kind not in ('midi','json','wav','tab'):
        raise HTTPException(400,'Expected MIDI, JSON, tab or audio')
    content=await file.read(256*1024*1024+1)
    if len(content)>256*1024*1024:
        raise HTTPException(413,'File exceeds 256 MB')
    if kind=='tab':
        return import_tab(identity,content,Path(file.filename or 'tab.json').name)
    if kind=='wav':
        if content[:4]!=b'RIFF':
            try:
                content=audio_to_wav(content,file.filename or 'audio.mp3')
            except ValueError as exc:
                raise HTTPException(400,f'Invalid audio: {exc}') from exc
        return store_audio(identity,content,Path(file.filename or 'audio.wav').name)
    instrument=song_instrument(row)
    try:
        if kind=='json':
            lesson_data,details=normalize_dashboard_json(content,instrument)
            instrument=active_instrument(lesson_data) or instrument
            content=lesson_json(lesson_data).encode()
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
        if instrument!=song_instrument(row):
            conn.execute('UPDATE songs SET instrument=? WHERE id=?',(None if instrument=='guitar' else instrument,identity))
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
        store_midi_analysis(identity,stored_path,f"{file_stem(row['name'])}.mid",Path(row['wav_name'] or stored_path.name).stem,tolerate_unplayable=True)
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
def lesson(identity: str, download: bool = False, part: str | None = None):
    """The V3 lesson, or with part the view of that instrument part (part=guitar: the V2 tab data)."""
    row=song(identity)
    if not row['json_path']:
        raise HTTPException(404,'No lesson')
    try:
        data=read_lesson(row['json_path'])
        body=part_view(data,part) if part else data
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    disposition='attachment' if download else 'inline'
    return Response(json.dumps(body,indent=2)+'\n',media_type='application/json',
                    headers={'Content-Disposition':content_disposition_header(disposition,row.get('json_name') or 'lesson.json')})


def lesson_midi(lesson, name):
    """The lesson's music cut off as its active part plays it, in that instrument's tracks and program
    (one track for guitar; right and left hand for piano)."""
    found=parts(lesson)
    if not found:
        return music_midi(lesson['music'],lesson['fps'],lesson_rules(lesson),((name,0,None),),0)
    _,part,instrument=found[0]
    return music_midi(lesson['music'],lesson['fps'],lesson_rules(lesson),instrument.midi_tracks(part,name),
                      instrument.midi_program)


@app.get('/api/songs/{identity}/midi')
def midi(identity: str, download: bool = False):
    """The lesson as one track on its beat grid and tempo map, so it matches the video."""
    row=song(identity)
    if not row['midi_path'] and not row['json_path']:
        raise HTTPException(404,'No MIDI')
    name=f"{file_stem(row['name'])}.mid"
    disposition='attachment' if download else 'inline'
    if not row['json_path']:
        return FileResponse(row['midi_path'],media_type='audio/midi',filename=name,content_disposition_type=disposition)
    try:
        midi_file=lesson_midi(read_lesson(row['json_path']),video_title(row)[0] or row['name'])
    except Exception as exc:
        raise HTTPException(400,f'This lesson cannot be written as MIDI: {exc}') from exc
    buffer=io.BytesIO()
    midi_file.save(file=buffer)
    return Response(buffer.getvalue(),media_type='audio/midi',
                    headers={'Content-Disposition':content_disposition_header(disposition,name)})


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
        lesson=read_lesson(row['json_path'])
        summary(lesson)
        instrument=song_instrument(row)
        view_path,_=write_view(identity,lesson,instrument)
        if not TRANSFER_LOCK.acquire(blocking=False):
            raise HTTPException(409,'Another transfer is in progress')
        title,subtitle=video_title(row)
        command=dict(command='dashboard_sync',json_path=str(view_path),wav_path=row['wav_path'],
                     song_id=identity,revision=row['revision'],offset_seconds=row['offset'],
                     title=title,subtitle=subtitle,style=row.get('guitar_style') or 'natural',timeout=60)
        if instrument!='guitar':
            command['instrument']=instrument
        if piano_visual(row):
            command['piano_look'],command['piano_effect']='visual',piano_effect(row)
        try:
            result=bridge(command)
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
        span=FRAME_RANGE_LINE.search(line)
        if span:
            job['frame_start'],job['frame_end']=int(span.group(1)),int(span.group(2))
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
    instrument=song_instrument(row)
    visual=piano_visual(row)
    scene=PIANO_VISUAL_SCENE if visual else PIANO_RENDER_SCENE if instrument=='piano' else RENDER_SCENE
    if not scene.exists():
        builder='make_piano_visual_scene.py' if visual else 'make_piano_scene.py'
        raise HTTPException(503,f'The {instrument} scene {scene.name} is missing; build it with scripts/{builder}.')
    view_path,view=write_view(identity,read_lesson(row['json_path']),instrument)
    prepare_view=prepare_piano_view if instrument=='piano' else prepare_guitar_view
    try:
        last=prepare_view(dict(view,fps=RENDER_FPS))['frame_end']
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
        if visual:
            # A full render runs until the last note has faded; the script reports that frame range.
            command=[str(BLENDER),'-b',str(scene),'--python-exit-code','1','--python',str(PIANO_VISUAL_SCRIPT),'--',
                     '--json',str(view_path),'--wav',row['wav_path'],'--offset',str(row['offset']),
                     '--out',str(output),'--fps',str(RENDER_FPS),'--start','0','--effect',piano_effect(row)]
            if payload.mode=='test':
                command+=['--end',str(end),*PIANO_VISUAL_TEST_OPTIONS]
        else:
            command=[str(BLENDER),'-b',str(scene),'--python-exit-code','1','--python',str(RENDER_SCRIPT),'--',
                     '--json',str(view_path),'--wav',row['wav_path'],'--offset',str(row['offset']),
                     '--out',str(output),'--fps',str(RENDER_FPS),'--start','0','--end',str(end),
                     f'--title={title}',f'--subtitle={subtitle}',f"--style={row.get('guitar_style') or 'natural'}"]
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
                      json.dumps(summary(as_lesson(json.loads(source.read_text())))),duration,time.time()))


seed()
app.mount('/static',StaticFiles(directory=STATIC),name='static')
