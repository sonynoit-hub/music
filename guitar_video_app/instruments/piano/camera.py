"""Camera shots for the PIANO_VISUAL stage, planned in pure Python and evaluated by Blender.

A shot list is {"version": 1, "shots": [{"start_bar": 1, "camera": "hero", "move": "drift",
"transition": "cut"}, ...]}: shots are stored in bars (1 = the first bar of the lesson) and turned
into seconds through the lesson's tempo map when a path is built, so Blender's FPS only decides on
which frame a cut lands (the frame nearest the downbeat).

Cameras are placed in keyboard-frame metres (x along the keys from the keyboard's middle, y = 0 at
the front edge of the white keys and growing away from the player, z up from the white key tops).
Every camera but wide frames a focus on the keyboard and is pulled back until the keys and the
rising notes above them fit the 9:16 safe box: clear of the captions at the bottom, the buttons on
the right and the top edge. Wide is the presentation camera's framing.
"""
from __future__ import annotations

import bisect
import math

from guitar_video_app.instruments.piano.keyboard import OCTAVE_MM, WHITE_LENGTH_MM, WHITE_MM, WIDTH_MM, key_x_mm
from guitar_video_app.music.tempo import seconds_at

VERSION = 1
CAMERAS = ('wide', 'hero', 'along', 'high', 'close', 'side')
MOVES = ('static', 'push', 'drift', 'arc')
TRANSITIONS = ('cut', 'blend')
SHOT_FIELDS = ('start_bar', 'camera', 'move', 'transition')

OCTAVE = OCTAVE_MM / 1000
KEY_MID = WHITE_LENGTH_MM / 2000
KEY_DEPTH = WHITE_LENGTH_MM / 1000
HALF_KEYBOARD = WIDTH_MM / 2000
KEY_MARGIN = WHITE_MM / 2000 + 0.02       # m kept beyond the outermost sounding keys' centres

# 1080x1920 with Blender's default 36 mm sensor, which fits the image's longer side (the height).
ASPECT = 1080 / 1920
SENSOR_MM = 36.0
# Normalized image coordinates (0-1, y up) that stay clear of short-video overlays.
SAFE_BOX = dict(left=0.04, right=0.86, bottom=0.20, top=0.92)
RISE_SHOWN = 0.40                         # m of rising notes kept in frame above the keys
# Lens shift that centres the focus in the safe box rather than the image (shift is measured in
# sensor heights, image x in widths).
SHIFT_X = ((SAFE_BOX['left'] + SAFE_BOX['right']) / 2 - 0.5) * -ASPECT

BLEND_SECONDS = 0.75                      # shortest blend
BLEND_MAX = 2.0                           # longest blend; never more than a bar or half the shot
TURN_RATE = 40.0                          # degrees of view turn a blend covers per extra second
ZOOM_SECONDS = 1.2                        # extra blend seconds per unit of log zoom (distance and lens)
BLEND_TURN = 25.0                         # Auto blends only between views at most this many degrees apart
MIN_BARS, MIN_SECONDS, MAX_SECONDS = 2, 3.0, 10.0
LOOK_AHEAD = 1.5                          # s of coming notes the focus already leans towards
DEAD_ZONE = 0.25 * OCTAVE                 # m the notes' centre may stray before the focus moves
SETTLE_SHARE = 0.25                       # a moving focus stops once this share of the dead zone from the centre
SPEED_SHARE = 0.25                        # largest focus speed, in frame widths per second
EASE_SECONDS = 0.5                        # time for the focus to reach full speed or stop
FOLLOW_RATE = 1.5                         # 1/s, how fast the focus closes the gap beyond the dead zone
PUSH_SHARE = 0.10                         # a push starts this much farther away than it ends
ARC_DEGREES = 12.0
STEP = 1 / 30                             # s between samples of a drifting focus

WIDE_LOCATION = (-1.75, -2.35, 0.755)     # PianoVisual_PresentationCamera in keyboard-frame metres
WIDE_TARGET = (0.0, KEY_MID, 0.06)        # PianoVisual_Anchor_CameraTarget
WIDE_LENS, WIDE_SHIFT = 35.0, 0.12

