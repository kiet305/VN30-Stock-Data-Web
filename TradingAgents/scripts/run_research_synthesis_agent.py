from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.llm_runtime import (
    apply_llm_runtime_defaults,
    build_llm_kwargs,
)
from scripts.human_feedback import feedback_context_for


REPORT_KINDS = ("market", "fundamentals", "sentiment", "news")
RATING_LEVELS = ("Strong Bull", "Slightly Bull", "Neutral", "Slightly Bear", "Strong Bear")
PORTAL_REPORTS_DIR_ENV = "TRADINGAGENTS_PORTAL_REPORTS_DIR"


@dataclass
class AnalystReport:
    kind: str
    content: str
    path: Path | None
    trace: str


@dataclass
class DebateDecision:
    winner: str = "Tie"
    confidence: str = "low"
    continue_debate: bool = True
    reason: str = ""
    bull_gaps: list[str] = field(default_factory=list)
    bear_gaps: list[str] = field(default_factory=list)
    next_instruction_for_bull: str = ""
    next_instruction_for_bear: str = ""


@dataclass
class DebateRound:
    round_no: int
    bull_case: str
    bear_case: str
    decision: DebateDecision


class ResearchFlowError(RuntimeError):
    pass


ProgressLogger = Callable[[str], None]


def _progress(progress: ProgressLogger | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _portal_reports_dir() -> Path | None:
    configured = os.environ.get(PORTAL_REPORTS_DIR_ENV)
    if configured:
        return Path(configured)
    if os.name == "nt":
        default_dir = Path(r"C:\tradingagents-reports")
        if default_dir.exists():
            return default_dir
    return None


def mirror_report_to_portal(path: Path) -> Path | None:
    portal_dir = _portal_reports_dir()
    if portal_dir is None:
        return None
    portal_dir.mkdir(parents=True, exist_ok=True)
    target = portal_dir / path.name
    try:
        if path.resolve() == target.resolve():
            return target
    except OSError:
        if str(path.absolute()) == str(target.absolute()):
            return target
    shutil.copy2(path, target)
    return target


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


def _load_runtime_env() -> None:
    repo_root = _repo_root()
    for candidate in (
        repo_root / ".env",
        repo_root.parent / ".env",
    ):
        _load_env_file(candidate)


def _safe_read(path: Path, max_chars: int = 20000) -> str:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n[Truncated for research synthesis]"


def _plain_log_excerpt(text: str, max_chars: int = 260) -> str:
    cleaned = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"<script[\s\S]*?</script>", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"[*_`>#|]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:\t")
    if not cleaned:
        return "Chưa có nội dung đủ rõ để tóm tắt."
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "..."


def _short_tool_trace(trace: str, max_items: int = 4, max_chars: int = 300) -> str:
    parts = [part.strip() for part in trace.split(";") if part.strip()]
    tool_parts = [part for part in parts if "(" in part and ")" in part]
    if not tool_parts:
        return ""
    names = []
    for part in tool_parts[:max_items]:
        name = part.split("(", 1)[0].strip()
        args = part.split("(", 1)[1].rsplit(")", 1)[0]
        if len(args) > 58:
            args = args[:57].rstrip() + "..."
        names.append(f"{name}({args})")
    summary = ", ".join(names)
    if len(tool_parts) > max_items:
        summary += f", +{len(tool_parts) - max_items} bước"
    if len(summary) > max_chars:
        summary = summary[: max_chars - 1].rstrip() + "..."
    return summary


def _log_report_output(
    progress: ProgressLogger | None,
    kind: str,
    report: AnalystReport,
    prefix: str = "output",
) -> None:
    path_label = report.path.name if report.path else "chưa có file output"
    word_count = len(re.findall(r"\S+", report.content))
    _progress(
        progress,
        f"[{prefix}][{kind}] Đã tạo {path_label}: {word_count} từ, {len(report.content):,} ký tự.",
    )
    _progress(progress, f"[{prefix}][{kind}] Nội dung chính: {_plain_log_excerpt(report.content)}")
    trace_summary = _short_tool_trace(report.trace)
    if trace_summary:
        _progress(progress, f"[tools][{kind}] Công cụ/dữ liệu đã gọi: {trace_summary}")


def _report_patterns(ticker: str, kind: str, trade_date: str | None) -> list[str]:
    ticker = ticker.upper()
    dated: list[str] = []
    if trade_date:
        dated = [
            f"{ticker}_{kind}_analysis_main_{trade_date}.md",
            f"{ticker}_{kind}_llm_google_{trade_date}.md",
            f"{ticker}_{kind}_llm_*_{trade_date}.md",
            f"{ticker}_{kind}_social_main_{trade_date}.md",
            f"{ticker}_{kind}_analysis_{trade_date}.md",
        ]
    fallback = {
        "market": [
            f"{ticker}_market_analysis_main_*.md",
            f"{ticker}_market_llm_google_*.md",
            f"{ticker}_market_llm_*_*.md",
            f"{ticker}_market_analysis_*.md",
        ],
        "news": [
            f"{ticker}_news_analysis_main_*.md",
            f"{ticker}_news_llm_google_*.md",
            f"{ticker}_news_llm_*_*.md",
        ],
        "fundamentals": [
            f"{ticker}_fundamentals_analysis_main_*.md",
            f"{ticker}_fundamentals_llm_google_*.md",
            f"{ticker}_fundamentals_llm_*_*.md",
        ],
        "sentiment": [
            f"{ticker}_sentiment_social_main_*.md",
            f"MARKET_sentiment_social_main_*.md",
        ],
    }[kind]
    return dated + fallback


def _find_latest_report(ticker: str, kind: str, trade_date: str | None = None) -> Path | None:
    reports_dir = _repo_root() / "reports"
    for pattern in _report_patterns(ticker, kind, trade_date):
        candidates = [path for path in reports_dir.glob(pattern) if path.is_file()]
        if candidates:
            return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]
    return None


def _collect_report_from_file(ticker: str, kind: str, trade_date: str | None) -> AnalystReport:
    path = _find_latest_report(ticker, kind, trade_date)
    if path is None:
        return AnalystReport(
            kind=kind,
            content=f"No {kind} analyst report was found in TradingAgents/reports.",
            path=None,
            trace=f"{kind}:missing_report",
        )
    return AnalystReport(
        kind=kind,
        content=_safe_read(path),
        path=path,
        trace=f"{kind}:loaded_report({path.name})",
    )


