from __future__ import annotations


def describe_pipeline() -> dict:
    """Small machine-readable summary Codex or another orchestrator can query."""
    return {
        "pipeline": [
            "midi_to_raw_song",
            "raw_song_to_guitar_chart",
            "blender_animate_tabs_render",
        ],
        "primary_contract": "guitar_chart.json",
        "timing": "frame-based",
        "renderer": "Blender",
    }

