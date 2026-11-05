"""Data quality rules, expressed as SQL over the staging tables ("data quality as code").

Each rule query returns: rid (row id in the staging table), company_id, quarter, detail.
Critical failures are quarantined and kept out of curated tables. Warnings stay in, flagged.
"""
from __future__ import annotations

from dataclasses import dataclass
import sqlite3

_QEND = (
    "date(substr({t}.quarter,1,4) || CASE substr({t}.quarter,6,1) "
    "WHEN '1' THEN '-03-31' WHEN '2' THEN '-06-30' WHEN '3' THEN '-09-30' ELSE '-12-31' END)"
)


@dataclass(frozen=True)
class Rule:
    rule_id: str
    name: str
    severity: str  # "critical" or "warn"
    table: str  # staging table the rule reads
    description: str
    sql: str


RULES: list[Rule] = [
    Rule("DQ001", "Revenue is present", "critical", "stg_financials",
         "Quarterly revenue must not be missing.",
         "SELECT rowid AS rid, company_id, quarter, 'revenue is missing' AS detail "
         "FROM stg_financials WHERE revenue_musd IS NULL"),
    Rule("DQ002", "Revenue is not negative", "critical", "stg_financials",
         "Quarterly revenue must be zero or positive.",
         "SELECT rowid, company_id, quarter, 'revenue is negative' "
         "FROM stg_financials WHERE revenue_musd < 0"),
    Rule("DQ003", "No duplicate company-quarter rows", "critical", "stg_financials",
         "Only one financial record per company and quarter. The first row is kept.",
         "SELECT f.rowid, f.company_id, f.quarter, 'duplicate of an earlier row' "
         "FROM stg_financials f JOIN (SELECT company_id, quarter, MIN(rowid) AS first_rid "
         "FROM stg_financials GROUP BY company_id, quarter) m "
         "ON f.company_id = m.company_id AND f.quarter = m.quarter WHERE f.rowid > m.first_rid"),
    Rule("DQ004", "EBITDA does not exceed revenue", "warn", "stg_financials",
         "EBITDA above revenue is implausible and needs review.",
         "SELECT rowid, company_id, quarter, 'EBITDA is greater than revenue' "
         "FROM stg_financials WHERE revenue_musd > 0 AND ebitda_musd > revenue_musd"),
    Rule("DQ005", "Reported within 120 days of quarter end", "warn", "stg_financials",
         "Late reporting weakens the reliability of the figures.",
         "SELECT rowid, company_id, quarter, 'reported more than 120 days after quarter end' "
         "FROM stg_financials WHERE julianday(as_of_date) - julianday("
         + _QEND.format(t="stg_financials") + ") > 120"),
    Rule("DQ006", "Currency matches the fund currency", "critical", "stg_financials",
         "Company financials must be reported in the currency of the owning fund.",
         "SELECT f.rowid, f.company_id, f.quarter, 'currency ' || f.currency || ' differs from fund currency ' || u.currency "
         "FROM stg_financials f JOIN stg_companies c ON c.company_id = f.company_id "
         "JOIN stg_funds u ON u.fund_id = c.fund_id WHERE f.currency <> u.currency"),
    Rule("DQ007", "Company belongs to a known fund", "critical", "stg_companies",
         "Every company must point to a fund that exists in the fund master.",
         "SELECT rowid, company_id, NULL, 'fund ' || fund_id || ' not found in fund master' "
         "FROM stg_companies WHERE fund_id NOT IN (SELECT fund_id FROM stg_funds)"),
    Rule("DQ008", "NAV is not negative", "critical", "stg_valuations",
         "Net asset value must be zero or positive.",
         "SELECT rowid, company_id, quarter, 'NAV is negative' FROM stg_valuations WHERE nav_musd < 0"),
    Rule("DQ009", "NAV is not above 15x cost", "warn", "stg_valuations",
         "A mark above 15 times cost needs review.",
         "SELECT v.rowid, v.company_id, v.quarter, 'NAV is more than 15x cost' "
         "FROM stg_valuations v JOIN stg_companies c ON c.company_id = v.company_id "
         "WHERE v.nav_musd > 15 * c.cost_musd"),
]


def run_rules(conn: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    """Return (failures, summary). Each failure is one rule hit on one staging row."""
    failures: list[dict] = []
    summary: list[dict] = []
    for rule in RULES:
        rows = conn.execute(rule.sql).fetchall()
        total = conn.execute(f"SELECT COUNT(*) FROM {rule.table}").fetchone()[0]
        for rid, company_id, quarter, detail in rows:
            failures.append(
                {
                    "rule_id": rule.rule_id,
                    "severity": rule.severity,
                    "source_table": rule.table,
                    "rid": rid,
                    "company_id": company_id,
                    "quarter": quarter,
                    "detail": detail,
                }
            )
        failing = len(rows)
        summary.append(
            {
                "rule_id": rule.rule_id,
                "rule_name": rule.name,
                "severity": rule.severity,
                "source_table": rule.table,
                "total_rows": total,
                "failing_rows": failing,
                "pass_rate": round(1 - failing / total, 4) if total else 1.0,
                "action": "quarantined" if rule.severity == "critical" else "flagged",
            }
        )
    return failures, summary