def _collect_sentiment_report(
    ticker: str,
    trade_date: str,
    model: str,
    look_back_days: int,
    social_path: str | None,
    provider: str,
    feedback_context: str = "",
) -> AnalystReport:
    from scripts.run_sentiment_llm_agent import run_sentiment_agent

    report, trace, resolved_date = run_sentiment_agent(
        ticker=ticker,
        trade_date=trade_date,
        model=model,
        look_back_days=look_back_days,
        social_path=social_path,
        provider=provider,
        feedback_context=feedback_context,
    )
    output_path = _repo_root() / "reports" / f"{ticker}_sentiment_social_main_{resolved_date}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    mirror_report_to_portal(output_path)
    return AnalystReport(
        kind="sentiment",
        content=report,
        path=output_path,
        trace=f"sentiment:ran(output={output_path.name}; " + "; ".join(trace) + ")",
    )


def _save_agent_report(
    ticker: str,
    kind: str,
    trade_date: str,
    provider: str,
    report: str,
) -> Path:
    filename_kind = {
        "market": f"market_llm_{provider}",
        "news": f"news_llm_{provider}",
        "fundamentals": f"fundamentals_llm_{provider}",
    }[kind]
    output_path = _repo_root() / "reports" / f"{ticker}_{filename_kind}_{trade_date}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    mirror_report_to_portal(output_path)
    return output_path


def _run_tool_calling_report(
    ticker: str,
    kind: str,
    trade_date: str,
    model: str,
    max_steps: int,
    provider: str,
    feedback_context: str = "",
) -> AnalystReport:
    from scripts.run_fundamentals_llm_agent import run_fundamentals_agent
    from scripts.run_market_llm_agent import run_market_agent
    from scripts.run_news_llm_agent import run_news_agent

    runner = {
        "market": run_market_agent,
        "news": run_news_agent,
        "fundamentals": run_fundamentals_agent,
    }[kind]
    report, trace = runner(
        ticker=ticker,
        trade_date=trade_date,
        model=model,
        max_steps=max_steps,
        provider=provider,
        feedback_context=feedback_context,
    )
    output_path = _save_agent_report(ticker, kind, trade_date, provider, report)
    return AnalystReport(
        kind=kind,
        content=report,
        path=output_path,
        trace=f"{kind}:ran(output={output_path.name}; " + "; ".join(trace) + ")",
    )


def _collect_analyst_reports(
    ticker: str,
    trade_date: str,
    model: str,
    max_steps: int,
    look_back_days: int,
    social_path: str | None,
    provider: str,
    feedback_path: str | None = None,
    progress: ProgressLogger | None = None,
    reuse_existing: bool = False,
) -> dict[str, AnalystReport]:
    if reuse_existing:
        reports = {}
        missing = []
        _progress(progress, "[analyst] Đang tái dùng analyst reports có sẵn trong thư mục reports/.")
        for index, kind in enumerate(REPORT_KINDS, start=1):
            report = _collect_report_from_file(ticker, kind, trade_date)
            reports[kind] = report
            if report.path is None:
                missing.append(kind)
                _progress(progress, f"[analyst][{index}/4 {kind}] Không tìm thấy report có sẵn.")
            else:
                _progress(progress, f"[analyst][{index}/4 {kind}] Đã load {report.path.name}.")
                _log_report_output(progress, kind, report, prefix="reuse")
        if missing:
            raise ResearchFlowError(
                "Không thể dùng --reuse-analyst-reports vì thiếu report: "
                + ", ".join(missing)
                + ". Chạy lại không có flag này để tạo đủ analyst reports."
            )
        return reports

    reports = {}
    for index, kind in enumerate(REPORT_KINDS, start=1):
        start = time.monotonic()
        _progress(progress, f"[analyst][{index}/4 {kind}] Bắt đầu chạy analyst report...")
        feedback_context = _agent_feedback_context(ticker, trade_date, kind, feedback_path)
        if kind == "sentiment":
            reports[kind] = _collect_sentiment_report(
                ticker=ticker,
                trade_date=trade_date,
                model=model,
                look_back_days=look_back_days,
                social_path=social_path,
                provider=provider,
                feedback_context=feedback_context,
            )
            elapsed = time.monotonic() - start
            output_name = reports[kind].path.name if reports[kind].path else "no_output_file"
            _progress(progress, f"[analyst][{index}/4 {kind}] Xong sau {elapsed:.1f}s: {output_name}.")
            _log_report_output(progress, kind, reports[kind])
            continue
        reports[kind] = _run_tool_calling_report(
            ticker=ticker,
            kind=kind,
            trade_date=trade_date,
            model=model,
            max_steps=max_steps,
            provider=provider,
            feedback_context=feedback_context,
        )
        elapsed = time.monotonic() - start
        output_name = reports[kind].path.name if reports[kind].path else "no_output_file"
        _progress(progress, f"[analyst][{index}/4 {kind}] Xong sau {elapsed:.1f}s: {output_name}.")
        _log_report_output(progress, kind, reports[kind])
    return reports


def _agent_feedback_context(
    ticker: str,
    trade_date: str,
    agent: str,
    feedback_path: str | None,
) -> str:
    return feedback_context_for(
        ticker=ticker,
        trade_date=trade_date,
        agents=(agent, "analyst", "all"),
        path=feedback_path,
    )


def _extract_signal_lines(text: str, keywords: tuple[str, ...], limit: int = 8) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if (
            not line
            or line.startswith("|")
            or line.startswith("#")
            or "final transaction proposal" in line.lower()
        ):
            continue
        lower = line.lower()
        if any(keyword in lower for keyword in keywords):
            cleaned = re.sub(r"\s+", " ", line).lstrip("- ").strip()
            if cleaned not in lines:
                lines.append(cleaned[:360])
        if len(lines) >= limit:
            break
    return lines


def _extract_overview_lines(text: str, limit: int = 5) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line.strip())
        if (
            not line
            or line.startswith("|")
            or "final transaction proposal" in line.lower()
        ):
            continue
        if line.startswith("#") and len(lines) >= 2:
            continue
        if line not in lines:
            lines.append(line[:360])
        if len(lines) >= limit:
            break
    return lines


