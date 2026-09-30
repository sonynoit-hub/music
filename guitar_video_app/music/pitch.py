NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def midi_note_name(pitch: int) -> str:
    octave = pitch // 12 - 1
    return f"{NOTE_NAMES[pitch % 12]}{octave}"
