"""Start the local dashboard: .venv/bin/python scripts/run_dashboard.py."""
import argparse
import copy
import logging
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from uvicorn.config import LOGGING_CONFIG


class HidePolling(logging.Filter):
    def filter(self,record):
        args=record.args if isinstance(record.args,tuple) else ()
        return not (len(args)>=3 and args[1]=='GET' and args[2] in ('/api/blender','/api/render'))


parser=argparse.ArgumentParser()
parser.add_argument('--port',type=int,default=8780)
args=parser.parse_args()
log_config=copy.deepcopy(LOGGING_CONFIG)
log_config.setdefault('filters',{})['hide_polling']={'()':HidePolling}
log_config['handlers']['access']['filters']=['hide_polling']
uvicorn.run('guitar_video_app.api.dashboard:app',host='127.0.0.1',port=args.port,log_config=log_config)
