from __future__ import annotations


LESSON_CAMERA = "LessonVerticalCamera"
GUITAR_CAMERA = "GuitarCamera"
TAB_ROOT = "Lesson_Tabs_Demo"
NOTE_MARKERS_COLLECTION = "NoteMarkers"
GUITAR_COMPONENTS_COLLECTION = "Guitar Components"

STRING_OBJECTS = {index: f"String_{index}" for index in range(1, 7)}
FRET_OBJECTS = {index: f"Fret_{index:02d}" for index in range(1, 21)}
# Scene property with the number of strings the scene draws; scenes without it are 6-string guitar scenes.
SCENE_STRINGS = "Lesson_Strings"
SCENE_FILES = {6: "outputs/v4-vertical.blend", 4: "outputs/bass-vertical.blend"}


def string_objects(count: int = 6) -> dict[int, str]:
    return {index: f"String_{index}" for index in range(1, count + 1)}


def scene_strings(scene) -> int:
    return int(scene.get(SCENE_STRINGS, 6))


def lesson_objects(count: int = 6) -> list[str]:
    """Objects a lesson view of an instrument with count strings needs in its scene."""
    names = ["App_Tab_White_Panel", "App_Tab_Cursor_Visible_6_String_Length",
             "App_Tab_Backdrop_Panel_Cursor_Lines_GROUP", "Nut"]
    names += list(string_objects(count).values())
    names += [f"Lesson_Tab_Line_{index}" for index in range(1, count + 1)]
    return names + list(FRET_OBJECTS.values())


def check_lesson_scene(scene, count: int, objects) -> None:
    """ValueError unless the open scene draws count strings and has the objects a lesson needs."""
    if scene_strings(scene) != count:
        raise ValueError(f"This lesson has {count} strings but the open scene draws {scene_strings(scene)}; "
                         f"open {SCENE_FILES.get(count, 'a matching scene')}.")
    missing = [name for name in lesson_objects(count) if name not in objects]
    if missing or scene.camera is None:
        raise ValueError(f"Open {SCENE_FILES.get(count, 'the lesson scene')} first. Missing: {', '.join(missing)}")

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