# azimuth: degrees from straight in front, negative towards the bass end; elevation: degrees above
# the key tops; octaves: the keyboard span framed around the focus; lift: m the aim sits above it.
PRESETS = {
    'hero': dict(azimuth=-28.0, elevation=24.0, lens=40.0, shift=0.10, octaves=2.75, lift=0.10),
    'along': dict(azimuth=-62.0, elevation=13.0, lens=32.0, shift=0.08, octaves=3.0, lift=0.12),
    'high': dict(azimuth=-8.0, elevation=57.0, lens=45.0, shift=0.05, octaves=2.0, lift=0.05),
    'close': dict(azimuth=-22.0, elevation=20.0, lens=55.0, shift=0.10, octaves=1.1, lift=0.08),
    'side': dict(azimuth=82.0, elevation=5.0, lens=35.0, shift=0.12, octaves=0.6, lift=0.15),
}


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a):
    length = math.sqrt(_dot(a, a))
    return (a[0] / length, a[1] / length, a[2] / length)


def _lerp(a, b, share):
    return a + (b - a) * share


def ease(share: float) -> float:
    """0 to 1 with zero speed and zero acceleration at both ends, so moves glide in and out."""
    share = min(1.0, max(0.0, share))
    return share * share * share * (share * (6 * share - 15) + 10)


def key_x(pitch: int) -> float:
    """A key's centre along the keyboard in keyboard-frame metres."""
    return key_x_mm(pitch) / 1000 - HALF_KEYBOARD


def project(state: dict, point) -> tuple[float, float] | None:
    """Where a keyboard-frame point lands in the 9:16 image (0-1, y up), or None behind the camera."""
    location, target = state['location'], state['target']
    forward = _unit(_sub(target, location))
    right = _unit(_cross(forward, (0.0, 0.0, 1.0)))
    up = _cross(right, forward)
    offset = _sub(point, location)
    depth = _dot(offset, forward)
    if depth <= 1e-6:
        return None
    x_mm = state['lens'] * _dot(offset, right) / depth
    y_mm = state['lens'] * _dot(offset, up) / depth
    return (0.5 + x_mm / (SENSOR_MM * ASPECT) - state['shift_x'] / ASPECT,
            0.5 + y_mm / SENSOR_MM - state['shift_y'])


def inside(spot, box=SAFE_BOX) -> bool:
    return spot is not None and box['left'] <= spot[0] <= box['right'] and box['bottom'] <= spot[1] <= box['top']


def _direction(azimuth, elevation):
    a, e = math.radians(azimuth), math.radians(elevation)
    return (math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))


def _wide_view():
    offset = _sub(WIDE_LOCATION, WIDE_TARGET)
    distance = math.sqrt(_dot(offset, offset))
    azimuth = math.degrees(math.atan2(offset[0], -offset[1]))
    elevation = math.degrees(math.asin(offset[2] / distance))
    return azimuth, elevation, distance


def _state(camera, focus, azimuth, distance):
    if camera == 'wide':
        target, lens, shift, shift_x = WIDE_TARGET, WIDE_LENS, WIDE_SHIFT, 0.0
        elevation = _wide_view()[1]
    else:
        preset = PRESETS[camera]
        target = (focus, KEY_MID, preset['lift'])
        lens, shift, shift_x, elevation = preset['lens'], preset['shift'], SHIFT_X, preset['elevation']
    direction = _direction(azimuth, elevation)
    location = tuple(t + distance * d for t, d in zip(target, direction))
    return dict(location=location, target=target, lens=lens, shift_x=shift_x, shift_y=shift)


def framing_points(focus: float, width: float) -> list[tuple[float, float, float]]:
    """The keyboard corners of a width centred on focus and the rising notes above its ends."""
    points = []
    for x in (focus - width / 2, focus + width / 2):
        points += [(x, 0.0, 0.0), (x, KEY_DEPTH, 0.0), (x, KEY_MID, RISE_SHOWN)]
    return points


_DISTANCES = {}


def framing_distance(camera: str, width: float, azimuth: float | None = None) -> float:
    """The smallest distance from which the camera fits width of keyboard into the safe box."""
    azimuth = PRESETS[camera]['azimuth'] if azimuth is None else azimuth
    key = (camera, round(width, 4), round(azimuth, 3))
    if key not in _DISTANCES:
        points = framing_points(0.0, width)
        fits = lambda d: all(inside(project(_state(camera, 0.0, azimuth, d), p)) for p in points)
        near, far = 0.2, 12.0
        if fits(near):
            far = near
        for _ in range(40):
            middle = (near + far) / 2
            near, far = (near, middle) if fits(middle) else (middle, far)
        _DISTANCES[key] = far
    return _DISTANCES[key]


