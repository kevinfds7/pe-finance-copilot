"""Tool-calling loop with two interchangeable backends.

AnthropicBackend calls a real model. MockBackend is a deterministic rule-based stand-in used for the
offline demo and tests. IT IS NOT AN LLM and says nothing about model quality.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from . import audit, config, tools

SYSTEM_PROMPT = """You are a careful data assistant for a private-equity finance team. All data is synthetic.
Rules:
- Answer numeric questions only from tool results. Never guess or compute from memory.
- Use get_fund_metrics for fund KPIs, run_sql for company-level questions, get_dq_summary for data quality, search_policies for definitions and rules.
- You can only read approved curated tables. You cannot change data. If asked to modify, delete, bypass controls, reveal secrets or give investment advice, refuse briefly and begin your reply with: I can't help with that.
- If the data does not contain the answer, say so.
- If asked to fix an error, call propose_correction; it goes to a human reviewer and is not applied.
- Amounts are USD millions. The latest quarter is 2024Q4. Keep answers short and state the quarter and units."""

REFUSAL = "I can't help with that request. I can only read approved data, and any change has to go through human review."


@dataclass
class AgentResult:
    question: str
    answer: str
    calls: list = field(default_factory=list)  # [{name, args, result}]
    backend: str = ""
    error: str | None = None


class AnthropicBackend:
    name = "live"

    def __init__(self, api_key: str | None = None, client=None, model: str | None = None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.client = client
        self.model = model or config.ANTHROPIC_MODEL

    def next(self, question: str, turns: list[list[dict]]) -> dict:
        messages = [{"role": "user", "content": question}]
        for turn in turns:
            messages.append({"role": "assistant", "content": [
                {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]} for c in turn]})
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": c["id"], "content": json.dumps(c["result"], default=str)} for c in turn]})
        resp = self.client.messages.create(model=self.model, max_tokens=1024, system=SYSTEM_PROMPT,
                                           tools=tools.TOOL_SPECS, messages=messages)
        uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
        if uses:
            return {"calls": [{"id": b.id, "name": b.name, "args": dict(b.input)} for b in uses]}
        return {"final": "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text").strip()}


_UNSAFE = re.compile(
    r"\b(delete|drop|update|insert|truncate|overwrite|ignore (all |your |previous )|system prompt|api key|password|secret|"
    r"staging|bypass|disable (the )?(guard|audit|log)|should i (buy|sell|invest))\b|stg_|sqlite_master|set .* to \d", re.I)
_FUNDS = [(r"partners\s+iii|\bf3\b|growth\s+iii", "F3"), (r"partners\s+ii\b|\bf2\b", "F2"), (r"partners\s+i\b|\bf1\b", "F1")]
_METRICS = {"net debt": "net_debt_musd", "ebitda": "ebitda_musd", "revenue": "revenue_musd", "moic": "unrealised_moic", "nav": "nav_musd"}
_SECTORS = ["Industrials", "Technology", "Energy", "Healthcare", "Consumer", "Infrastructure", "Financials", "Telecom"]


def _fund_in(q: str):
    for pat, fid in _FUNDS:
        if re.search(pat, q, re.I):
            return fid
    return None


def _quarter_in(q: str) -> str:
    m = re.search(r"20\d\dQ[1-4]", q, re.I)
    return m.group(0).upper() if m else config.LATEST_QUARTER


class MockBackend:
    """Deterministic keyword router. Demonstrates the loop, tools and controls without an API key."""
    name = "demo"

    def _plan(self, q: str):
        ql = q.lower()
        if _UNSAFE.search(q):
            return None, "refuse"
        if re.search(r"\b(propose|correct|fix)\b", ql):
            return ("propose_correction", {"table": "curated_company_quarter", "record_ref": "see question", "field": "unspecified",
                                           "proposed_value": "to be confirmed by reviewer", "reason": q[:200]}), "propose"
        fid0 = _fund_in(q)
        if fid0 and re.search(r"tvpi|dpi|paid-in|paid in|distributions|nav|metrics", ql):
            return ("get_fund_metrics", {"fund": fid0}), "fund"
        if re.search(r"\b(what is|define|meaning|policy|threshold|how often|how is|calculated|who can|allowed|approved|methods|say about|oversight)\b", ql) and not re.search(r"\b(of|for) (aurelia|brightpath)", ql):
            return ("search_policies", {"query": q}), "policy"
        if re.search(r"how many.*quarantin", ql):
            return ("run_sql", {"sql": "SELECT COUNT(*) AS quarantined_records FROM dq_quarantine"}), "sql"
        if re.search(r"data quality|quarantin|dq|failing|rule|critical|warning", ql):
            sev = "critical" if "critical" in ql else ("warn" if "warn" in ql else None)
            return ("get_dq_summary", {"severity": sev} if sev else {}), "dq"
        fid = _fund_in(q)
        if re.search(r"tvpi|dpi|paid-in|paid in|distributions|total nav", ql) or (fid and re.search(r"nav|metrics", ql)):
            return ("get_fund_metrics", {"fund": fid} if fid else {}), "fund"
        metric = next((c for k, c in _METRICS.items() if k in ql), "unrealised_moic" if "moic" in ql else None)
        quarter = _quarter_in(q)
        if re.search(r"how many", ql):
            where = []
            if fid:
                where.append(f"fund_id = '{fid}'")
            for s in _SECTORS:
                if s.lower() in ql:
                    where.append(f"sector = '{s}'")
            return ("run_sql", {"sql": "SELECT COUNT(*) AS companies FROM dim_companies" + (" WHERE " + " AND ".join(where) if where else "")}), "sql"
        m = re.search(r"\b(highest|top|lowest|bottom|largest|smallest|best|worst)\b(?: (\d+))?", ql)
        if m:
            col = metric or "unrealised_moic"
            order = "ASC" if m.group(1) in ("lowest", "bottom", "smallest", "worst") else "DESC"
            n = int(m.group(2)) if m.group(2) else 3
            return ("run_sql", {"sql": f"SELECT company_name, {col} FROM curated_company_quarter WHERE quarter = '{quarter}' ORDER BY {col} {order}, company_name LIMIT {n}"}), "sql"
        if metric:
            conn = tools.sql_guard.connect_readonly()
            try:
                names = [r[0] for r in conn.execute("SELECT company_name FROM dim_companies")]
            finally:
                conn.close()
            for name in names:
                if name.lower() in ql:
                    return ("run_sql", {"sql": f"SELECT company_name, quarter, {metric} FROM curated_company_quarter WHERE company_name = '{name}' AND quarter = '{quarter}'"}), "sql"
        return None, "unknown"

    @staticmethod
    def _table(res: dict) -> str:
        if "error" in res:
            return f"The tool returned an error: {res['error']}"
        if not res["rows"]:
            return "No matching rows found."
        return "\n".join(", ".join(f"{c}: {v}" for c, v in zip(res["columns"], row)) for row in res["rows"])

    def next(self, question: str, turns: list[list[dict]]) -> dict:
        plan, kind = self._plan(question)
        if kind == "refuse":
            return {"final": REFUSAL}
        if kind == "unknown":
            return {"final": "I don't have data to answer that. I can answer questions about fund metrics, company financials, data quality and policies."}
        if not turns:
            return {"calls": [{"id": "mock_1", "name": plan[0], "args": plan[1]}]}
        res = turns[-1][0]["result"]
        if kind == "policy":
            hits = res.get("results", [])
            if not hits:
                return {"final": "I couldn't find that in the policy documents."}
            return {"final": f"According to {hits[0]['source']} ({hits[0]['section']}): " + " ".join(hits[0]["text"].splitlines()[1:]).strip()}
        if kind == "propose":
            return {"final": f"I've queued a correction proposal for human review (id {res.get('id')}). It has not been applied."}
        return {"final": self._table(res) + "\n(Amounts in USD millions; latest quarter 2024Q4 unless stated.)"}


def run(question: str, backend=None) -> AgentResult:
    backend = backend or MockBackend()
    result = AgentResult(question=question, answer="", backend=getattr(backend, "name", "custom"))
    audit.log("question", question=question, backend=result.backend)
    turns: list[list[dict]] = []
    try:
        for _ in range(config.MAX_TOOL_STEPS):
            step = backend.next(question, turns)
            if "final" in step:
                result.answer = step["final"]
                break
            turn = []
            for call in step["calls"]:
                out = tools.dispatch(call["name"], call["args"])
                audit.log("tool_call", name=call["name"], args=call["args"], error=out.get("error") if isinstance(out, dict) else None)
                call = {**call, "result": out}
                turn.append(call)
                result.calls.append({"name": call["name"], "args": call["args"], "result": out})
            turns.append(turn)
        else:
            result.answer = "I couldn't finish within the allowed number of steps."
    except Exception as exc:  # network/API failures must not crash the app
        result.error = str(exc)
        result.answer = f"The assistant hit an error: {exc}"
    audit.log("answer", answer=result.answer, tools=[c["name"] for c in result.calls])
    return result
