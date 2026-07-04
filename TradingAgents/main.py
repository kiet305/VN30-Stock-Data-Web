from __future__ import annotations

import argparse
from pathlib import Path

from scripts.run_research_synthesis_agent import (
    ResearchFlowError,
    mirror_report_to_portal,
    run_research_synthesis_agent,
)


# Full TradingAgentsGraph flow is:
# Analyst Team -> Research Team -> Trader -> Risk Team -> Portfolio Manager.
#
# This entrypoint intentionally activates only the analysis-to-research layer:
# Market report + News report + Fundamentals report + Sentiment report
# -> Bull/Bear Researcher debate rounds -> research_synthesis_report.
#
# Downstream Trader, Risk, and Portfolio flows remain deactivated here.


def _default_output_path(ticker: str, trade_date: str) -> Path:
    return Path(__file__).resolve().parent / "reports" / (
        f"{ticker}_research_synthesis_main_{trade_date}.md"
    )


def _log_progress(message: str) -> None:
    print(message, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the four analyst agents, save their separate reports, then "
            "run Bull/Bear researcher debate rounds."
        )
    )
    parser.add_argument("--ticker", default="HPG")
    parser.add_argument(
        "--date",
        default="2026-01-29",
        help="Analysis date used for all four analyst agents.",
    )
    parser.add_argument(
        "--provider",
        default="openai",
        help="LLM provider. Providers use API-key environment variables or local runtime configuration.",
    )
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--look-back-days", type=int, default=7)
    parser.add_argument(
        "--debate-rounds",
        type=int,
        default=2,
        help="Maximum Bull/Bear debate rounds. Bull always argues first in each round.",
    )
    parser.add_argument("--social-path", default=None)
    parser.add_argument(
        "--feedback-path",
        default=None,
        help="Optional JSONL feedback path. Defaults to ~/.tradingagents/memory/human_research_feedback.jsonl.",
    )
    parser.add_argument(
        "--reuse-analyst-reports",
        action="store_true",
        help="Load existing market/fundamentals/sentiment/news reports from reports/ and run only Bull/Bear debate.",
    )
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    try:
        report, trace = run_research_synthesis_agent(
            ticker=args.ticker,
            trade_date=args.date,
            model=args.model,
            max_steps=args.max_steps,
            look_back_days=args.look_back_days,
            social_path=args.social_path,
            provider=args.provider,
            feedback_path=args.feedback_path,
            debate_rounds=args.debate_rounds,
            progress=_log_progress,
            reuse_analyst_reports=args.reuse_analyst_reports,
        )
    except ResearchFlowError as exc:
        raise SystemExit(f"ERROR: {exc}") from None

    output_path = Path(args.output) if args.output else _default_output_path(args.ticker, args.date)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    portal_output_path = mirror_report_to_portal(output_path)

    print("ACTIVE_FLOW=Market -> Fundamentals -> Sentiment -> News -> Bull/Bear Debate -> Coordinator")
    print(f"TICKER={args.ticker}")
    print(f"TRADE_DATE={args.date}")
    print(f"PROVIDER={args.provider}")
    print(f"MODEL={args.model}")
    print(f"MAX_STEPS={args.max_steps}")
    print(f"DEBATE_ROUNDS={args.debate_rounds}")
    print(f"FEEDBACK_PATH={args.feedback_path or 'default'}")
    print(f"OUTPUT={output_path}")
    if portal_output_path:
        print(f"PORTAL_OUTPUT={portal_output_path}")
    print("ANALYST_AND_RESEARCH_TRACE:")
    for item in trace:
        print(f"- {item}")
    print("DEACTIVATED_FLOWS=Trader, Risk, Portfolio")
    print("REPORT_PREVIEW:")
    print(report[:5000])


if __name__ == "__main__":
    main()
