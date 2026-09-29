# Beat-based lesson tests

Version 2 uses standard guitar numbering: 1 is high E, 6 is low E.
This differs from the historical demo's reversed tab-row values. Do not copy
old `string` values without converting their meaning. The scene names its strings
in reverse: V2 string 1 (thin high E) maps to `String_6`, and string 6 (thick low E)
maps to `String_1`. Staff lines are sorted top-to-bottom in camera space.

Starts and durations are in quarter-note beats. Use numbers or rational strings
such as `"1/3"` for exact triplets. At 120 BPM and 60 FPS, one beat is 30 frames.
Each note is active on the half-open interval `[start, end)`. A new note on the
same string cuts off the previous note permanently. Simultaneous notes on the
same string are rejected. Notes on different strings can overlap freely.

The cursor advances continuously across two measures per page, including rests.
A note sustained across a page remains active on the guitar; its tab number is
shown on its onset page only. No tie or rhythmic-stem notation is generated yet.
Note durations currently control playback, not engraved rhythmic symbols.
Inactive strings and markers reset even when seeking backward or looping.

Fixtures:

- `01_mapping`: all strings, open and fretted.
- `02_durations`: sixteenth, eighth, quarter, half, whole, dotted and triplets.
- `03_chords`: two through six strings together.
- `04_independent_endings`: different lengths within a chord.
- `05_overlap`: sustained bass beneath melody.
- `06_retrigger`: same-string repeats, changes and early cutoff.
- `07_silence`: opening rest, empty measure and ending silence.
- `08_boundaries`: sustained notes across measure and page changes.
- `09_frets`: 0, 1, 9, 10, 12 and 20.
- `10_dense`: consecutive two-digit sixteenth notes.
- `11_combined`: combined cases with silence between sections.
- `invalid/`: malformed strings, frets, duration, start, IDs and same-string chords.

Run from the project directory:

```sh
python3 scripts/build_lesson_tests.py
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup outputs/reference-guitar.blend --python-exit-code 1 --python scripts/verify_lesson_v2.py
```

The verification creates `outputs/lesson-v2-tests.blend` and a chord preview;
it does not overwrite `reference-guitar.blend`. Load another test in Blender:

```python
from guitar_video_app.integrations.lesson_setup import install_lesson
install_lesson('/Users/dc/CodexProjects/guitar/data/lesson_tests/02_durations.json')
```

The V2 blend's embedded loader imports the external Python project on reopen.
Keep the project at its current path, or rerun the installer after moving it.
V2 intentionally covers fixed-tempo fretted/open notes; bends, slides, muting,
tempo changes and audio synthesis are not implemented by these fixtures.
