from __future__ import annotations

from pathlib import Path

from guitar_video_app.integrations.guitar_animation import animate_from_chart
from guitar_video_app.integrations.render_video import configure_render
from guitar_video_app.integrations.tab_overlay_visible import build_tab_overlay
from guitar_video_app.integrations.transform_snapshot import compare_snapshots, write_snapshot


def animate_and_prepare_render(
    chart_path: str | Path,
    output_video_path: str | Path | None = None,
    before_snapshot_path: str | Path | None = None,
    after_snapshot_path: str | Path | None = None,
) -> dict:
    import bpy

    start_frame = int(bpy.context.scene.frame_start)
    bpy.context.scene.frame_set(start_frame)
    if before_snapshot_path:
        write_snapshot(before_snapshot_path)

    animate_from_chart(chart_path)
    build_tab_overlay(chart_path)

    if output_video_path:
        configure_render(str(output_video_path))

    bpy.context.scene.frame_set(start_frame)
    if after_snapshot_path:
        write_snapshot(after_snapshot_path)

    changes = {}
    if before_snapshot_path and after_snapshot_path:
        changes = compare_snapshots(before_snapshot_path, after_snapshot_path)

    return {
        "chart_path": str(chart_path),
        "output_video_path": str(output_video_path) if output_video_path else None,
        "preserved_transform_changes": changes,
        "tab_overlay": "visible_v3",
    }

