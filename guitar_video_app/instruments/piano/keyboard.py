"""88-key piano keyboard geometry in millimetres, shared by the piano view and the Blender scene.

x is measured from the left edge of the lowest key (A0) along the keyboard. Every octave spans
OCTAVE_MM: seven white keys of equal width at the front, and twelve keys of equal width at the back,
so a black key's center sits at (pitch class + 0.5) twelfths of its octave. That places the black
keys off center between their white neighbours the way real keyboards do.
"""
from __future__ import annotations

LOW = 21    # A0
HIGH = 108  # C8
MIDDLE_C = 60
OCTAVE_MM = 164.5
WHITE_MM = OCTAVE_MM / 7          # 23.5, front width of a white key
BLACK_MM = OCTAVE_MM / 12         # 13.7, back width of every key; a black key's width at its base
WHITE_LENGTH_MM = 150.0           # visible length of a white key
BLACK_LENGTH_MM = 95.0            # visible length of a black key, flush with the white keys at the back
BLACK_HEIGHT_MM = 12.0            # black key top above the white key tops
PRESS_MM = 10.0                   # how far the front of a white key goes down

_WHITE_INDEX = {0: 0, 2: 1, 4: 2, 5: 3, 7: 4, 9: 5, 11: 6}
# Left edge of A0 measured from the C below it (A is the sixth white key of its octave).
_A0_OFFSET_MM = 5 * WHITE_MM


def playable(pitch: int) -> bool:
    return type(pitch) is int and LOW <= pitch <= HIGH


def is_black(pitch: int) -> bool:
    return pitch % 12 not in _WHITE_INDEX


def key_x_mm(pitch: int) -> float:
    """Center of the key along the keyboard, from the left edge of A0."""
    octave_start = (pitch // 12 - 1) * OCTAVE_MM
    pitch_class = pitch % 12
    if pitch_class in _WHITE_INDEX:
        center = octave_start + (_WHITE_INDEX[pitch_class] + 0.5) * WHITE_MM
    else:
        center = octave_start + (pitch_class + 0.5) * BLACK_MM
    return center - _A0_OFFSET_MM


def key_width_mm(pitch: int) -> float:
    return BLACK_MM if is_black(pitch) else WHITE_MM


def white_keys() -> list[int]:
    return [p for p in range(LOW, HIGH + 1) if not is_black(p)]


WIDTH_MM = len(white_keys()) * WHITE_MM  # 52 white keys: 1222 mm


def geometry() -> dict:
    """The keyboard dimensions the piano view carries for its renderer."""
    return dict(low=LOW, high=HIGH, width_mm=round(WIDTH_MM, 3), octave_mm=OCTAVE_MM,
                white_key_mm=round(WHITE_MM, 3), black_key_mm=round(BLACK_MM, 3),
                white_length_mm=WHITE_LENGTH_MM, black_length_mm=BLACK_LENGTH_MM,
                black_height_mm=BLACK_HEIGHT_MM, press_mm=PRESS_MM)
