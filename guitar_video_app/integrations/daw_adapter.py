from __future__ import annotations

from pathlib import Path


def export_chart_for_daw(chart_path: str | Path) -> dict:
    """Placeholder boundary for future DAW API/export integration."""
    return {
        "chart_path": str(chart_path),
        "status": "not_connected",
        "message": "DAW integration boundary is ready; connect a specific DAW API next.",
    }

