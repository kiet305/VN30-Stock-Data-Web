from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.human_feedback import append_feedback, load_feedback, resolve_feedback_path


AGENT_CHOICES = (
    "all",
    "analyst",
    "market",
    "fundamentals",
    "sentiment",
    "news",
    "research",
    "bull",
    "bear",
    "synthesis",
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Store human corrections that future TradingAgents research runs will read."
    )
    parser.add_argument("--ticker", default="*", help="Ticker scope, or * for every ticker.")
    parser.add_argument("--date", default="", help="Optional analysis date scope, e.g. 2026-01-29.")
    parser.add_argument("--agent", default="all", choices=AGENT_CHOICES)
    parser.add_argument("--issue", required=True, help="What was wrong or weak in the prior analysis.")
    parser.add_argument("--correction", required=True, help="How future agents should handle it.")
    parser.add_argument("--evidence", default="", help="Optional evidence or source for your correction.")
    parser.add_argument("--source-report", default="", help="Optional report filename/path you reviewed.")
    parser.add_argument("--tag", action="append", default=[], help="Optional tag; can be repeated.")
    parser.add_argument("--path", default=None, help="Override feedback JSONL path.")
    parser.add_argument("--list", action="store_true", help="Print recent stored feedback after writing.")
    args = parser.parse_args()

    path = append_feedback(
        ticker=args.ticker,
        trade_date=args.date,
        agent=args.agent,
        issue=args.issue,
        correction=args.correction,
        evidence=args.evidence,
        source_report=args.source_report,
        tags=args.tag,
        path=args.path,
    )

    print(f"FEEDBACK_PATH={path}")
    print("STATUS=stored")

    if args.list:
        print("RECENT_FEEDBACK:")
        for item in reversed(load_feedback(resolve_feedback_path(args.path))[-5:]):
            scope = item.ticker if item.ticker else "*"
            date = f" {item.trade_date}" if item.trade_date else ""
            print(f"- [{item.agent} {scope}{date}] {item.issue} -> {item.correction}")


if __name__ == "__main__":
    main()
