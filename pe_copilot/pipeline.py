"""Raw CSV -> staging -> data quality rules -> curated tables, with lineage."""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

from . import config
from .data_gen import generate
from .dq_rules import RULES, run_rules

STAGING = {
    "funds": ("stg_funds", ["fund_id", "fund_name", "vintage_year", "currency", "fund_size_musd"]),
    "companies": ("stg_companies", ["company_id", "fund_id", "company_name", "sector", "region", "invest_date", "cost_musd"]),
    "quarterly_financials": ("stg_financials", ["company_id", "quarter", "revenue_musd", "ebitda_musd", "net_debt_musd", "currency", "as_of_date"]),
    "valuations": ("stg_valuations", ["company_id", "quarter", "nav_musd", "valuation_method", "as_of_date"]),
    "cash_flows": ("stg_cash_flows", ["fund_id", "flow_date", "flow_type", "amount_musd"]),
}
TEXT_COLS = {"fund_id", "fund_name", "currency", "company_id", "sector", "region", "invest_date", "quarter",
             "as_of_date", "valuation_method", "flow_date", "flow_type", "company_name"}

CURATED_DDL = {
    "dim_funds": "CREATE TABLE dim_funds (fund_id TEXT PRIMARY KEY, fund_name TEXT, vintage_year INTEGER, currency TEXT, fund_size_musd REAL)",
    "dim_companies": "CREATE TABLE dim_companies (company_id TEXT PRIMARY KEY, company_name TEXT, fund_id TEXT, fund_name TEXT, sector TEXT, region TEXT, invest_date TEXT, cost_musd REAL)",
    "curated_company_quarter": (
        "CREATE TABLE curated_company_quarter (company_id TEXT, company_name TEXT, fund_id TEXT, fund_name TEXT, sector TEXT, "
        "region TEXT, quarter TEXT, revenue_musd REAL, ebitda_musd REAL, net_debt_musd REAL, nav_musd REAL, cost_musd REAL, "
        "unrealised_moic REAL, as_of_date TEXT, dq_flags TEXT)"
    ),
    "curated_fund_metrics": (
        "CREATE TABLE curated_fund_metrics (fund_id TEXT, fund_name TEXT, as_of_quarter TEXT, total_nav_musd REAL, "
        "paid_in_musd REAL, distributions_musd REAL, tvpi REAL, dpi REAL)"
    ),
    "dq_summary": (
        "CREATE TABLE dq_summary (rule_id TEXT, rule_name TEXT, severity TEXT, source_table TEXT, total_rows INTEGER, "
        "failing_rows INTEGER, pass_rate REAL, action TEXT)"
    ),
    "dq_quarantine": (
        "CREATE TABLE dq_quarantine (rule_id TEXT, severity TEXT, source_table TEXT, source_rowid INTEGER, "
        "company_id TEXT, quarter TEXT, detail TEXT)"
    ),
}


def _convert(col: str, value: str):
    if value == "":
        return None
    return value if col in TEXT_COLS else (int(value) if col == "vintage_year" else float(value))


def write_raw(data: dict) -> None:
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    for key, (_, cols) in STAGING.items():
        with open(config.RAW_DIR / f"{key}.csv", "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=cols)
            writer.writeheader()
            for row in data[key]:
                writer.writerow({c: ("" if row[c] is None else row[c]) for c in cols})


def load_staging(conn: sqlite3.Connection) -> None:
    for key, (table, cols) in STAGING.items():
        conn.execute(f"CREATE TABLE {table} ({', '.join(cols)})")
        with open(config.RAW_DIR / f"{key}.csv", newline="") as fh:
            rows = [tuple(_convert(c, r[c]) for c in cols) for r in csv.DictReader(fh)]
        conn.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(cols))})", rows)