# Bars and validation

def bar_count(prepared: dict) -> int:
    return max(1, math.ceil(prepared['end'] / prepared['measure']))


def bar_seconds(prepared: dict, bar: int) -> float:
    """When a 1-based bar's downbeat sounds."""
    return float(seconds_at(prepared['tempo_map'], (bar - 1) * prepared['measure']))


def cut_seconds(prepared: dict, bar: int) -> float:
    """The downbeat moved onto the frame where the cut shows."""
    fps = prepared['fps']
    return round(bar_seconds(prepared, bar) * fps) / fps


def validate(plan: dict, prepared: dict) -> dict:
    """A checked copy of a shot list: known cameras, moves and transitions, bars rising from 1."""
    if not isinstance(plan, dict) or plan.get('version') != VERSION or set(plan) - {'version', 'shots'}:
        raise ValueError('Expected a version 1 shot list.')
    shots = plan.get('shots')
    if not isinstance(shots, list) or not shots:
        raise ValueError('A shot list needs at least one shot.')
    bars, checked = bar_count(prepared), []
    for number, shot in enumerate(shots, 1):
        if not isinstance(shot, dict) or set(shot) - set(SHOT_FIELDS):
            raise ValueError(f'Shot {number}: expected only {", ".join(SHOT_FIELDS)}.')
        start = shot.get('start_bar')
        if type(start) is not int or not 1 <= start <= bars:
            raise ValueError(f'Shot {number}: start_bar must be a bar from 1 to {bars}.')
        if checked and start <= checked[-1]['start_bar']:
            raise ValueError(f'Shot {number}: shots must start on rising bars.')
        if shot.get('camera') not in CAMERAS:
            raise ValueError(f'Shot {number}: camera must be one of {", ".join(CAMERAS)}.')
        move, transition = shot.get('move', 'static'), shot.get('transition', 'cut')
        if move not in MOVES:
            raise ValueError(f'Shot {number}: move must be one of {", ".join(MOVES)}.')
        if transition not in TRANSITIONS:
            raise ValueError(f'Shot {number}: transition must be one of {", ".join(TRANSITIONS)}.')
        checked.append(dict(start_bar=start, camera=shot['camera'], move=move,
                            transition='cut' if not checked else transition))
    if checked[0]['start_bar'] != 1:
        raise ValueError('The first shot must start at bar 1.')
    return dict(version=VERSION, shots=checked)


# Notes and focus

def timed_keys(prepared: dict) -> list[tuple[float, float, float]]:
    """(start seconds, end seconds, key x) of every note, by start."""
    tempos = prepared['tempo_map']
    return sorted((float(seconds_at(tempos, n['start'])), float(seconds_at(tempos, n['end'])), key_x(n['pitch']))
                  for n in prepared['notes'])


def _sounding(keys, start, end):
    return [x for s, e, x in keys if s < end and e > start]


def _centre(xs):
    return (min(xs) + max(xs)) / 2


def focus_path(keys, start, end, width, first=None):
    """Focus samples every STEP seconds from start to end: it leans LOOK_AHEAD seconds ahead to the
    middle of the notes, waits inside the dead zone, and eases to at most SPEED_SHARE widths/s."""
    top_speed = SPEED_SHARE * width
    accel = top_speed / EASE_SECONDS
    count = max(1, math.ceil((end - start) / STEP)) + 1
    xs = _sounding(keys, start, start + LOOK_AHEAD)
    focus = _centre(xs) if xs else (first if first is not None else 0.0)
    speed, path, moving = 0.0, [], False
    for i in range(count):
        t = start + i * STEP
        xs = _sounding(keys, t, t + LOOK_AHEAD)
        goal = _centre(xs) if xs else focus
        gap = goal - focus
        # Once the notes leave the dead zone the focus recentres on them, then rests again.
        moving = abs(gap) > (SETTLE_SHARE * DEAD_ZONE if moving else DEAD_ZONE)
        wanted = FOLLOW_RATE * gap if moving else 0.0
        wanted = max(-top_speed, min(top_speed, wanted))
        speed += max(-accel * STEP, min(accel * STEP, wanted - speed))
        path.append(focus)
        focus += speed * STEP
    return path


