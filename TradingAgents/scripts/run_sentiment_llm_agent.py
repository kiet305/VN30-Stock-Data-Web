from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.llm_runtime import (
    apply_llm_runtime_defaults,
    build_llm_kwargs,
)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_runtime_env() -> None:
    repo_root = _repo_root()
    for candidate in (
        repo_root / ".env",
        repo_root.parent / ".env",
    ):
        _load_env_file(candidate)


def _build_prompt(
    ticker: str,
    trade_date: str,
    social_context: str,
    feedback_context: str = "",
) -> str:
    from tradingagents.agents.utils.agent_utils import get_analysis_report_format_instruction

    feedback_block = ""
    if feedback_context:
        feedback_block = f"""

Human correction memory from prior runs:
{feedback_context}

Apply these corrections when interpreting sentiment. If fresh local data conflicts with a correction, state the conflict explicitly.
"""

    return f"""You are a financial market sentiment analyst for Vietnamese equities.

Analyze the local market-wide social metrics below for ticker `{ticker}` on analysis date `{trade_date}`.

Use only the provided local project data. Do not claim Reddit, StockTwits, Facebook post text, or external web evidence unless it is explicitly present in the context.

Interpretation guide:
- Attention index measures discussion intensity, not automatically positive sentiment.
- Reaction sentiment score ranges from -1 to 1. Positive values indicate love/wow/haha reactions dominate sad reactions.
- High attention with weak or mixed score means crowded attention but uncertain emotional direction.
- If ticker-specific rows are unavailable, clearly state that only market-wide sentiment is available.
- Google Trends context is broad Vietnam public-search interest, not stock-specific proof unless a trend explicitly names a company/sector.

Output in Vietnamese. Put the overall sentiment band, 0-10 sentiment score,
confidence, market-wide sentiment read, ticker-specific read, top attention
tickers, Google Trends context, trading implications, and data limitations inside
the mandatory analyst report structure below. Do not append a separate summary
table.
{feedback_block}

{get_analysis_report_format_instruction(ticker, trade_date)}

<local_social_context>
{social_context}
</local_social_context>
"""


def _is_bad_llm_report(report: str) -> bool:
    if len(report) > 50000:
        return True
    return any(len(line) > 5000 for line in report.splitlines())


def run_sentiment_agent(
    ticker: str,
    trade_date: str | None,
    model: str,
    look_back_days: int,
    social_path: str | None = None,
    provider: str = "openai",
    feedback_context: str = "",
) -> tuple[str, list[str], str]:
    _load_runtime_env()
    provider = apply_llm_runtime_defaults(provider, model)

    from tradingagents.dataflows.local_social import (
        build_deterministic_social_report,
        build_market_social_context,
        latest_social_date,
    )

    resolved_date = trade_date or latest_social_date(social_path)
    social_context = build_market_social_context(
        ticker=ticker,
        curr_date=resolved_date,
        look_back_days=look_back_days,
        social_path=social_path,
    )
    trace = [
        f"build_market_social_context(ticker={ticker}, date={resolved_date}, look_back_days={look_back_days}, social_path={social_path or 'trend/social.csv'})"
    ]

    def fallback(reason: str) -> tuple[str, list[str], str]:
        trace.append(f"deterministic_fallback(reason={reason})")
        report = build_deterministic_social_report(
            ticker=ticker,
            curr_date=resolved_date,
            look_back_days=look_back_days,
            social_path=social_path,
        )
        return report, trace, resolved_date

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.llm_clients import create_llm_client

        messages = [
            SystemMessage(content=_build_prompt(ticker, resolved_date, social_context, feedback_context)),
            HumanMessage(content=f"Produce the sentiment report for {ticker}."),
        ]
        config = DEFAULT_CONFIG.copy()
        config["llm_provider"] = provider
        config["quick_think_llm"] = model
        config["deep_think_llm"] = model
        config["output_language"] = os.environ.get("TRADINGAGENTS_OUTPUT_LANGUAGE", "Vietnamese")
        llm = create_llm_client(
            provider=provider,
            model=model,
            base_url=config.get("backend_url"),
            **build_llm_kwargs(provider, config),
        ).get_llm()
        response = llm.invoke(messages)
        report = str(response.content).strip()
    except Exception as exc:  # noqa: BLE001 - fall back to deterministic local report
        return fallback(type(exc).__name__)

    if not report:
        return fallback("empty_llm_response")
    if _is_bad_llm_report(report):
        return fallback("oversized_or_malformed_llm_response")

    return report, trace, resolved_date


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the local-social-backed Sentiment Analyst."
    )
    parser.add_argument("--ticker", default="MARKET")
    parser.add_argument("--date", default=None, help="Defaults to latest date in trend/social.csv")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--look-back-days", type=int, default=7)
    parser.add_argument("--social-path", default=None)
    parser.add_argument(
        "--output",
        default=None,
        help="Markdown output path. Defaults to TradingAgents/reports/<ticker>_sentiment_social_main_<date>.md",
    )
    args = parser.parse_args()

    report, trace, resolved_date = run_sentiment_agent(
        ticker=args.ticker,
        trade_date=args.date,
        model=args.model,
        look_back_days=args.look_back_days,
        social_path=args.social_path,
        provider=args.provider,
    )
    output_path = (
        Path(args.output)
        if args.output
        else _repo_root() / "reports" / f"{args.ticker}_sentiment_social_main_{resolved_date}.md"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    print(f"PROVIDER={args.provider}")
    print(f"MODEL={args.model}")
    print(f"TICKER={args.ticker}")
    print(f"TRADE_DATE={resolved_date}")
    print(f"OUTPUT={output_path}")
    print("TRACE:")
    for item in trace:
        print(f"- {item}")
    print("REPORT_PREVIEW:")
    print(report[:5000])


if __name__ == "__main__":
    main()
