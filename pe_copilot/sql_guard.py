"""Read-only SQL guard. Defence in depth: text checks, an authorizer allowlist, a read-only connection,
a timeout and a row limit. The model never gets a writable handle."""
from __future__ import annotations

import re
import sqlite3
import time

from . import config

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|truncate|load_extension)\b", re.I
)


class SQLGuardError(ValueError):
    """Raised when a query is rejected. The message is safe to show to the model and the user."""


def validate(sql: str) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise SQLGuardError("Empty query.")
    text = sql.strip()
    if ";" in text:
        raise SQLGuardError("Only a single statement is allowed (no semicolons).")
    if "--" in text or "/*" in text:
        raise SQLGuardError("Comments are not allowed.")
    if not re.match(r"^(select|with)\b", text, re.I):
        raise SQLGuardError("Only SELECT queries are allowed.")
    match = FORBIDDEN.search(text)
    if match:
        raise SQLGuardError(f"Keyword not allowed: {match.group(1).upper()}.")
    return text


def _authorizer(action, arg1, arg2, dbname, source):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK if arg1 in config.ALLOWED_TABLES else sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_DENY


def connect_readonly() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    conn.set_authorizer(_authorizer)
    return conn


def run_query(sql: str, max_rows: int | None = None) -> dict:
    """Validate and run a query. Returns {columns, rows, truncated}. Raises SQLGuardError on any problem."""
    max_rows = max_rows or config.MAX_SQL_ROWS
    safe = validate(sql)
    wrapped = f"SELECT * FROM ({safe}) LIMIT {max_rows + 1}"
    conn = connect_readonly()
    deadline = time.monotonic() + config.SQL_TIMEOUT_SECONDS
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10000)
    try:
        cur = conn.execute(wrapped)
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description]
    except sqlite3.Error as exc:
        raise SQLGuardError(f"Query rejected or failed: {exc}") from exc
    finally:
        conn.close()
    return {"columns": columns, "rows": [list(r) for r in rows[:max_rows]], "truncated": len(rows) > max_rows}
