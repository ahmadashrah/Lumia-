"""JSON file logging for Lio runs."""

import json
from datetime import datetime
from pathlib import Path

LOG_ROOT = Path(__file__).resolve().parents[2] / "logs" / "lio"


def log_run(capability: str, payload: dict) -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%H%M%S")
    folder = LOG_ROOT / today
    folder.mkdir(parents=True, exist_ok=True)
    fname = folder / f"{capability}_{ts}.json"
    fname.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return fname
