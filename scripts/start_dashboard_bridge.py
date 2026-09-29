"""Run in Blender's text editor when the dashboard bridge is not connected."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from guitar_video_app.integrations.blender_bridge_server import start_bridge
print(start_bridge())
