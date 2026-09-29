"""Start the local dashboard: .venv/bin/python scripts/run_dashboard.py."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn

parser=argparse.ArgumentParser()
parser.add_argument('--port',type=int,default=8780)
args=parser.parse_args()
uvicorn.run('guitar_video_app.api.dashboard:app',host='127.0.0.1',port=args.port)
