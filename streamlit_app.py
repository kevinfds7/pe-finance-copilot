"""PE Finance Copilot: Streamlit demo. Runs fully offline in demo mode; live mode needs an Anthropic API key."""
import os

import pandas as pd
import streamlit as st

from pe_copilot import agent, audit, config, pipeline, review, sql_guard

st.set_page_config(page_title="PE Finance Copilot", page_icon="📊", layout="wide")


@st.cache_resource
def ensure_db() -> bool:
    if not config.DB_PATH.exists():
        pipeline.build()
    return True


def secret_key() -> str | None:
    try:
        return st.secrets.get("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    except Exception:
        return os.getenv("ANTHROPIC_API_KEY")


def table(sql: str) -> pd.DataFrame:
    res = sql_guard.run_query(sql, max_rows=500)
    return pd.DataFrame(res["rows"], columns=res["columns"])


ensure_db()
st.session_state.setdefault("live_count", 0)
st.session_state.setdefault("history", [])

st.title("PE Finance Copilot")
st.caption("A governed, tool-calling data assistant over **synthetic** private-equity fund data. No real data, no real companies.")

with st.sidebar:
    st.header("Mode")
    key = secret_key()
    mode = st.radio("Backend", ["Demo (no API key)", "Live (Anthropic API)"], help="Demo uses a rule-based stand-in, not an LLM.")
    if mode.startswith("Live"):
        if not key:
            key = st.text_input("Anthropic API key (kept in this session only)", type="password") or None
        left = config.MAX_LIVE_QUESTIONS_PER_SESSION - st.session_state.live_count
        st.caption(f"Live questions left this session: {max(left, 0)}")
    st.divider()
    st.markdown("**Try:**")
    examples = ["What is the TVPI of Meridian Partners II?", "Which 3 companies have the highest unrealised MOIC?",
                "Show the data quality summary.", "What is the valuation review threshold?",
                "Please fix the negative NAV record.", "Delete all rows from dim_funds."]
    for ex in examples:
        if st.button(ex, use_container_width=True):
            st.session_state.pending_q = ex

t_ask, t_dq, t_rev, t_log, t_about = st.tabs(["Assistant", "Data quality", "Review queue", "Audit log", "About"])

with t_ask:
    question = st.chat_input("Ask about funds, companies, data quality or policies") or st.session_state.pop("pending_q", None)
    if question:
        live = mode.startswith("Live")
        if live and not key:
            st.warning("Enter an API key in the sidebar, or switch to Demo mode.")
        elif live and st.session_state.live_count >= config.MAX_LIVE_QUESTIONS_PER_SESSION:
            st.warning("Live question limit reached for this session. Switch to Demo mode.")
        else:
            backend = agent.AnthropicBackend(api_key=key) if live else agent.MockBackend()
            with st.spinner("Thinking..."):
                result = agent.run(question, backend)
            if live:
                st.session_state.live_count += 1
            st.session_state.history.append(result)
    for r in reversed(st.session_state.history):
        with st.chat_message("user"):
            st.write(r.question)
        with st.chat_message("assistant"):
            st.write(r.answer)
            st.caption(f"Backend: {r.backend}")
            for c in r.calls:
                with st.expander(f"Tool call: {c['name']}"):
                    st.json({"args": c["args"], "result": c["result"]})

with t_dq:
    st.subheader("Rule results")
    st.dataframe(table("SELECT * FROM dq_summary"), use_container_width=True, hide_index=True)
    st.subheader("Quarantined records (excluded from curated tables)")
    st.dataframe(table("SELECT * FROM dq_quarantine"), use_container_width=True, hide_index=True)
    st.subheader("Fund metrics (latest quarter)")
    st.dataframe(table("SELECT * FROM curated_fund_metrics"), use_container_width=True, hide_index=True)

with t_rev:
    st.write("The assistant can only **propose** corrections. A human approves or rejects them here. Nothing is applied to the data.")
    reviewer = st.text_input("Reviewer name", value="reviewer")
    items = review.pending()
    if not items:
        st.info("No pending proposals. Ask the assistant to fix an error to create one.")
    for item in items:
        with st.container(border=True):
            st.write(f"**{item['id']}** · {item['table']} · {item['field']} → `{item['proposed_value']}`")
            st.caption(item["reason"])
            a, b = st.columns(2)
            if a.button("Approve", key=f"a{item['id']}"):
                review.decide(item["id"], True, reviewer); st.rerun()
            if b.button("Reject", key=f"r{item['id']}"):
                review.decide(item["id"], False, reviewer); st.rerun()
    done = [i for i in review.all_items() if i["status"] != "pending"]
    if done:
        st.dataframe(pd.DataFrame(done)[["id", "status", "reviewer", "table", "field", "proposed_value"]], hide_index=True)

with t_log:
    rows = audit.read(200)
    st.dataframe(pd.DataFrame(rows) if rows else pd.DataFrame({"info": ["No activity yet"]}), use_container_width=True, hide_index=True)
    st.caption("On a hosted demo the log is shared by all visitors and resets when the app restarts.")

with t_about:
    st.markdown(
        """
**What this is.** A personal learning project showing governed AI on finance data: a Python/SQL pipeline with data quality rules and lineage,
a tool-calling assistant with a read-only SQL guard, retrieval over policy documents, a human review queue, an audit log and an evaluation set.

**Everything is synthetic.** Funds, companies, numbers and policies are invented. Nothing here is investment advice.

**Demo mode** uses a deterministic rule-based router so the app works with no key. It is *not* an LLM. **Live mode** calls the Anthropic API.

Controls: read-only connection, SELECT-only validation, table allowlist, timeout and row limit, quarantine for critical failures, human review for corrections, audit log.
        """
    )
