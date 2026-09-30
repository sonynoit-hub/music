"""Validated lesson/audio transfer on Blender's main thread."""
import json
import math
import hashlib
from pathlib import Path
import wave


def status():
    import bpy
    scene = bpy.context.scene
    names = ['LessonVerticalCamera','App_Tab_White_Panel','Backdrop','Nut']
    names += [f'String_{i}' for i in range(1,7)] + [f'Lesson_Tab_Line_{i}' for i in range(1,7)]
    matrices = {n:[list(row) for row in bpy.data.objects[n].matrix_world] for n in names if n in bpy.data.objects}
    return dict(ok=True, scene=scene.name, file=bpy.data.filepath,
                camera=scene.camera.name if scene.camera else None,
                frame=scene.frame_current, song_id=scene.get('Dashboard_Song_ID'),
                revision=scene.get('Dashboard_Revision'),
                layout_fingerprint=hashlib.sha256(json.dumps(matrices,sort_keys=True).encode()).hexdigest(),
                audio_strips=len([s for s in scene.sequence_editor.strips if s.name.startswith('Lesson_JSON_Guitar_Audio')]) if scene.sequence_editor else 0,
                markers=len([o for o in bpy.data.objects if o.name.startswith('Lesson_V2_Marker_')]))


def _piano_look(command):
    """Scene check, loader, install and undo for the song's piano look: the lesson keyboard or PIANO_VISUAL with
    rising notes or plumes."""
    if command.get('piano_look') == 'visual':
        import bpy
        from guitar_video_app.integrations import piano_visual_particles as visual
        from guitar_video_app.integrations.piano_visual import FRAME_OBJECT
        effect = command.get('piano_effect', 'notes')
        previous = bpy.context.scene.get(visual.EFFECT_PROPERTY, 'notes')
        return dict(anchor=FRAME_OBJECT, scene_file='outputs/piano-visual.blend (PIANO_VISUAL)',
                    text=visual.TEXT, loader=visual.LOADER, install=lambda data: visual.install(data, effect=effect),
                    clear=visual.uninstall, restore=lambda data: visual.install(data, effect=previous))
    from guitar_video_app.integrations.piano_lesson import LOADER, TEXT, install_piano
    from guitar_video_app.integrations.piano_scene import KEYBOARD
    from guitar_video_app.integrations.title_overlay import install_title

    def install(data):
        install_piano(data)
        install_title(command.get('title', ''), command.get('subtitle', ''), anchor=KEYBOARD)
    return dict(anchor=KEYBOARD, scene_file='the piano scene (outputs/piano-vertical.blend)', text=TEXT,
                loader=LOADER, install=install, clear=lambda: None, restore=install_piano)


def sync_piano(command):
    """Install a piano view and its audio in the open piano scene of the song's look; the previous lesson comes
    back on failure."""
    import bpy
    from guitar_video_app.instruments.piano.view import prepare

    look = _piano_look(command)
    scene = bpy.context.scene
    data = json.loads(Path(command['json_path']).read_text())
    lesson = prepare(data)
    audio = Path(command['wav_path']).resolve(strict=True)
    offset = float(command.get('offset_seconds', 0))
    if not math.isfinite(offset) or abs(offset) > 60:
        raise ValueError('Audio offset must be between -60 and 60 seconds.')
    with wave.open(str(audio)) as wav:
        if wav.getnframes() == 0:
            raise ValueError('The WAV file is empty.')
    if look['anchor'] not in scene.objects:
        raise ValueError(f"Open {look['scene_file']} first.")
    previous = bpy.data.texts.get(look['text'])
    previous_data = json.loads(previous.as_string()) if previous else None
    frame = scene.frame_current
    timing = (scene.frame_start, scene.frame_end, scene.render.fps, scene.render.fps_base)
    editor = scene.sequence_editor_create()
    old_audio = [s for s in editor.strips if s.name.startswith('Lesson_JSON_Guitar_Audio')]
    channel = max(s.channel for s in old_audio) if old_audio else max((s.channel for s in editor.strips), default=0) + 1
    new_audio = None
    try:
        new_audio = editor.strips.new_sound('Dashboard_Audio_Pending', str(audio), channel=channel,
                                            frame_start=round(offset * lesson['fps']))
        new_audio.mute = True
        look['install'](data)
        scene.frame_set(0)
    except Exception:
        if new_audio:
            editor.strips.remove(new_audio)
        if previous_data:
            look.get('restore', look['install'])(previous_data)
        else:
            look['clear']()
        scene.frame_start, scene.frame_end, scene.render.fps, scene.render.fps_base = timing
        scene.frame_set(frame)
        raise
    for strip in old_audio:
        editor.strips.remove(strip)
    new_audio.name = 'Lesson_JSON_Guitar_Audio'
    new_audio.mute = False
    new_audio.volume = 1
    scene['Dashboard_Song_ID'] = command['song_id']
    scene['Dashboard_Revision'] = command['revision']
    loader = bpy.data.texts.get(look['loader'])
    if loader:
        loader.write('\nfrom guitar_video_app.integrations.blender_bridge_server import start_bridge\nstart_bridge()\n')
    return dict(ok=True, frame_start=0, frame_end=scene.frame_end,
                audio_start=new_audio.frame_final_start, note_count=len(lesson['notes']),
                revision=command['revision'], saved=False)


