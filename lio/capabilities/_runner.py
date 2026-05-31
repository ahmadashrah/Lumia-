"""Shared run helper for capability modules."""

import json
from datetime import datetime

from ..core import engine, logger
from ..core.prompts import system_for


def run(capability: str, payload: dict, max_tokens: int = 2500) -> dict:
    system = system_for(capability)
    user = json.dumps(payload, indent=2, ensure_ascii=False)
    raw = engine.generate(system, user, max_tokens=max_tokens)
    record = {
        "capability": capability,
        "timestamp": datetime.now().isoformat(),
        "input": payload,
        "output": raw,
    }
    log_path = logger.log_run(capability, record)
    record["log_path"] = str(log_path)
    return record
