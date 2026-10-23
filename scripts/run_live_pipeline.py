"""Live-run entry point: records the API's own response metadata for every model call (response id, returned model, finish reason, reply
channel, UTC timestamps) into the file named by LIVE_CALL_LOG, then runs scripts/run_reliability.py unchanged. The frozen pipeline is not
modified: the capture wraps the OpenAI SDK call from outside. Same arguments as run_reliability.py (--seeds N --out DIR)."""
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

if __name__ == "__main__":
    log = os.environ.get("LIVE_CALL_LOG")
    if log:
        from app.live.capture import install
        install(log)
    sys.argv[0] = str(ROOT / "scripts" / "run_reliability.py")
    runpy.run_path(sys.argv[0], run_name="__main__")
