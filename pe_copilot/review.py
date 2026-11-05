"""Human review queue. The assistant can only PROPOSE corrections; nothing is applied automatically."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from . import audit, config


def _load() -> list[dict]:
    if not config.REVIEW_QUEUE_PATH.exists():
        return []
    return [json.loads(x) for x in config.REVIEW_QUEUE_PATH.read_text().splitlines() if x.strip()]


def _save(items: list[dict]) -> None:
    config.REVIEW_QUEUE_PATH.write_text("".join(json.dumps(i) + "\n" for i in items))


def propose(table: str, record_ref: str, field: str, proposed_value: str, reason: str) -> dict:
    item = {
        "id": uuid.uuid4().hex[:8],
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "table": table, "record_ref": record_ref, "field": field,
        "proposed_value": proposed_value, "reason": reason,
        "status": "pending", "reviewer": None,
    }
    items = _load()
    items.append(item)
    _save(items)
    audit.log("correction_proposed", item=item)
    return item


def pending() -> list[dict]:
    return [i for i in _load() if i["status"] == "pending"]


def all_items() -> list[dict]:
    return _load()


def decide(item_id: str, approve: bool, reviewer: str) -> dict | None:
    items = _load()
    for item in items:
        if item["id"] == item_id and item["status"] == "pending":
            item["status"] = "approved" if approve else "rejected"
            item["reviewer"] = reviewer
            _save(items)
            audit.log("correction_decided", id=item_id, status=item["status"], reviewer=reviewer)
            return item
    return None
