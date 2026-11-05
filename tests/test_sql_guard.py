import pytest

from pe_copilot import sql_guard as g


@pytest.mark.parametrize("sql", [
    "DROP TABLE dim_funds", "DELETE FROM dim_funds", "UPDATE dim_funds SET fund_name='x'", "SELECT 1; SELECT 2",
    "SELECT * FROM stg_funds", "SELECT * FROM sqlite_master", "SELECT 1 -- comment", "PRAGMA table_info(dim_funds)",
    "WITH x AS (SELECT 1) DELETE FROM dim_funds", "ATTACH DATABASE 'x.db' AS x", "", "SELECT * FROM dim_funds /* c */",
])
def test_blocked(sql):
    with pytest.raises(g.SQLGuardError):
        g.run_query(sql)


def test_allowed_and_cte():
    assert g.run_query("SELECT COUNT(*) AS n FROM dim_funds")["rows"] == [[3]]
    assert g.run_query("WITH t AS (SELECT fund_id FROM dim_funds) SELECT * FROM t ORDER BY 1")["rows"][0] == ["F1"]


def test_row_limit():
    res = g.run_query("SELECT * FROM curated_company_quarter", max_rows=5)
    assert len(res["rows"]) == 5 and res["truncated"]


def test_runaway_query_times_out(monkeypatch):
    monkeypatch.setattr("pe_copilot.config.SQL_TIMEOUT_SECONDS", 0.2)
    with pytest.raises(g.SQLGuardError):
        g.run_query("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT COUNT(*) FROM c")