# The camera path

class _Shot:
    def __init__(self, shot, start, end, keys, previous_focus):
        self.camera, self.move, self.transition = shot['camera'], shot['move'], shot['transition']
        self.start, self.end = start, end
        if self.camera == 'wide':
            self.azimuth, _, self.distance = _wide_view()
            self.path, self.width = [0.0], None
            self._finish()
            return
        preset = PRESETS[self.camera]
        self.azimuth = preset['azimuth']
        base = preset['octaves'] * OCTAVE
        xs = _sounding(keys, start, end)
        if self.move == 'drift':
            self.path = focus_path(keys, start, end + BLEND_MAX, base, previous_focus)
            reach = 0.0
            for i, focus in enumerate(self.path):
                t = start + i * STEP
                near = _sounding(keys, t, t + STEP)
                if near and t < end:
                    reach = max(reach, max(abs(x - focus) for x in near))
            needed = 2 * (reach + KEY_MARGIN) if reach else 0.0
        else:
            focus = _centre(xs) if xs else (previous_focus if previous_focus is not None else 0.0)
            self.path = [focus]
            needed = max(xs) - min(xs) + 2 * KEY_MARGIN if xs else 0.0
        self.width = max(base, needed)
        sweep = (-ARC_DEGREES / 2, 0.0, ARC_DEGREES / 2) if self.move == 'arc' else (0.0,)
        self.distance = max(framing_distance(self.camera, self.width, self.azimuth + a) for a in sweep)
        self._finish()

    def _finish(self):
        self.last_focus = self.path[-1]

    def focus(self, t):
        if len(self.path) == 1:
            return self.path[0]
        place = max(0.0, (t - self.start) / STEP)
        i = min(int(place), len(self.path) - 2)
        return _lerp(self.path[i], self.path[i + 1], min(1.0, place - i))

    def state(self, t):
        share = ease((t - self.start) / max(1e-6, self.end - self.start))
        azimuth, distance = self.azimuth, self.distance
        if self.move == 'push':
            distance *= 1 + PUSH_SHARE * (1 - share)
        elif self.move == 'arc':
            azimuth += _lerp(-ARC_DEGREES / 2, ARC_DEGREES / 2, share)
        return _state(self.camera, self.focus(t), azimuth, distance)


def _polar(state):
    """Azimuth and elevation (radians) and distance of the camera around its target."""
    offset = _sub(state['location'], state['target'])
    distance = math.sqrt(_dot(offset, offset))
    return math.atan2(offset[0], -offset[1]), math.asin(offset[2] / distance), distance


def _turn(a, b):
    return (b - a + math.pi) % (2 * math.pi) - math.pi


def blend_length(a: dict, b: dict, limit: float) -> float:
    """Seconds to blend from camera state a to b: longer for bigger turns and zooms, at most limit."""
    (az0, el0, d0), (az1, el1, d1) = _polar(a), _polar(b)
    turn = math.degrees(abs(_turn(az0, az1)) + abs(el1 - el0))
    zoom = abs(math.log(d1 / d0)) + abs(math.log(b['lens'] / a['lens']))
    wanted = BLEND_SECONDS + turn / TURN_RATE + zoom * ZOOM_SECONDS
    return max(BLEND_SECONDS, min(wanted, BLEND_MAX, limit))


def _mix(a, b, share):
    """Orbit from state a to b: the target slides, the camera swings around it and zooms evenly."""
    (az0, el0, d0), (az1, el1, d1) = _polar(a), _polar(b)
    target = tuple(_lerp(x, y, share) for x, y in zip(a['target'], b['target']))
    azimuth, elevation = az0 + _turn(az0, az1) * share, _lerp(el0, el1, share)
    distance = math.exp(_lerp(math.log(d0), math.log(d1), share))
    direction = (math.sin(azimuth) * math.cos(elevation), -math.cos(azimuth) * math.cos(elevation), math.sin(elevation))
    return dict(location=tuple(t + distance * d for t, d in zip(target, direction)), target=target,
                lens=_lerp(a['lens'], b['lens'], share), shift_x=_lerp(a['shift_x'], b['shift_x'], share),
                shift_y=_lerp(a['shift_y'], b['shift_y'], share))


