from types import SimpleNamespace

from pe_copilot import agent, config, review, tools
from pe_copilot.evaluation import runner
from pe_copilot.retrieval import search


def test_retrieval_finds_definition():
    top = search("how is TVPI calculated")[0]
    assert "TVPI" in top["text"]


def test_tool_errors_do_not_raise():
    assert "error" in tools.dispatch("run_sql", {"sql": "DELETE FROM dim_funds"})
    assert "error" in tools.dispatch("nope", {})
    assert "error" in tools.dispatch("run_sql", {})


def test_review_queue_never_changes_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REVIEW_QUEUE_PATH", tmp_path / "q.jsonl")
    monkeypatch.setattr(config, "AUDIT_LOG_PATH", tmp_path / "a.jsonl")
    before = runner.db_fingerprint()
    item = review.propose("curated_company_quarter", "C01/2023Q1", "revenue_musd", "10", "test")
    assert review.pending()[0]["id"] == item["id"]
    assert review.decide(item["id"], True, "reviewer")["status"] == "approved"
    assert not review.pending()
    assert runner.db_fingerprint() == before


class FakeClient:
    """Stands in for anthropic.Anthropic: first asks for a tool, then answers from the tool result."""
    def __init__(self):
        self.calls = []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls.append(kw)
        if len(kw["messages"]) == 1:
            block = SimpleNamespace(type="tool_use", id="tu_1", name="get_fund_metrics", input={"fund": "F1"})
            return SimpleNamespace(content=[block])
        result = kw["messages"][-1]["content"][0]
        assert result["type"] == "tool_result" and result["tool_use_id"] == "tu_1"
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="Done.")])


def test_anthropic_backend_tool_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_LOG_PATH", tmp_path / "a.jsonl")
    client = FakeClient()
    res = agent.run("TVPI of F1?", agent.AnthropicBackend(client=client, model="test-model"))
    assert res.answer == "Done." and [c["name"] for c in res.calls] == ["get_fund_metrics"]
    assert client.calls[0]["model"] == "test-model" and client.calls[0]["tools"] == tools.TOOL_SPECS


def test_api_failure_is_handled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_LOG_PATH", tmp_path / "a.jsonl")
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("boom"))))
    res = agent.run("hi", agent.AnthropicBackend(client=client))
    assert res.error == "boom" and "error" in res.answer.lower()


def test_step_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_LOG_PATH", tmp_path / "a.jsonl")

    class Loop:
        name = "loop"
        def next(self, q, turns):
            return {"calls": [{"id": "x", "name": "get_dq_summary", "args": {}}]}
    res = agent.run("loop", Loop())
    assert len(res.calls) == config.MAX_TOOL_STEPS and "steps" in res.answer


def test_offline_eval_passes_all_cases():
    result = runner.evaluate(agent.MockBackend())
    failed = [r["id"] for r in result["rows"] if not r["passed"]]
    assert not failed, failed
    assert result["n"] == 39