def build(seed: int | None = None) -> dict:
    """Rebuild the whole database from scratch. Deterministic for a given seed."""
    seed = config.SEED if seed is None else seed
    data = generate(seed)
    write_raw(data)

    if config.DB_PATH.exists():
        config.DB_PATH.unlink()
    conn = sqlite3.connect(config.DB_PATH)
    try:
        load_staging(conn)
        failures, summary = run_rules(conn)

        quarantined = {(f["source_table"], f["rid"]) for f in failures if f["severity"] == "critical"}
        flags: dict[tuple[str, int], list[str]] = defaultdict(list)
        for f in failures:
            if f["severity"] == "warn":
                flags[(f["source_table"], f["rid"])].append(f["rule_id"])

        for ddl in CURATED_DDL.values():
            conn.execute(ddl)

        # Dimensions (a company with an unknown fund is quarantined, so it never reaches the dimension)
        conn.execute("INSERT INTO dim_funds SELECT * FROM stg_funds")
        bad_companies = {rid for t, rid in quarantined if t == "stg_companies"}
        for rid, cid, fid, name, sector, region, inv, cost in conn.execute(
            "SELECT rowid, company_id, fund_id, company_name, sector, region, invest_date, cost_musd FROM stg_companies"
        ).fetchall():
            if rid in bad_companies:
                continue
            fund_name = conn.execute("SELECT fund_name FROM stg_funds WHERE fund_id=?", (fid,)).fetchone()[0]
            conn.execute("INSERT INTO dim_companies VALUES (?,?,?,?,?,?,?,?)", (cid, name, fid, fund_name, sector, region, inv, cost))

        # Clean financials and valuations, keyed by company and quarter
        fin = {}
        for rid, cid, q, rev, ebitda, nd, _cur, asof in conn.execute(
            "SELECT rowid, company_id, quarter, revenue_musd, ebitda_musd, net_debt_musd, currency, as_of_date FROM stg_financials ORDER BY rowid"
        ).fetchall():
            if ("stg_financials", rid) not in quarantined:
                fin[(cid, q)] = (rev, ebitda, nd, asof, flags.get(("stg_financials", rid), []))
        val = {}
        for rid, cid, q, nav in conn.execute("SELECT rowid, company_id, quarter, nav_musd FROM stg_valuations ORDER BY rowid").fetchall():
            if ("stg_valuations", rid) not in quarantined:
                val[(cid, q)] = (nav, flags.get(("stg_valuations", rid), []))

        companies = {r[0]: r for r in conn.execute("SELECT company_id, company_name, fund_id, fund_name, sector, region, cost_musd FROM dim_companies")}
        out = []
        for (cid, q), (rev, ebitda, nd, asof, f1) in sorted(fin.items()):
            if (cid, q) not in val or cid not in companies:
                continue
            nav, f2 = val[(cid, q)]
            _, cname, fid, fname, sector, region, cost = companies[cid]
            flag = ",".join(sorted(set(f1 + f2))) or None
            out.append((cid, cname, fid, fname, sector, region, q, rev, ebitda, nd, nav, cost, round(nav / cost, 3), asof, flag))
        conn.executemany("INSERT INTO curated_company_quarter VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", out)

        # Fund metrics at the latest quarter
        for fid, fname in conn.execute("SELECT fund_id, fund_name FROM dim_funds").fetchall():
            nav = conn.execute("SELECT COALESCE(SUM(nav_musd),0) FROM curated_company_quarter WHERE fund_id=? AND quarter=?",
                               (fid, config.LATEST_QUARTER)).fetchone()[0]
            paid = conn.execute("SELECT COALESCE(SUM(amount_musd),0) FROM stg_cash_flows WHERE fund_id=? AND flow_type='call'", (fid,)).fetchone()[0]
            dist = conn.execute("SELECT COALESCE(SUM(amount_musd),0) FROM stg_cash_flows WHERE fund_id=? AND flow_type='distribution'", (fid,)).fetchone()[0]
            conn.execute("INSERT INTO curated_fund_metrics VALUES (?,?,?,?,?,?,?,?)",
                         (fid, fname, config.LATEST_QUARTER, round(nav, 2), round(paid, 2), round(dist, 2),
                          round((nav + dist) / paid, 3) if paid else None, round(dist / paid, 3) if paid else None))

        conn.executemany("INSERT INTO dq_summary VALUES (:rule_id,:rule_name,:severity,:source_table,:total_rows,:failing_rows,:pass_rate,:action)", summary)
        conn.executemany(
            "INSERT INTO dq_quarantine VALUES (?,?,?,?,?,?,?)",
            [(f["rule_id"], f["severity"], f["source_table"], f["rid"], f["company_id"], f["quarter"], f["detail"])
             for f in failures if f["severity"] == "critical"],
        )
        conn.commit()
    finally:
        conn.close()

    lineage = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": seed,
        "note": "All data is synthetic.",
        "rules": [{"id": r.rule_id, "name": r.name, "severity": r.severity, "table": r.table} for r in RULES],
        "tables": {
            "dim_funds": {"from": ["stg_funds"], "logic": "copy"},
            "dim_companies": {"from": ["stg_companies", "stg_funds"], "logic": "exclude companies failing DQ007; add fund name"},
            "curated_company_quarter": {
                "from": ["stg_financials", "stg_valuations", "dim_companies"],
                "logic": "inner join clean financials and valuations on company and quarter; critical failures quarantined; warnings kept in dq_flags; unrealised_moic = nav / cost",
            },
            "curated_fund_metrics": {
                "from": ["curated_company_quarter", "stg_cash_flows"],
                "logic": "TVPI = (NAV + distributions) / paid-in; DPI = distributions / paid-in; at the latest quarter",
            },
            "dq_summary": {"from": ["all staging tables"], "logic": "one row per rule"},
            "dq_quarantine": {"from": ["all staging tables"], "logic": "rows failing a critical rule"},
        },
    }
    config.LINEAGE_PATH.write_text(json.dumps(lineage, indent=2))
    return {"seed": seed, "failures": len(failures), "summary": summary, "expected": data["expected_failures"]}


if __name__ == "__main__":
    result = build()
    for row in result["summary"]:
        print(row["rule_id"], row["failing_rows"], row["action"])