def sync(command):
    import bpy
    from guitar_video_app.instruments import as_lesson

    if command.get('instrument') == 'piano':
        return sync_piano(command)
    from guitar_video_app.instruments.guitar.view import guitar_view, prepare
    from guitar_video_app.integrations.lesson_setup import install_v2
    from guitar_video_app.integrations.guitar_style import install_style
    from guitar_video_app.integrations.title_overlay import install_title

    scene = bpy.context.scene
    data = json.loads(Path(command['json_path']).read_text())
    if data.get('version') != 2:
        data = guitar_view(as_lesson(data))
    lesson = prepare(data)
    audio = Path(command['wav_path']).resolve(strict=True)
    offset = float(command.get('offset_seconds', 0))
    if not math.isfinite(offset) or abs(offset) > 60:
        raise ValueError('Audio offset must be between -60 and 60 seconds.')
    with wave.open(str(audio)) as wav:
        if wav.getnframes() == 0:
            raise ValueError('The WAV file is empty.')
    required = ['App_Tab_White_Panel','App_Tab_Cursor_Visible_6_String_Length',
                'App_Tab_Backdrop_Panel_Cursor_Lines_GROUP','Nut']
    required += [f'String_{i}' for i in range(1,7)]
    required += [f'Lesson_Tab_Line_{i}' for i in range(1,7)]
    required += [f'Fret_{i:02d}' for i in range(1,21)]
    missing = [n for n in required if n not in scene.objects]
    if missing or scene.camera is None:
        raise ValueError('Open the guitar lesson scene first. Missing: ' + ', '.join(missing))
    if 'App_Tab_Backdrop_Panel_Cursor_Lines_COLLECTION' not in bpy.data.collections:
        raise ValueError('The tab collection is missing.')
    for i in range(1,7):
        obj = bpy.data.objects[f'String_{i}']
        if obj.animation_data and obj.animation_data.action:
            raise ValueError('Legacy string actions are still attached.')
    previous = bpy.data.texts.get('Lesson_V2_JSON')
    previous_data = json.loads(previous.as_string()) if previous else None
    frame = scene.frame_current
    timing = (scene.frame_start,scene.frame_end,scene.render.fps,scene.render.fps_base)
    editor = scene.sequence_editor_create()
    old_audio = [s for s in editor.strips if s.name.startswith('Lesson_JSON_Guitar_Audio')]
    channel = max((s.channel for s in editor.strips),default=0)+1
    if old_audio:
        channel = max(s.channel for s in old_audio)
    new_audio = None
    try:
        new_audio = editor.strips.new_sound('Dashboard_Audio_Pending',str(audio),channel=channel,
                                            frame_start=round(offset*lesson['fps']))
        new_audio.mute = True
        install_v2(data)
        install_title(command.get('title', ''), command.get('subtitle', ''))
        install_style(command.get('style') or 'natural')
        scene.frame_set(0)
    except Exception:
        if new_audio:
            editor.strips.remove(new_audio)
        if previous_data:
            install_v2(previous_data)
        scene.frame_start,scene.frame_end,scene.render.fps,scene.render.fps_base = timing
        scene.frame_set(frame)
        raise
    for strip in old_audio:
        editor.strips.remove(strip)
    new_audio.name = 'Lesson_JSON_Guitar_Audio'
    new_audio.mute = False
    new_audio.volume = 1
    scene['Dashboard_Song_ID'] = command['song_id']
    scene['Dashboard_Revision'] = command['revision']
    loader = bpy.data.texts.get('Demo_16_Note_Tab_Controller.py')
    if loader:
        loader.write('\nfrom guitar_video_app.integrations.blender_bridge_server import start_bridge\nstart_bridge()\n')
    return dict(ok=True, frame_start=0, frame_end=scene.frame_end,
                audio_start=new_audio.frame_final_start, note_count=len(lesson['notes']),
                revision=command['revision'], saved=False)
