from __future__ import annotations


LESSON_CAMERA = "LessonVerticalCamera"
GUITAR_CAMERA = "GuitarCamera"
TAB_ROOT = "Lesson_Tabs_Demo"
NOTE_MARKERS_COLLECTION = "NoteMarkers"
GUITAR_COMPONENTS_COLLECTION = "Guitar Components"

STRING_OBJECTS = {index: f"String_{index}" for index in range(1, 7)}
FRET_OBJECTS = {index: f"Fret_{index:02d}" for index in range(1, 21)}

PRESERVE_NAME_PREFIXES = (
    "Reference Guitar - ",
    "Lesson_Tab_",
    "String_",
    "Fret_",
    "Note_",
    "Tuner_",
    "Bridge_Pin",
    "Inlay_",
    "Rosette_",
)

PRESERVE_EXACT_NAMES = {
    LESSON_CAMERA,
    GUITAR_CAMERA,
    "LessonVerticalCamera_Black_Backdrop",
    TAB_ROOT,
    "Fretboard",
    "Body_Soundboard",
    "Body_Back",
    "Body_Sides",
    "Neck",
    "Neck_Heel",
    "Headstock",
    "Headstock_Face",
    "Nut",
    "Bridge",
    "Saddle",
    "Pickguard",
    "Guitar_Bright_Area_Light",
    "Guitar_Soft_Fill_Light",
}


def is_preserved_name(name: str) -> bool:
    return name in PRESERVE_EXACT_NAMES or any(name.startswith(prefix) for prefix in PRESERVE_NAME_PREFIXES)

