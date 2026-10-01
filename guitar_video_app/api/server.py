from __future__ import annotations

from pathlib import Path

from guitar_video_app.api.service import build_chart_from_raw_json, build_from_midi


def create_app():
    try:
        from fastapi import FastAPI
        from pydantic import BaseModel
    except ImportError as exc:
        raise RuntimeError("Install FastAPI to run the API: python -m pip install fastapi uvicorn") from exc

    app = FastAPI(title="Music Video Studio")

    class MidiBuildRequest(BaseModel):
        midi_path: str
        output_dir: str = "work/data"
        fps: float = 30.0

    class ChartBuildRequest(BaseModel):
        raw_json_path: str
        output_path: str = "work/data/guitar_chart.json"
        fps: float = 30.0

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/build/from-midi")
    def from_midi(request: MidiBuildRequest) -> dict:
        result = build_from_midi(request.midi_path, request.output_dir, fps=request.fps)
        return {
            "raw_song_path": str(result.raw_song_path),
            "chart_path": str(result.chart_path),
            "event_count": result.event_count,
            "bpm": result.bpm,
            "fps": result.fps,
        }

    @app.post("/build/chart")
    def chart(request: ChartBuildRequest) -> dict:
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        result = build_chart_from_raw_json(request.raw_json_path, output, fps=request.fps)
        return {
            "raw_song_path": str(result.raw_song_path),
            "chart_path": str(result.chart_path),
            "event_count": result.event_count,
            "bpm": result.bpm,
            "fps": result.fps,
        }

    return app


app = create_app()

