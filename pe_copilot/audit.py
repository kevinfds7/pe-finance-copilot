"""Append-only JSONL audit log of every question, tool call and answer."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import config


def log(event: str, **fields) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **fields}
    with open(config.AUDIT_LOG_PATH, "a") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def read(limit: int = 200) -> list[dict]:
    if not config.AUDIT_LOG_PATH.exists():
        return []
    lines = config.AUDIT_LOG_PATH.read_text().splitlines()[-limit:]
    return [json.loads(x) for x in lines if x.strip()]
