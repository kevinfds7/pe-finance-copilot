"""Central configuration. Everything is overridable through environment variables."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY_DIR = ROOT / "docs" / "policies"
CONTRACT_PATH = ROOT / "docs" / "data_contract.yaml"
REPORTS_DIR = ROOT / "reports"


def _writable_dir(preferred: Path) -> Path:
    """Use the preferred directory if we can write to it, otherwise fall back to a temp dir.

    Hosted environments (for example Streamlit Community Cloud) can have read-only or
    ephemeral file systems, so we never assume the repo folder is writable.
    """
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe = preferred / ".write_probe"
        probe.write_text("ok")
        probe.unlink()
        return preferred
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "pe_finance_copilot"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


DATA_DIR = _writable_dir(Path(os.getenv("PE_COPILOT_DATA_DIR", ROOT / "data")))
DB_PATH = DATA_DIR / "pe_finance.db"
RAW_DIR = DATA_DIR / "raw"
AUDIT_LOG_PATH = DATA_DIR / "audit_log.jsonl"
REVIEW_QUEUE_PATH = DATA_DIR / "review_queue.jsonl"
LINEAGE_PATH = DATA_DIR / "lineage.json"

SEED = int(os.getenv("PE_COPILOT_SEED", "42"))
LATEST_QUARTER = "2024Q4"

# LLM settings (live mode only). The model is configurable so the project does not go stale.
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_TOOL_STEPS = 6
MAX_SQL_ROWS = 50
SQL_TIMEOUT_SECONDS = 3.0
MAX_LIVE_QUESTIONS_PER_SESSION = int(os.getenv("MAX_LIVE_QUESTIONS_PER_SESSION", "15"))

# The assistant may only read these objects. Staging tables are deliberately excluded.
ALLOWED_TABLES = (
    "dim_funds",
    "dim_companies",
    "curated_company_quarter",
    "curated_fund_metrics",
    "dq_summary",
    "dq_quarantine",
)