class CameraPath:
    """camera_at(seconds) for a validated shot list over a prepared piano view."""

    def __init__(self, prepared: dict, plan: dict):
        self.plan = validate(plan, prepared)
        self.fps = prepared['fps']
        keys = timed_keys(prepared)
        song_end = float(seconds_at(prepared['tempo_map'], prepared['end']))
        shots = self.plan['shots']
        cuts = [cut_seconds(prepared, s['start_bar']) for s in shots] + [max(song_end, 1e-3)]
        self.cuts, self.shots, focus = cuts[:-1], [], None
        for shot, start, end in zip(shots, cuts, cuts[1:]):
            self.shots.append(_Shot(shot, start, max(end, start + STEP), keys, focus))
            focus = self.shots[-1].last_focus if self.shots[-1].camera != 'wide' else focus
        self.blends = [0.0] * len(self.shots)
        for i, (shot, entry) in enumerate(zip(self.shots, shots)):
            if i and shot.transition == 'blend':
                bar = bar_seconds(prepared, entry['start_bar'] + 1) - bar_seconds(prepared, entry['start_bar'])
                limit = min(bar, (shot.end - shot.start) / 2)
                self.blends[i] = blend_length(self.shots[i - 1].state(shot.start), shot.state(shot.start), limit)

    def shot_index(self, seconds: float) -> int:
        return max(0, bisect.bisect_right(self.cuts, seconds + 1e-9) - 1)

    def blending(self, seconds: float) -> bool:
        i = self.shot_index(seconds)
        return seconds < self.shots[i].start + self.blends[i]

    def camera_at(self, seconds: float) -> dict:
        """location and target (keyboard-frame metres), lens (mm), shift_x and shift_y of the shot camera."""
        i = self.shot_index(seconds)
        shot = self.shots[i]
        state = shot.state(seconds)
        if seconds < shot.start + self.blends[i]:
            state = _mix(self.shots[i - 1].state(seconds), state, ease((seconds - shot.start) / self.blends[i]))
        return state

    def frame_state(self, frame: int) -> dict:
        return self.camera_at(frame / self.fps)


def camera_path(prepared: dict, plan: dict) -> CameraPath:
    return CameraPath(prepared, plan)


# The Auto director

TARGET_SECONDS = 6.0
DENSE_RATE, SPARSE_RATE = 4.0, 1.5        # note starts per second
SUSTAINED_SECONDS = 1.2                   # average sounding length of a sustained passage
SIDE_GAP = 30.0                           # s between two side shots
CHOICES = {
    'wide': ('wide', 'hero'),
    'dense': ('hero', 'wide'),
    'medium': ('hero', 'along', 'high'),
    'sparse': ('close', 'along', 'high'),
}
MOVE_FOR = dict(wide='static', hero='drift', along='drift', high='drift', close='push', side='push')


def view_turn(a: str, b: str) -> float:
    """Degrees of azimuth plus elevation between two cameras' views."""
    angles = lambda c: _wide_view()[:2] if c == 'wide' else (PRESETS[c]['azimuth'], PRESETS[c]['elevation'])
    (az0, el0), (az1, el1) = angles(a), angles(b)
    return abs(az1 - az0) + abs(el1 - el0)


def _bars_between(starts, first, last):
    return starts[last - 1] - starts[first - 1]


def _shortest(starts, first, limit):
    """Bars a shot from bar first needs for MIN_BARS and MIN_SECONDS, never past bar limit."""
    count = MIN_BARS
    while first + count < limit and _bars_between(starts, first, first + count) < MIN_SECONDS:
        count += 1
    return min(count, limit - first)


def _features(keys, start, end):
    xs = _sounding(keys, start, end)
    onsets = [k for k in keys if start <= k[0] < end]
    held = [min(e, end) - max(s, start) for s, e, _ in keys if s < end and e > start]
    return dict(centre=_centre(xs) if xs else None, span=max(xs) - min(xs) if xs else 0.0,
                rate=len(onsets) / max(1e-6, end - start), held=sum(held) / len(held) if held else 0.0)


