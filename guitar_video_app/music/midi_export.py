"""Export a lesson's music as MIDI with the exact same note cutoffs as Blender playback."""
from fractions import Fraction

from guitar_video_app.music.lesson import prepare
from guitar_video_app.music.rules import PitchRules

TICKS_PER_BEAT = 960
VELOCITY = 85


def _note_track(name, channel, program, notes, end_tick):
    """One track from (start_tick, end_tick, pitch); a same-pitch note ends where the next one starts."""
    import mido

    track = mido.MidiTrack()
    track.append(mido.MetaMessage('track_name', name=name))
    track.append(mido.Message('program_change', channel=channel, program=program))
    spans = {}
    for start, end, pitch in sorted(notes):
        previous = spans.setdefault(pitch, [])
        if previous and previous[-1][0] == start:
            previous[-1][1] = max(previous[-1][1], end)
            continue
        if previous and previous[-1][1] > start:
            previous[-1][1] = start
        previous.append([start, end])
    events = [(tick, on, pitch) for pitch, items in spans.items()
              for start, end in items for tick, on in ((start, 1), (end, 0))]
    last = 0
    for tick, on, pitch in sorted(events):
        track.append(mido.Message('note_on' if on else 'note_off', channel=channel,
                                  note=pitch, velocity=VELOCITY if on else 0, time=tick-last))
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
    notes = [(tick(n['start']), tick(n['end']), n['pitch'], n) for n in lesson['notes']]
    for name, channel, slot in tracks:
        chosen = (lambda n: True) if slot is None else slot if callable(slot) else (lambda n: rules.slot(n) == slot)
        midi.tracks.append(_note_track(name, channel, program, [n[:3] for n in notes if chosen(n[3])], end_tick))
    return midi
