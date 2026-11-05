"""Tools exposed to the assistant. Every tool returns JSON-serialisable data and never raises to the model."""
from __future__ import annotations

from . import retrieval, review, sql_guard
from .sql_guard import SQLGuardError

TOOL_SPECS = [
    {
        "name": "run_sql",
        "description": (
            "Run one read-only SQLite SELECT over curated tables: dim_funds, dim_companies, curated_company_quarter, "
            "curated_fund_metrics, dq_summary, dq_quarantine. Amounts are USD millions. Latest quarter is 2024Q4. "
            "No semicolons or comments. Max 50 rows."
        ),
        "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
    },
    {
        "name": "get_fund_metrics",
        "description": "Get TVPI, DPI, NAV, paid-in and distributions for a fund (id like F1 or name). Omit fund for all funds.",
        "input_schema": {"type": "object", "properties": {"fund": {"type": "string"}}},
    },
    {
        "name": "get_dq_summary",
        "description": "Get the data quality rule results. Optionally filter by severity: critical or warn.",
        "input_schema": {"type": "object", "properties": {"severity": {"type": "string", "enum": ["critical", "warn"]}}},
    },
    {
        "name": "search_policies",
        "description": "Search the policy documents (glossary, valuation policy, data quality policy, AI usage policy). Use for definitions and rules.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "propose_correction",
        "description": "Propose a data correction for human review. It is NOT applied. Use only when the user asks for a fix.",
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string"}, "record_ref": {"type": "string"}, "field": {"type": "string"},
                "proposed_value": {"type": "string"}, "reason": {"type": "string"},
            },
            "required": ["table", "record_ref", "field", "proposed_value", "reason"],
        },
    },
]


def run_sql(sql: str) -> dict:
    return sql_guard.run_query(sql)


def get_fund_metrics(fund: str | None = None) -> dict:
    where, params = "", ()
    if fund:
        where, params = " WHERE fund_id = ? OR lower(fund_name) = lower(?)", (fund.strip(), fund.strip())
    conn = sql_guard.connect_readonly()
    try:
        cur = conn.execute("SELECT fund_id, fund_name, as_of_quarter, total_nav_musd, paid_in_musd, distributions_musd, tvpi, dpi "
                           "FROM curated_fund_metrics" + where, params)
        rows = [list(r) for r in cur.fetchall()]
        cols = [d[0] for d in cur.description]
    finally:
        conn.close()
    if not rows:
        return {"error": f"No fund matches '{fund}'."}
    return {"columns": cols, "rows": rows}


def get_dq_summary(severity: str | None = None) -> dict:
    sql = "SELECT rule_id, rule_name, severity, failing_rows, total_rows, action FROM dq_summary"
    if severity in ("critical", "warn"):
        sql += f" WHERE severity = '{severity}'"
    return sql_guard.run_query(sql + " ORDER BY rule_id")


def search_policies(query: str) -> dict:
    hits = retrieval.search(query, k=3)
    return {"results": hits} if hits else {"results": [], "note": "No relevant policy text found."}


def propose_correction(table: str, record_ref: str, field: str, proposed_value: str, reason: str) -> dict:
    item = review.propose(table, record_ref, field, proposed_value, reason)
    return {"status": "queued_for_human_review", "id": item["id"], "note": "Not applied. A reviewer must approve it."}


REGISTRY = {f.__name__: f for f in (run_sql, get_fund_metrics, get_dq_summary, search_policies, propose_correction)}


def dispatch(name: str, args: dict) -> dict:
    func = REGISTRY.get(name)
    if func is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return func(**(args or {}))
    except SQLGuardError as exc:
        return {"error": str(exc)}
    except TypeError as exc:
        return {"error": f"Bad arguments: {exc}"}
    except Exception as exc:  # never let a tool crash the loop
        return {"error": f"Tool failed: {exc}"}
