"""Command line: build the data, ask a question, show data quality, run the evaluation."""
from __future__ import annotations

import argparse
import os

from . import config


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pe_copilot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="regenerate synthetic data and rebuild the database")
    sub.add_parser("dq", help="print the data quality summary")
    ask = sub.add_parser("ask", help="ask the assistant a question")
    ask.add_argument("question")
    ask.add_argument("--live", action="store_true", help="use the Anthropic API (needs ANTHROPIC_API_KEY)")
    ev = sub.add_parser("eval", help="run the golden evaluation set")
    ev.add_argument("--live", action="store_true")
    args = ap.parse_args(argv)

    from . import agent, pipeline

    if args.cmd == "build" or not config.DB_PATH.exists():
        pipeline.build()
    if args.cmd == "build":
        print(f"Built {config.DB_PATH}")
        return 0
    if args.cmd == "dq":
        from . import tools
        for row in tools.get_dq_summary()["rows"]:
            print(*row, sep=" | ")
        return 0

    backend = agent.MockBackend()
    if args.live:
        if not os.getenv("ANTHROPIC_API_KEY"):
            ap.error("--live needs ANTHROPIC_API_KEY in the environment")
        backend = agent.AnthropicBackend()
    if args.cmd == "ask":
        res = agent.run(args.question, backend)
        print(res.answer)
        print(f"\n[backend: {res.backend}; tools: {[c['name'] for c in res.calls]}]")
        return 0
    from .evaluation import runner
    result = runner.evaluate(backend)
    path = runner.write_report(result)
    print(f"Overall pass {result['overall_pass']:.0%} over {result['n']} cases. Report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
