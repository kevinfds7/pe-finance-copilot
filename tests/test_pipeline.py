import sqlite3

import yaml

from pe_copilot import config, pipeline
from pe_copilot.evaluation.runner import db_fingerprint


def test_failures_match_injected_ground_truth(built_db):
    got = {r["rule_id"]: r["failing_rows"] for r in built_db["summary"]}
    assert got == built_db["expected"]


def test_deterministic():
    pipeline.build()
    a = db_fingerprint()
    pipeline.build()
    assert db_fingerprint() == a


def test_quarantined_rows_absent_from_curated():
    conn = sqlite3.connect(config.DB_PATH)
    assert conn.execute("SELECT COUNT(*) FROM dq_quarantine").fetchone()[0] == 9
    assert conn.execute("SELECT COUNT(*) FROM curated_company_quarter WHERE revenue_musd IS NULL OR revenue_musd < 0 OR nav_musd < 0").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM (SELECT company_id, quarter FROM curated_company_quarter GROUP BY 1,2 HAVING COUNT(*)>1)").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM dim_companies WHERE company_id='C99'").fetchone()[0] == 0


def test_warnings_kept_and_flagged():
    conn = sqlite3.connect(config.DB_PATH)
    flagged = conn.execute("SELECT COUNT(*) FROM curated_company_quarter WHERE dq_flags IS NOT NULL").fetchone()[0]
    assert flagged >= 4


def test_fund_metrics_formula():
    conn = sqlite3.connect(config.DB_PATH)
    for nav, paid, dist, tvpi, dpi in conn.execute("SELECT total_nav_musd, paid_in_musd, distributions_musd, tvpi, dpi FROM curated_fund_metrics"):
        assert abs(tvpi - (nav + dist) / paid) < 0.001
        assert abs(dpi - dist / paid) < 0.001


def test_data_contract_matches_database():
    contract = yaml.safe_load(config.CONTRACT_PATH.read_text())
    conn = sqlite3.connect(config.DB_PATH)
    for name, spec in contract["tables"].items():
        cols = {r[1]: r[2] for r in conn.execute(f"PRAGMA table_info({name})")}
        assert cols == spec["columns"], name
