from __future__ import annotations


def configure_render(output_path: str, fps: int = 30, resolution: tuple[int, int] = (1080, 1920)) -> None:
    """Run inside Blender. Changes render settings only, not scene object transforms."""
    import bpy

    scene = bpy.context.scene
    scene.render.fps = fps
    scene.render.resolution_x = resolution[0]
    scene.render.resolution_y = resolution[1]
    scene.render.resolution_percentage = 100
    scene.render.filepath = output_path