def _recommendation_lines(text: str) -> list[str]:
    match = re.search(r"final transaction proposal:\s*\*\*(buy|hold|sell)\*\*", text, re.IGNORECASE)
    if not match:
        return []
    value = match.group(1).upper()
    meaning = {
        "BUY": "nghiêng tích cực",
        "HOLD": "thiên về trung tính/thận trọng",
        "SELL": "nghiêng tiêu cực",
    }[value]
    return [f"Khuyến nghị nền từ report là **{value}**, tức {meaning}."]


def _bullet_list(lines: list[str], fallback: str, fallback_lines: list[str] | None = None) -> str:
    if not lines:
        overview = fallback_lines or []
        if overview:
            return "\n".join([f"- {fallback}", *[f"- {line}" for line in overview]])
        return f"- {fallback}"
    return "\n".join(f"- {line}" for line in lines)


def _kind_label(kind: str) -> str:
    return {
        "market": "Market Analysis",
        "news": "News Analysis",
        "fundamentals": "Fundamental Analysis",
        "sentiment": "Sentiment Analysis",
    }[kind]


def _count_matches(text: str, terms: tuple[str, ...]) -> int:
    lower = text.lower()
    return sum(lower.count(term) for term in terms)


def _score_report_text(text: str) -> float:
    lower = text.lower()
    score = 0.0

    proposal = re.search(r"final transaction proposal:\s*\*\*(buy|hold|sell)\*\*", lower)
    proposal_value = proposal.group(1) if proposal else None
    if proposal:
        score += {"buy": 1.5, "hold": 0.0, "sell": -1.5}[proposal_value]

    score_match = re.search(r"overall score:\s*\*\*([0-9]+(?:\.[0-9]+)?)/10\*\*", lower)
    if score_match:
        value = float(score_match.group(1))
        if value >= 7.5:
            score += 1.25
        elif value >= 6:
            score += 0.6
        elif value <= 2.5:
            score -= 1.25
        elif value <= 4:
            score -= 0.6

    positive_terms = (
        "bullish",
        "strong bull",
        "buy",
        "positive",
        "tich cuc",
        "tích cực",
        "tang truong",
        "tăng trưởng",
        "cai thien",
        "cải thiện",
        "support",
        "uptrend",
    )
    negative_terms = (
        "bearish",
        "strong bear",
        "sell",
        "negative",
        "tieu cuc",
        "tiêu cực",
        "rui ro",
        "rủi ro",
        "suy giam",
        "suy giảm",
        "resistance",
        "downtrend",
    )
    positive_count = _count_matches(lower, positive_terms)
    negative_count = _count_matches(lower, negative_terms)
    score += max(min((positive_count - negative_count) * 0.08, 1.0), -1.0)
    if proposal_value == "hold":
        score = max(min(score, 0.35), -0.35)
    return score


def _rating_from_score(score: float) -> str:
    if score >= 4.0:
        return "Strong Bull"
    if score >= 0.6:
        return "Slightly Bull"
    if score <= -4.0:
        return "Strong Bear"
    if score <= -0.6:
        return "Slightly Bear"
    return "Neutral"


def _rating_explanation(rating: str) -> str:
    if rating == "Strong Bull":
        return "Tín hiệu thuận lợi chiếm ưu thế rõ ràng trên nhiều nhóm phân tích."
    if rating == "Slightly Bull":
        return "Luận điểm tích cực đang nhỉnh hơn, nhưng vẫn cần xác nhận thêm từ giá, volume hoặc catalyst mới."
    if rating == "Slightly Bear":
        return "Rủi ro đang nhỉnh hơn cơ hội, phù hợp với cách tiếp cận thận trọng hoặc giảm quy mô vị thế."
    if rating == "Strong Bear":
        return "Tín hiệu bất lợi chiếm ưu thế rõ ràng, chưa phù hợp để ưu tiên vị thế mua."
    return "Tín hiệu hai chiều còn cân bằng hoặc chưa đủ mạnh để nghiêng hẳn về bull/bear."


def _overall_rating(reports: dict[str, AnalystReport]) -> tuple[str, float, str]:
    score = sum(_score_report_text(reports[kind].content) for kind in REPORT_KINDS)
    rating = _rating_from_score(score)
    return rating, score, _rating_explanation(rating)


