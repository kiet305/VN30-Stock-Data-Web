from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def default_feedback_path() -> Path:
    return (
        Path(os.environ.get("TRADINGAGENTS_HOME", Path.home() / ".tradingagents"))
        / "memory"
        / "human_research_feedback.jsonl"
    )


DEFAULT_FEEDBACK_PATH = default_feedback_path()

GLOBAL_TICKERS = {"", "*", "ALL", "MARKET"}
GLOBAL_AGENTS = {"", "*", "all"}


@dataclass
class HumanFeedback:
    created_at: str
    ticker: str
    agent: str
    issue: str
    correction: str
    trade_date: str = ""
    evidence: str = ""
    source_report: str = ""
    tags: list[str] | None = None


def resolve_feedback_path(path: str | Path | None = None) -> Path:
    configured = path or os.environ.get("TRADINGAGENTS_HUMAN_FEEDBACK_PATH")
    return Path(configured).expanduser() if configured else default_feedback_path()


def append_feedback(
    *,
    ticker: str,
    agent: str,
    issue: str,
    correction: str,
    trade_date: str = "",
    evidence: str = "",
    source_report: str = "",
    tags: Iterable[str] | None = None,
    path: str | Path | None = None,
) -> Path:
    target = resolve_feedback_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    entry = HumanFeedback(
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        ticker=_normalize_ticker(ticker),
        agent=_normalize_agent(agent),
        trade_date=trade_date.strip(),
        issue=_clean_text(issue, max_chars=1600),
        correction=_clean_text(correction, max_chars=1600),
        evidence=_clean_text(evidence, max_chars=1600),
        source_report=_clean_text(source_report, max_chars=500),
        tags=[_clean_text(tag, max_chars=80) for tag in (tags or []) if _clean_text(tag, max_chars=80)],
    )
    if not entry.issue:
        raise ValueError("Feedback issue is required.")
    if not entry.correction:
        raise ValueError("Feedback correction is required.")
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
    return target


def load_feedback(path: str | Path | None = None) -> list[HumanFeedback]:
    target = resolve_feedback_path(path)
    if not target.exists():
        return []
    entries: list[HumanFeedback] = []
    for raw_line in target.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        entries.append(
            HumanFeedback(
                created_at=str(payload.get("created_at") or ""),
                ticker=_normalize_ticker(str(payload.get("ticker") or "")),
                agent=_normalize_agent(str(payload.get("agent") or "")),
                trade_date=str(payload.get("trade_date") or "").strip(),
                issue=_clean_text(str(payload.get("issue") or ""), max_chars=1600),
                correction=_clean_text(str(payload.get("correction") or ""), max_chars=1600),
                evidence=_clean_text(str(payload.get("evidence") or ""), max_chars=1600),
                source_report=_clean_text(str(payload.get("source_report") or ""), max_chars=500),
                tags=[
                    _clean_text(str(tag), max_chars=80)
                    for tag in payload.get("tags", [])
                    if _clean_text(str(tag), max_chars=80)
                ],
            )
        )
    return entries


def relevant_feedback(
    *,
    ticker: str,
    agents: Iterable[str],
    trade_date: str = "",
    limit: int = 8,
    path: str | Path | None = None,
) -> list[HumanFeedback]:
    wanted_ticker = _normalize_ticker(ticker)
    wanted_agents = {_normalize_agent(agent) for agent in agents}
    wanted_agents.update(GLOBAL_AGENTS)
    wanted_date = trade_date.strip()

    matches: list[HumanFeedback] = []
    for entry in reversed(load_feedback(path)):
        if entry.ticker not in GLOBAL_TICKERS and entry.ticker != wanted_ticker:
            continue
        if entry.agent not in wanted_agents:
            continue
        if entry.trade_date and wanted_date and entry.trade_date != wanted_date:
            continue
        matches.append(entry)
        if len(matches) >= limit:
            break
    return matches


def format_feedback_context(entries: Iterable[HumanFeedback]) -> str:
    items = list(entries)
    if not items:
        return ""
    lines = [
        "Human correction memory from prior research runs.",
        "Use these corrections to avoid repeated analytical mistakes. If a correction conflicts with fresh tool data, state the conflict explicitly.",
    ]
    for index, entry in enumerate(items, start=1):
        scope = entry.ticker if entry.ticker not in GLOBAL_TICKERS else "ALL"
        date = f", date={entry.trade_date}" if entry.trade_date else ""
        evidence = f" Evidence: {entry.evidence}" if entry.evidence else ""
        source = f" Source report: {entry.source_report}" if entry.source_report else ""
        lines.append(
            f"{index}. [{entry.agent}; ticker={scope}{date}] Issue: {entry.issue} "
            f"Correction to apply: {entry.correction}.{evidence}{source}"
        )
    return "\n".join(lines)


def feedback_context_for(
    *,
    ticker: str,
    agents: Iterable[str],
    trade_date: str = "",
    limit: int = 8,
    path: str | Path | None = None,
) -> str:
    return format_feedback_context(
        relevant_feedback(
            ticker=ticker,
            agents=agents,
            trade_date=trade_date,
            limit=limit,
            path=path,
        )
    )


def _normalize_ticker(value: str) -> str:
    cleaned = value.strip().upper()
    return cleaned or "*"


def _normalize_agent(value: str) -> str:
    return value.strip().lower() or "all"


def _clean_text(value: str, max_chars: int) -> str:
    cleaned = " ".join(value.replace("\r", " ").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip() + "..."
