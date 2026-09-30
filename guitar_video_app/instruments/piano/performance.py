"""Deterministic seconds-based visual events, independent of Blender and cameras."""
from guitar_video_app.music.tempo import beat, seconds_at


def performance(data, prepared):
    tempos = prepared['tempo_map']
    pedals = []
    for event in data.get('pedal_events', []):
        if event.get('type', 'sustain') != 'sustain':
            continue
        start = beat(event['start_beat'])
        duration = beat(event['duration_beats'])
        if start < 0 or duration <= 0:
            raise ValueError('Pedal spans require nonnegative start and positive duration.')
        pedals.append(dict(start=float(seconds_at(tempos, start)),
                           end=float(seconds_at(tempos, start + duration)),
                           channel=event.get('channel')))
    pedals.sort(key=lambda e: e['start'])
    notes = []
    for note in prepared['notes']:
        start = float(seconds_at(tempos, note['start']))
        end = float(seconds_at(tempos, note['end']))
        sound_end = end
        for pedal in pedals:
            same_channel = (pedal['channel'] is None or note.get('channel') is None
                            or pedal['channel'] == note['channel'])
            if same_channel and pedal['start'] <= sound_end < pedal['end']:
                sound_end = pedal['end']
        notes.append(dict(id=note['id'], pitch=note['pitch'], hand=note.get('hand', 'unknown'),
                          start=start, end=end, sound_end=sound_end,
                          velocity=max(1, min(127, int(note.get('velocity', 80))))))
    return notes, pedals


def pedal_amount(pedals, now):
    amount = 0.0
    for event in pedals:
        start, end = event['start'], event['end']
        if start <= now < end:
            amount = max(amount, min(1.0, (now-start)/.06))
        elif end <= now < end+.09:
            amount = max(amount, 1-(now-end)/.09)
    return amount * amount * (3-2*amount)


def trail_state(note, now, speed=.42, linger=1.4):
    """Bottom, length and brightness; release detaches the bar, sustain softens it."""
    if now <= note['start'] or now >= note['sound_end'] + linger:
        return 0.0, 0.0, 0.0
    top = speed*(now-note['start'])
    bottom = speed*max(0.0, now-note['end'])
    held = now < note['end']
    brightness = .65 + .35*note['velocity']/127
    if not held:
        brightness *= .5
    if now > note['sound_end']:
        brightness *= max(0.0, 1-(now-note['sound_end'])/linger)
    return bottom, top-bottom, brightness