def _clean_report_line(line: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", line)
    cleaned = re.sub(r"[*_`>#|]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:\t")
    return cleaned


def _extract_main_thesis(case_text: str, side: str) -> str:
    side_lower = side.lower()
    for raw_line in case_text.splitlines():
        line = _clean_report_line(raw_line)
        if not line:
            continue
        lower = line.lower()
        if side_lower in lower and "researcher" in lower:
            continue
        if "luận điểm cốt lõi" in lower or "luan diem cot loi" in lower:
            continue
        if len(line) >= 60:
            return line[:320]
    fallback = {
        "bull": "Luận điểm Bull tập trung vào các yếu tố ủng hộ khả năng nắm giữ hoặc mở vị thế.",
        "bear": "Luận điểm Bear tập trung vào các rủi ro có thể khiến vị thế mua kém hấp dẫn.",
    }
    return fallback.get(side_lower, "Luận điểm chính chưa đủ dữ liệu để tóm tắt.")


def _score_bar(score: float, max_abs: float = 3.0) -> str:
    clipped = max(min(score, max_abs), -max_abs)
    width = int(round(abs(clipped) / max_abs * 100))
    color = "#1f8a4c" if clipped > 0.15 else "#b83232" if clipped < -0.15 else "#6b7280"
    return (
        '<div style="height:8px;background:#e5e7eb;border-radius:999px;overflow:hidden;min-width:90px">'
        f'<div style="height:8px;width:{width}%;background:{color};border-radius:999px"></div>'
        "</div>"
    )


def _analyst_signal_rows(
    reports: dict[str, AnalystReport],
    overall_rating: str,
    overall_signal: str,
) -> str:
    rows: list[str] = []
    for kind in REPORT_KINDS:
        score = _score_report_text(reports[kind].content)
        rating = _rating_from_score(score)
        rows.append(
            "<tr>"
            f"<td>{html.escape(_kind_label(kind))}</td>"
            f"<td>{html.escape(rating)}</td>"
            f"<td>{html.escape(_rating_explanation(rating))}</td>"
            "</tr>"
        )
    rows.append(
        "<tr>"
        "<td><strong>Tổng hợp</strong></td>"
        f"<td><strong>{html.escape(overall_rating)}</strong></td>"
        f"<td>{html.escape(overall_signal)}</td>"
        "</tr>"
    )
    return "\n".join(rows)


def _summary_dashboard(
    ticker: str,
    trade_date: str | None,
    rating: str,
    score: float,
    explanation: str,
    reports: dict[str, AnalystReport],
    bull_case: str,
    bear_case: str,
) -> str:
    bull_thesis = _extract_main_thesis(bull_case, "bull")
    bear_thesis = _extract_main_thesis(bear_case, "bear")
    date_value = trade_date or "N/A"
    return f"""
<section class="report-dashboard">
  <h1>Tổng hợp Bull/Bear: {html.escape(ticker.upper())}</h1>
  <p><strong>Ngày phân tích:</strong> {html.escape(date_value)}</p>

  <table>
    <caption>Luận điểm chính và đường dẫn chi tiết</caption>
    <thead>
      <tr>
        <th>Phe</th>
        <th>Luận điểm chính</th>
        <th>Trọng tâm</th>
        <th>Chi tiết</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>Bull</strong></td>
        <td>{html.escape(bull_thesis)}</td>
        <td>Cơ hội / yếu tố hỗ trợ</td>
        <td><a href="#luan-diem-chi-tiet-bull">Xem luận điểm Bull</a></td>
      </tr>
      <tr>
        <td><strong>Bear</strong></td>
        <td>{html.escape(bear_thesis)}</td>
        <td>Rủi ro / yếu tố phản biện</td>
        <td><a href="#luan-diem-chi-tiet-bear">Xem luận điểm Bear</a></td>
      </tr>
    </tbody>
  </table>

  <table>
    <caption>Bảng tín hiệu tổng hợp từ 4 agent analysis</caption>
    <thead>
      <tr>
        <th>Agent</th>
        <th>Nghiêng về</th>
        <th>Tín hiệu tổng hợp</th>
      </tr>
    </thead>
    <tbody>
      {_analyst_signal_rows(reports, rating, explanation)}
    </tbody>
  </table>

  <table>
    <caption>Kết luận tổng quan</caption>
    <tbody>
      <tr>
        <th>Mức độ tổng</th>
        <td><strong>{html.escape(rating)}</strong></td>
      </tr>
      <tr>
        <th>Diễn giải</th>
        <td>{html.escape(explanation)}</td>
      </tr>
      <tr>
        <th>Thang đánh giá</th>
        <td>Strong Bull / Slightly Bull / Neutral / Slightly Bear / Strong Bear</td>
      </tr>
    </tbody>
  </table>
</section>
""".strip()


def _deterministic_bull_case(ticker: str, reports: dict[str, AnalystReport]) -> str:
    positive_keywords = (
        "bull",
        "positive",
        "tich cuc",
        "growth",
        "support",
        "buy",
        "strong",
        "uptrend",
        "score",
        "attention",
        "revenue",
        "profit",
        "margin",
    )
    sections = []
    for kind in REPORT_KINDS:
        lines = _extract_signal_lines(reports[kind].content, positive_keywords)
        overview = _recommendation_lines(reports[kind].content) + _extract_overview_lines(reports[kind].content)
        sections.append(
            f"### {_kind_label(kind)}\n"
            f"{_bullet_list(lines, 'Các điểm chính cần cân nhắc từ nhóm phân tích này:', overview)}"
        )
    return "\n\n".join(
        [
            f"# Bull Researcher: {ticker.upper()}",
            "## 1. Luận Điểm Cốt Lõi",
            (
                "Bull case tập trung vào các bằng chứng ủng hộ khả năng nắm giữ hoặc mở vị thế "
                "khi market, news, fundamentals và sentiment không mâu thuẫn nghiêm trọng."
            ),
            "## 2. Bằng Chứng Theo 4 Nhóm",
            *sections,
            "## 3. Phản Biện Luận Điểm Bear",
            (
                "Các điểm bất lợi cần được xem là cảnh báo, nhưng chưa đủ để bác bỏ bull case "
                "nếu chúng không đi kèm suy yếu rõ ràng về giá, thanh khoản, lợi nhuận hoặc catalyst tin tức."
            ),
            "## 4. Điều Kiện Vô Hiệu Hóa Bull Case",
            "- Giá phá vỡ vùng hỗ trợ quan trọng với thanh khoản tăng.\n"
            "- Tin tức hoặc kết quả kinh doanh mới làm suy yếu giả thuyết tăng trưởng.\n"
            "- Sentiment tích cực nhưng giá không xác nhận, tạo rủi ro crowded trade.",
            "## 5. Kết Luận Bull",
            (
                "Luận điểm bull có thể đứng vững nếu các nhóm tín hiệu tiếp tục không phủ định lẫn nhau. "
                "Nếu vào lệnh, nên ưu tiên quy mô vừa phải và đợi xác nhận từ giá/volume."
            ),
        ]
    )


def _deterministic_bear_case(ticker: str, reports: dict[str, AnalystReport], bull_case: str) -> str:
    negative_keywords = (
        "bear",
        "negative",
        "tieu cuc",
        "risk",
        "weak",
        "sell",
        "down",
        "resistance",
        "overbought",
        "debt",
        "decline",
        "limitation",
        "uncertain",
        "caution",
    )
    sections = []
    for kind in REPORT_KINDS:
        lines = _extract_signal_lines(reports[kind].content, negative_keywords)
        overview = _recommendation_lines(reports[kind].content) + _extract_overview_lines(reports[kind].content)
        sections.append(
            f"### {_kind_label(kind)}\n"
            f"{_bullet_list(lines, 'Các điểm rủi ro hoặc bối cảnh cần cân nhắc từ nhóm phân tích này:', overview)}"
        )
    return "\n\n".join(
        [
            f"# Bear Researcher: {ticker.upper()}",
            "## 1. Luận Điểm Cốt Lõi",
            (
                "Bear case tập trung vào các rủi ro có thể khiến việc mua hoặc nắm giữ kém hấp dẫn: "
                "tín hiệu chưa đủ xác nhận, catalyst không chắc chắn, chu kỳ ngành, hoặc sentiment quá đông."
            ),
            "## 2. Bằng Chứng Theo 4 Nhóm",
            *sections,
            "## 3. Phản Biện Luận Điểm Bull",
            (
                "Bull case yếu nhất khi xem attention, narrative hoặc sức mạnh quá khứ như bằng chứng chắc chắn "
                "cho lợi nhuận tương lai. Bear case yêu cầu xác nhận từ xu hướng giá, thanh khoản, chất lượng "
                "lợi nhuận và catalyst mới trước khi chấp nhận vị thế long."
            ),
            "## 4. Điều Kiện Vô Hiệu Hóa Bear Case",
            "- Giá vượt kháng cự với thanh khoản thuyết phục.\n"
            "- Tin tức và fundamentals cùng xác nhận cải thiện lợi nhuận/dòng tiền.\n"
            "- Sentiment tích cực đi kèm dòng tiền thật, không chỉ là mức độ chú ý.",
            "## 5. Kết Luận Bear",
            (
                "Bear case ủng hộ sự thận trọng nếu các báo cáo còn mixed, thiếu dữ liệu mới, "
                "hoặc tín hiệu tích cực chưa được giá và volume xác nhận."
            ),
        ]
    )


def _build_research_prompt(
    ticker: str,
    reports: dict[str, AnalystReport],
    side: str,
    opponent: str = "",
    feedback_context: str = "",
    debate_context: str = "",
) -> str:
    analyst_context = "\n\n".join(
        [
            f"## {_kind_label(kind)}\n\n{reports[kind].content}"
            for kind in REPORT_KINDS
        ]
    )
    opponent_block = f"\n\nOpponent argument to address:\n{opponent}" if opponent else ""
    debate_block = ""
    if debate_context:
        debate_block = f"""

Debate context and coordinator guidance:
{debate_context}

Use this context to strengthen your next argument. Address only material weaknesses and avoid repeating points already answered.
"""
    feedback_block = ""
    if feedback_context:
        feedback_block = f"""

Human correction memory:
{feedback_context}

Apply these corrections when building the {side} case. Do not repeat prior mistakes unless the current evidence proves the correction no longer applies.
"""
    return f"""You are the {side} Researcher in a TradingAgents research team for ticker {ticker.upper()}.

Use only the four analyst reports below. Write in Vietnamese.

Do not include file paths, source tables, tool traces, or implementation details.

Return the report exactly in this structure:

# {side} Researcher: {ticker.upper()}
## 1. Luận Điểm Cốt Lõi
State the core {side.lower()} thesis in 3-5 concise sentences.

## 2. Bằng Chứng Theo 4 Nhóm
### Market Analysis
List the strongest points from market/technical analysis.
### News Analysis
List the strongest points from news flow.
### Fundamental Analysis
List the strongest points from fundamentals.
### Sentiment Analysis
List the strongest points from social/sentiment.

## 3. Phản Biện Luận Điểm Đối Lập
Directly address the opponent thesis or the most likely counterargument.

## 4. Điều Kiện Vô Hiệu Hóa Luận Điểm
List 3-5 concrete conditions that would make this {side.lower()} case wrong.

## 5. Kết Luận {side}
Give a clear closing stance for this side only.

Rules:
- Make the argument complete enough to be read independently.
- Separate evidence from interpretation.
- Mention uncertainty and data gaps when relevant.
- Use labels "Market Analysis", "News Analysis", "Fundamental Analysis", and "Sentiment Analysis".
- Do not mention local filenames, source paths, traces, tools, or fallback behavior.
{opponent_block}
{debate_block}
{feedback_block}

<analyst_reports>
{analyst_context}
</analyst_reports>
"""


def _try_llm_research_case(
    ticker: str,
    reports: dict[str, AnalystReport],
    model: str,
    side: str,
    provider: str,
    opponent: str = "",
    feedback_context: str = "",
    debate_context: str = "",
) -> str | None:

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.llm_clients import create_llm_client

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
        messages = [
            SystemMessage(
                content=_build_research_prompt(
                    ticker,
                    reports,
                    side,
                    opponent,
                    feedback_context=feedback_context,
                    debate_context=debate_context,
                )
            ),
            HumanMessage(content=f"Produce the {side} Researcher argument for {ticker.upper()}."),
        ]
        response = llm.invoke(messages)
        text = str(response.content).strip()
        if text and len(text) < 60000 and not any(len(line) > 6000 for line in text.splitlines()):
            return f"# {side} Researcher Argument: {ticker.upper()}\n\n{text}"
    except Exception:
        return None
    return None


def _research_case(
    ticker: str,
    reports: dict[str, AnalystReport],
    model: str,
    side: str,
    provider: str,
    opponent: str = "",
    feedback_context: str = "",
    debate_context: str = "",
) -> tuple[str, str]:
    llm_case = _try_llm_research_case(
        ticker,
        reports,
        model,
        side,
        provider,
        opponent,
        feedback_context=feedback_context,
        debate_context=debate_context,
    )
    if llm_case:
        return llm_case, f"{side.lower()}:llm"
    if side.lower() == "bull":
        return _deterministic_bull_case(ticker, reports), "bull:deterministic_fallback"
    return _deterministic_bear_case(ticker, reports, opponent), "bear:deterministic_fallback"


def _build_debate_context(rounds: list[DebateRound]) -> str:
    if not rounds:
        return ""
    last = rounds[-1]
    blocks = [
        "Previous debate summary:",
        _debate_round_summary(last),
        "",
        f"Coordinator winner so far: {last.decision.winner} ({last.decision.confidence}).",
        f"Coordinator reason: {last.decision.reason or 'No reason provided.'}",
    ]
    if last.decision.next_instruction_for_bull:
        blocks.append(f"Instruction for Bull: {last.decision.next_instruction_for_bull}")
    if last.decision.next_instruction_for_bear:
        blocks.append(f"Instruction for Bear: {last.decision.next_instruction_for_bear}")
    return "\n".join(blocks)


def _debate_round_summary(round_item: DebateRound, max_chars: int = 2400) -> str:
    return "\n".join(
        [
            f"Round {round_item.round_no}",
            "Bull argument:",
            _truncate_for_prompt(round_item.bull_case, max_chars),
            "Bear argument:",
            _truncate_for_prompt(round_item.bear_case, max_chars),
        ]
    )


def _debate_transcript(rounds: list[DebateRound], current_bull: str, current_bear: str) -> str:
    blocks = [_debate_round_summary(item, max_chars=1600) for item in rounds[-2:]]
    blocks.append(
        "\n".join(
            [
                f"Round {len(rounds) + 1}",
                "Bull argument:",
                _truncate_for_prompt(current_bull, 3000),
                "Bear argument:",
                _truncate_for_prompt(current_bear, 3000),
            ]
        )
    )
    return "\n\n".join(blocks)


def _analyst_context_for_coordinator(reports: dict[str, AnalystReport]) -> str:
    sections = []
    for kind in REPORT_KINDS:
        overview = "\n".join(_extract_overview_lines(reports[kind].content, limit=8))
        sections.append(f"## {_kind_label(kind)}\n{overview or _truncate_for_prompt(reports[kind].content, 1200)}")
    return "\n\n".join(sections)


def _build_coordinator_prompt(
    ticker: str,
    reports: dict[str, AnalystReport],
    rounds: list[DebateRound],
    current_bull: str,
    current_bear: str,
    round_no: int,
    max_rounds: int,
) -> str:
    return f"""You are the Debate Coordinator for the TradingAgents Bull/Bear research team.

Task:
- Evaluate the debate for ticker {ticker.upper()} after round {round_no} of {max_rounds}.
- Bull always argues first, Bear responds second.
- Decide whether Bull, Bear, or neither side is currently winning based only on evidence quality, directness of rebuttals, data support, uncertainty handling, and logical consistency.
- Do not reward repeated claims without stronger evidence.
- If the winner is clear with high confidence, stop the debate. Otherwise continue until max_rounds is reached.

Return only compact JSON with this exact schema:
{{
  "winner": "Bull|Bear|Tie",
  "confidence": "low|medium|high",
  "continue_debate": true,
  "reason": "short Vietnamese explanation",
  "bull_gaps": ["missing or weak Bull point"],
  "bear_gaps": ["missing or weak Bear point"],
  "next_instruction_for_bull": "what Bull must address next",
  "next_instruction_for_bear": "what Bear must address next"
}}

Analyst context:
{_analyst_context_for_coordinator(reports)}

Debate transcript:
{_debate_transcript(rounds, current_bull, current_bear)}
"""


def _try_llm_coordinator_decision(
    ticker: str,
    reports: dict[str, AnalystReport],
    rounds: list[DebateRound],
    current_bull: str,
    current_bear: str,
    round_no: int,
    max_rounds: int,
    model: str,
    provider: str,
) -> DebateDecision | None:
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.llm_clients import create_llm_client

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
        response = llm.invoke(
            [
                SystemMessage(
                    content=_build_coordinator_prompt(
                        ticker,
                        reports,
                        rounds,
                        current_bull,
                        current_bear,
                        round_no,
                        max_rounds,
                    )
                ),
                HumanMessage(content="Judge this debate round and return only JSON."),
            ]
        )
        return _parse_coordinator_decision(str(response.content), round_no, max_rounds)
    except Exception:
        return None


def _coordinator_decision(
    ticker: str,
    reports: dict[str, AnalystReport],
    rounds: list[DebateRound],
    current_bull: str,
    current_bear: str,
    round_no: int,
    max_rounds: int,
    model: str,
    provider: str,
) -> tuple[DebateDecision, str]:
    decision = _try_llm_coordinator_decision(
        ticker=ticker,
        reports=reports,
        rounds=rounds,
        current_bull=current_bull,
        current_bear=current_bear,
        round_no=round_no,
        max_rounds=max_rounds,
        model=model,
        provider=provider,
    )
    if decision is None:
        decision = _deterministic_coordinator_decision(
            reports=reports,
            round_no=round_no,
            max_rounds=max_rounds,
        )
        return decision, f"coordinator:deterministic_fallback(round={round_no}; winner={decision.winner})"
    return decision, f"coordinator:llm(round={round_no}; winner={decision.winner}; confidence={decision.confidence})"


def _parse_coordinator_decision(text: str, round_no: int, max_rounds: int) -> DebateDecision:
    payload = _extract_json_object(text)
    winner = _clean_winner(str(payload.get("winner", "Tie")))
    confidence = _clean_confidence(str(payload.get("confidence", "low")))
    continue_debate = bool(payload.get("continue_debate", True))
    if round_no >= max_rounds:
        continue_debate = False
    elif winner in {"Bull", "Bear"} and confidence == "high":
        continue_debate = False
    else:
        continue_debate = True
    return DebateDecision(
        winner=winner,
        confidence=confidence,
        continue_debate=continue_debate,
        reason=_clean_report_line(str(payload.get("reason", "")))[:500],
        bull_gaps=_clean_string_list(payload.get("bull_gaps", [])),
        bear_gaps=_clean_string_list(payload.get("bear_gaps", [])),
        next_instruction_for_bull=_clean_report_line(str(payload.get("next_instruction_for_bull", "")))[:500],
        next_instruction_for_bear=_clean_report_line(str(payload.get("next_instruction_for_bear", "")))[:500],
    )


def _extract_json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


def _clean_winner(value: str) -> str:
    lowered = value.strip().lower()
    if lowered == "bull":
        return "Bull"
    if lowered == "bear":
        return "Bear"
    return "Tie"


def _clean_confidence(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"low", "medium", "high"}:
        return lowered
    return "low"


def _clean_string_list(value: object, limit: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        text = _clean_report_line(str(item))[:260]
        if text:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _deterministic_coordinator_decision(
    reports: dict[str, AnalystReport],
    round_no: int,
    max_rounds: int,
) -> DebateDecision:
    rating, score, explanation = _overall_rating(reports)
    if rating in {"Strong Bull", "Slightly Bull"}:
        winner = "Bull"
        confidence = "high" if rating == "Strong Bull" else "medium"
    elif rating in {"Strong Bear", "Slightly Bear"}:
        winner = "Bear"
        confidence = "high" if rating == "Strong Bear" else "medium"
    else:
        winner = "Tie"
        confidence = "medium"
    continue_debate = round_no < max_rounds and not (winner in {"Bull", "Bear"} and confidence == "high")
    return DebateDecision(
        winner=winner,
        confidence=confidence,
        continue_debate=continue_debate,
        reason=f"{explanation} Điểm tổng hợp heuristic: {score:.2f}.",
        bull_gaps=["Cần chứng minh catalyst hoặc xác nhận giá/volume rõ hơn."],
        bear_gaps=["Cần lượng hóa rủi ro và điều kiện phá vỡ bull case rõ hơn."],
        next_instruction_for_bull="Tập trung vào bằng chứng mới hoặc xác nhận trực tiếp từ dữ liệu analyst.",
        next_instruction_for_bear="Tập trung vào phản biện các giả định yếu và điều kiện vô hiệu hóa bull case.",
    )


def _run_research_debate(
    ticker: str,
    reports: dict[str, AnalystReport],
    model: str,
    provider: str,
    debate_rounds: int,
    bull_feedback: str,
    bear_feedback: str,
    progress: ProgressLogger | None = None,
) -> tuple[str, str, list[DebateRound], list[str]]:
    max_rounds = max(1, debate_rounds)
    rounds: list[DebateRound] = []
    trace: list[str] = []
    bull_case = ""
    bear_case = ""
    _progress(progress, f"[debate] Bắt đầu tranh luận Bull/Bear cho {ticker.upper()} ({max_rounds} vòng tối đa).")
    for round_no in range(1, max_rounds + 1):
        _progress(progress, f"[debate][vòng {round_no}/{max_rounds}] Bull Researcher đang lập luận...")
        debate_context = _build_debate_context(rounds)
        bull_opponent = bear_case if round_no > 1 else ""
        bull_case, bull_trace = _research_case(
            ticker,
            reports,
            model,
            "Bull",
            provider,
            opponent=bull_opponent,
            feedback_context=bull_feedback,
            debate_context=debate_context,
        )
        trace.append(f"round_{round_no}:{bull_trace}")
        _progress(
            progress,
            f"[debate][vòng {round_no}/{max_rounds}] Bull xong ({bull_trace}, {len(bull_case):,} ký tự).",
        )
        _progress(progress, f"[debate][vòng {round_no}/{max_rounds}] Bull preview: {_plain_log_excerpt(bull_case)}")

        _progress(progress, f"[debate][vòng {round_no}/{max_rounds}] Bear Researcher đang phản biện Bull...")
        bear_case, bear_trace = _research_case(
            ticker,
            reports,
            model,
            "Bear",
            provider,
            opponent=bull_case,
            feedback_context=bear_feedback,
            debate_context=debate_context,
        )
        trace.append(f"round_{round_no}:{bear_trace}")
        _progress(
            progress,
            f"[debate][vòng {round_no}/{max_rounds}] Bear xong ({bear_trace}, {len(bear_case):,} ký tự).",
        )
        _progress(progress, f"[debate][vòng {round_no}/{max_rounds}] Bear preview: {_plain_log_excerpt(bear_case)}")

        _progress(progress, f"[debate][vòng {round_no}/{max_rounds}] Coordinator đang chấm vòng tranh luận...")
        decision, coordinator_trace = _coordinator_decision(
            ticker=ticker,
            reports=reports,
            rounds=rounds,
            current_bull=bull_case,
            current_bear=bear_case,
            round_no=round_no,
            max_rounds=max_rounds,
            model=model,
            provider=provider,
        )
        rounds.append(
            DebateRound(
                round_no=round_no,
                bull_case=bull_case,
                bear_case=bear_case,
                decision=decision,
            )
        )
        trace.append(coordinator_trace)
        reason = decision.reason or "không có lý do cụ thể"
        _progress(
            progress,
            (
                f"[debate][vòng {round_no}/{max_rounds}] Coordinator: "
                f"{decision.winner} ({decision.confidence}); tiếp tục={decision.continue_debate}. "
                f"Lý do: {reason}"
            ),
        )
        bull_gap = "; ".join(decision.bull_gaps[:2]) if decision.bull_gaps else "không ghi nhận gap lớn"
        bear_gap = "; ".join(decision.bear_gaps[:2]) if decision.bear_gaps else "không ghi nhận gap lớn"
        _progress(
            progress,
            f"[debate][vòng {round_no}/{max_rounds}] Coordinator gaps: Bull={bull_gap}; Bear={bear_gap}",
        )
        if decision.next_instruction_for_bull or decision.next_instruction_for_bear:
            _progress(
                progress,
                (
                    f"[debate][vòng {round_no}/{max_rounds}] Hướng dẫn vòng sau: "
                    f"Bull={decision.next_instruction_for_bull or 'không có'}; "
                    f"Bear={decision.next_instruction_for_bear or 'không có'}"
                ),
            )
        if not decision.continue_debate:
            _progress(progress, f"[debate] Dừng sau vòng {round_no}: coordinator đã đủ điều kiện kết thúc.")
            break
    _progress(progress, f"[debate] Hoàn tất {len(rounds)} vòng tranh luận Bull/Bear.")
    return bull_case, bear_case, rounds, trace


def _truncate_for_prompt(text: str, max_chars: int) -> str:
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip() + "\n[Truncated]"


def _combined_report(
    ticker: str,
    trade_date: str | None,
    reports: dict[str, AnalystReport],
    bull_case: str,
    bear_case: str,
    trace: list[str],
    debate_rounds: list[DebateRound] | None = None,
) -> str:
    rating, score, explanation = _overall_rating(reports)
    dashboard = _summary_dashboard(
        ticker=ticker,
        trade_date=trade_date,
        rating=rating,
        score=score,
        explanation=explanation,
        reports=reports,
        bull_case=bull_case,
        bear_case=bear_case,
    )
    return "\n\n".join(
        item
        for item in [
            dashboard,
            '<section id="luan-diem-chi-tiet-bull">',
            "<h2>Luận điểm chi tiết Bull</h2>",
            bull_case,
            "</section>",
            '<section id="luan-diem-chi-tiet-bear">',
            "<h2>Luận điểm chi tiết Bear</h2>",
            bear_case,
            "</section>",
            _debate_report_section(debate_rounds or []),
            '<section id="tong-ket-hanh-dong">',
            "<h2>Tổng kết hành động</h2>",
            (
                "<p>Báo cáo này tổng hợp tranh luận bull/bear từ 4 nhóm analyst. "
                "Quyết định giao dịch cuối cùng vẫn cần được xác nhận thêm bằng điểm vào/ra, "
                "quản trị rủi ro và dữ liệu mới nhất trước khi đặt lệnh.</p>"
            ),
            "</section>",
        ]
        if item
    )


def _markdown_table_cell(value: str, max_chars: int = 420) -> str:
    text = _clean_report_line(value).replace("|", "/")
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "..."
    return text or "-"


def _markdown_list(items: list[str], fallback: str) -> str:
    cleaned_items = [_clean_report_line(item) for item in items]
    cleaned_items = [item for item in cleaned_items if item]
    if not cleaned_items:
        return f"- {fallback}"
    return "\n".join(f"- {item}" for item in cleaned_items)


def _debate_round_report(item: DebateRound) -> str:
    decision = item.decision
    coordinator_lines = [
        f"- Bên thắng thế: **{decision.winner}**",
        f"- Độ tin cậy: **{decision.confidence}**",
        f"- Lý do: {decision.reason or 'Chưa có lý do cụ thể.'}",
    ]
    if decision.next_instruction_for_bull:
        coordinator_lines.append(f"- Gợi ý vòng sau cho Bull: {decision.next_instruction_for_bull}")
    if decision.next_instruction_for_bear:
        coordinator_lines.append(f"- Gợi ý vòng sau cho Bear: {decision.next_instruction_for_bear}")

    return "\n\n".join(
        [
            f"### Vòng {item.round_no}",
            "#### Bull Researcher",
            item.bull_case.strip() or "_Không có luận điểm Bull._",
            "#### Bear Researcher",
            item.bear_case.strip() or "_Không có luận điểm Bear._",
            "#### Coordinator",
            "\n".join(coordinator_lines),
        ]
    )


def _debate_report_section(rounds: list[DebateRound]) -> str:
    if not rounds:
        return ""
    final = rounds[-1].decision
    rows = []
    for item in rounds:
        decision = item.decision
        rows.append(
            "| "
            + " | ".join(
                [
                    str(item.round_no),
                    _markdown_table_cell(decision.winner),
                    _markdown_table_cell(decision.confidence),
                    _markdown_table_cell(decision.reason or "Chưa có lý do cụ thể."),
                ]
            )
            + " |"
        )

    round_details = "\n\n".join(_debate_round_report(item) for item in rounds)
    bull_gaps = _markdown_list(final.bull_gaps, "Không ghi nhận gap lớn cho Bull.")
    bear_gaps = _markdown_list(final.bear_gaps, "Không ghi nhận gap lớn cho Bear.")
    return f"""
<section id="tranh-bien-theo-vong">
<h2>Tranh biện Bull/Bear theo từng vòng</h2>

**Cơ chế:** mỗi vòng gồm Bull Researcher nói trước, Bear Researcher phản biện sau. Coordinator đánh giá chất lượng bằng chứng sau từng vòng và dừng khi đã đủ số vòng hoặc có kết luận rõ.

**Kết quả sau {len(rounds)} vòng:** {final.winner} ({final.confidence} confidence).

| Vòng | Bên thắng thế | Độ tin cậy | Lý do |
| --- | --- | --- | --- |
{chr(10).join(rows)}

{round_details}

### Gap còn lại của Bull
{bull_gaps}

### Gap còn lại của Bear
{bear_gaps}
</section>
""".strip()


def run_research_synthesis_agent(
    ticker: str,
    trade_date: str,
    model: str,
    max_steps: int,
    look_back_days: int,
    social_path: str | None = None,
    provider: str = "openai",
    feedback_path: str | None = None,
    debate_rounds: int = 2,
    progress: ProgressLogger | None = None,
    reuse_analyst_reports: bool = False,
) -> tuple[str, list[str]]:
    _load_runtime_env()
    provider = apply_llm_runtime_defaults(provider, model)
    _progress(
        progress,
        (
            f"[research] Thu thập 4 analyst reports cho {ticker.upper()} "
            f"ngày {trade_date} bằng provider={provider}, model={model}."
        ),
    )

    reports = _collect_analyst_reports(
        ticker=ticker,
        trade_date=trade_date,
        model=model,
        max_steps=max_steps,
        look_back_days=look_back_days,
        social_path=social_path,
        provider=provider,
        feedback_path=feedback_path,
        progress=progress,
        reuse_existing=reuse_analyst_reports,
    )
    trace = [reports[kind].trace for kind in REPORT_KINDS]
    _progress(
        progress,
        "[research] Analyst reports đã sẵn sàng: "
        + ", ".join(f"{kind}={reports[kind].trace}" for kind in REPORT_KINDS),
    )
    bull_feedback = feedback_context_for(
        ticker=ticker,
        trade_date=trade_date,
        agents=("bull", "research", "all"),
        path=feedback_path,
    )
    bear_feedback = feedback_context_for(
        ticker=ticker,
        trade_date=trade_date,
        agents=("bear", "research", "all"),
        path=feedback_path,
    )
    bull_case, bear_case, debate_history, debate_trace = _run_research_debate(
        ticker,
        reports,
        model,
        provider,
        debate_rounds=debate_rounds,
        bull_feedback=bull_feedback,
        bear_feedback=bear_feedback,
        progress=progress,
    )
    trace.extend(debate_trace)
    _progress(progress, "[research] Đang dựng report tổng hợp kèm transcript từng vòng tranh luận...")
    report = _combined_report(
        ticker,
        trade_date,
        reports,
        bull_case,
        bear_case,
        trace,
        debate_rounds=debate_history,
    )
    _progress(progress, f"[research] Tổng hợp preview: {_plain_log_excerpt(report)}")
    _progress(progress, "[research] Hoàn tất report tổng hợp Bull/Bear.")
    return report, trace


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate four analyst reports into Bull and Bear researcher arguments."
    )
    parser.add_argument("--ticker", default="HPG")
    parser.add_argument("--date", default="2026-01-29")
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

    def log_progress(message: str) -> None:
        print(message, flush=True)

    try:
        report, _trace = run_research_synthesis_agent(
            ticker=args.ticker,
            trade_date=args.date,
            model=args.model,
            max_steps=args.max_steps,
            look_back_days=args.look_back_days,
            social_path=args.social_path,
            provider=args.provider,
            feedback_path=args.feedback_path,
            debate_rounds=args.debate_rounds,
            progress=log_progress,
            reuse_analyst_reports=args.reuse_analyst_reports,
        )
    except ResearchFlowError as exc:
        raise SystemExit(f"ERROR: {exc}") from None
    date_label = args.date or "latest"
    output_path = (
        Path(args.output)
        if args.output
        else _repo_root() / "reports" / f"{args.ticker}_research_synthesis_main_{date_label}.md"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    mirror_report_to_portal(output_path)

    print(f"PROVIDER={args.provider}")
    print(f"MODEL={args.model}")
    print(f"DEBATE_ROUNDS={args.debate_rounds}")
    print(f"OUTPUT={output_path}")
    print("REPORT_PREVIEW:")
    print(report[:5000])


if __name__ == "__main__":
    main()
