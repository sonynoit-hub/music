"""Export a lesson's music as MIDI with the exact same note cutoffs as Blender playback."""
from fractions import Fraction

from guitar_video_app.music.lesson import prepare
from guitar_video_app.music.rules import PitchRules
from guitar_video_app.music.tempo import beat_at, seconds_at

TICKS_PER_BEAT = 960
VELOCITY = 85
# A muted (dead) note is a short, soft click of its string.
MUTED_SECONDS = 0.05
MUTED_VELOCITY = 50


def muted_end(tempos, note):
    """Where a muted note stops sounding (beats): MUTED_SECONDS after its start, or its end if sooner."""
    return min(note['end'], beat_at(tempos, seconds_at(tempos, note['start']) + MUTED_SECONDS))


def _note_track(name, channel, program, notes, end_tick):
    """One track from (start_tick, end_tick, pitch, velocity); a same-pitch note ends where the next one starts."""
    import mido

    track = mido.MidiTrack()
    track.append(mido.MetaMessage('track_name', name=name))
    track.append(mido.Message('program_change', channel=channel, program=program))
    spans = {}
    for start, end, pitch, velocity in sorted(notes):
        previous = spans.setdefault(pitch, [])
        if previous and previous[-1][0] == start:
            previous[-1][1] = max(previous[-1][1], end)
            continue
        if previous and previous[-1][1] > start:
            previous[-1][1] = start
        previous.append([start, end, velocity])
    events = [(tick, on, pitch, velocity) for pitch, items in spans.items()
              for start, end, velocity in items for tick, on in ((start, 1), (end, 0))]
    last = 0
    for tick, on, pitch, velocity in sorted(events):
        track.append(mido.Message('note_on' if on else 'note_off', channel=channel,
                                  note=pitch, velocity=velocity if on else 0, time=tick-last))
        last = tick
    track.append(mido.MetaMessage('end_of_track', time=max(0, end_tick-last)))
    return track


def music_midi(music, fps, rules=None, tracks=(('Music', 0, None),), program=0):
    """MIDI of a music layer on its beat grid and tempo map. Notes are cut off as in playback
    (music.lesson.prepare with rules). tracks are (name, channel, slot): a track holds the notes
    whose rules.slot is slot, the notes for which slot(note) is true when slot is callable, or
    every note when slot is None."""
    import mido

    rules = rules or PitchRules()
    lesson = prepare(music, fps, rules)
    midi = mido.MidiFile(type=1, ticks_per_beat=TICKS_PER_BEAT)
    tick = lambda position: round(position * TICKS_PER_BEAT)
    end_tick = tick(lesson['end'])
    conductor = mido.MidiTrack()
    midi.tracks.append(conductor)
    conductor.append(mido.MetaMessage('time_signature', numerator=music['time_signature'][0], denominator=music['time_signature'][1]))
    last = 0
    for position, _, bpm in lesson['tempo_map']:
        conductor.append(mido.MetaMessage('set_tempo', tempo=round(Fraction(60000000) / bpm), time=tick(position) - last))
        last = tick(position)
    conductor.append(mido.MetaMessage('end_of_track', time=max(0, end_tick - last)))
    notes = [(tick(n['start']), tick(muted_end(lesson['tempo_map'], n)), n['pitch'], MUTED_VELOCITY, n) if n.get('muted')
             else (tick(n['start']), tick(n['end']), n['pitch'], VELOCITY, n) for n in lesson['notes']]
    for name, channel, slot in tracks:
        chosen = (lambda n: True) if slot is None else slot if callable(slot) else (lambda n: rules.slot(n) == slot)
        midi.tracks.append(_note_track(name, channel, program, [n[:4] for n in notes if chosen(n[4])], end_tick))
    return midi