def _boundaries(prepared, keys):
    """Shot start bars: an opening of about two bars, shots of TARGET_SECONDS cut early where the music jumps
    more than an octave, and an ending that holds the last two bars or more."""
    bars = bar_count(prepared)
    starts = [bar_seconds(prepared, b) for b in range(1, bars + 1)]
    starts.append(float(seconds_at(prepared['tempo_map'], prepared['end'])))
    limit = bars + 1
    ending = limit - MIN_BARS
    while ending > 1 and _bars_between(starts, ending, limit) < MIN_SECONDS:
        ending -= 1
    opening = 1 + _shortest(starts, 1, limit)
    if ending < opening:
        return [1], starts
    if ending > opening and (ending - opening < MIN_BARS or _bars_between(starts, opening, ending) < MIN_SECONDS):
        opening = ending
    centres = [_features(keys, starts[b - 1], starts[b])['centre'] for b in range(1, limit)]
    jumps = {b for b in range(2, limit) if centres[b - 1] is not None and centres[b - 2] is not None
             and abs(centres[b - 1] - centres[b - 2]) > OCTAVE}
    cuts, bar = [1], opening
    while bar < ending:
        count = _shortest(starts, bar, ending)
        longest = count
        while bar + longest < ending and _bars_between(starts, bar, bar + longest + 1) <= MAX_SECONDS:
            longest += 1
        jump = next((n for n in range(count, longest + 1) if bar + n in jumps), None)
        if jump is not None:
            count = jump
        else:
            while count < longest and _bars_between(starts, bar, bar + count) < TARGET_SECONDS:
                count += 1
        rest = ending - (bar + count)
        if rest and (rest < MIN_BARS or _bars_between(starts, bar + count, ending) < MIN_SECONDS):
            count += rest
        cuts.append(bar)
        bar += count
    cuts.append(ending)
    return cuts, starts


def auto_shots(prepared: dict) -> dict:
    """Suggested shots for a prepared piano view; the same view always gets the same shots."""
    keys = timed_keys(prepared)
    cuts, starts = _boundaries(prepared, keys)
    ends = cuts[1:] + [len(starts)]
    shots, previous, used, last_side = [], None, {}, -math.inf
    for i, (first, after) in enumerate(zip(cuts, ends)):
        start, end = starts[first - 1], starts[after - 1]
        look = _features(keys, start, end)
        if i == len(cuts) - 1 and i:
            camera, move = 'wide', 'static'
        elif i == 0:
            fits = look['span'] + 2 * KEY_MARGIN <= PRESETS['hero']['octaves'] * OCTAVE
            camera = 'hero' if fits or len(cuts) == 2 else 'wide'
            move = 'push'
        else:
            if look['span'] > 4.5 * OCTAVE:
                mood = 'wide'
            elif look['rate'] >= DENSE_RATE or look['span'] > 3 * OCTAVE:
                mood = 'dense'
            elif look['rate'] < SPARSE_RATE or look['held'] >= SUSTAINED_SECONDS:
                mood = 'sparse'
            else:
                mood = 'medium'
            options = list(CHOICES[mood])
            turn = used.get(mood, 0)
            options = options[turn % len(options):] + options[:turn % len(options)]
            if mood == 'sparse' and start - last_side >= SIDE_GAP and look['span'] <= OCTAVE:
                options.insert(0, 'side')
            if i == len(cuts) - 2:
                options = [o for o in options if o != 'wide'] or ['hero']
            camera = next(o for o in options + ['hero', 'high'] if o != previous)
            used[mood] = turn + 1
            move = 'arc' if camera == 'high' and mood == 'sparse' else MOVE_FOR[camera]
        if camera == 'side':
            last_side = start
        transition = 'cut'
        close_views = i and view_turn(previous, camera) <= BLEND_TURN
        if close_views and i == len(cuts) - 1:
            transition = 'blend'
        elif close_views and look['centre'] is not None and shots[-1]['centre'] is not None \
                and abs(look['centre'] - shots[-1]['centre']) <= OCTAVE / 2:
            transition = 'blend'
        shots.append(dict(start_bar=first, camera=camera, move=move, transition=transition if i else 'cut',
                          centre=look['centre']))
        previous = camera
    return dict(version=VERSION, shots=[{k: s[k] for k in SHOT_FIELDS} for s in shots])
