from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.config import get_settings
from app.schemas import AnalysisRunLogEntry, AnalysisRunStatusResponse, AnalysisRunStep, AnalysisReportSection, AnalysisReportsResponse
from app.services.llm_config import get_llm_runtime_config


REPORT_ORDER = ["market", "sentiment", "news", "fundamentals", "research"]
RUN_STATE_TTL = timedelta(hours=3)

REPORT_LABELS = {
    "market": ("Market Analyst", "Phân tích kỹ thuật"),
    "sentiment": ("Sentiment Analyst", "Tâm lý thị trường"),
    "news": ("News Analyst", "Tin tức"),
    "fundamentals": ("Fundamentals Analyst", "Cơ bản doanh nghiệp"),
    "research": ("Bull/Bear Researchers", "Tổng hợp nghiên cứu"),
}

SECTION_FILE_KEYS = {
    "market_report": "market",
    "market": "market",
    "sentiment_report": "sentiment",
    "sentiment": "sentiment",
    "news_report": "news",
    "news": "news",
    "fundamentals_report": "fundamentals",
    "fundamentals": "fundamentals",
}

DATE_PATTERN = re.compile(r"(20\d{2}-\d{2}-\d{2})")
TIMESTAMP_PATTERN = re.compile(r"(20\d{2}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")
LOG_PREFIX_PATTERN = re.compile(r"^20\d{2}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\s+")

_RUN_STATE: dict[str, datetime] = {}
_RUN_PROCESSES: dict[str, subprocess.Popen[str]] = {}
_RUN_EXIT_CODES: dict[str, int] = {}


@dataclass(frozen=True)
class ReportCandidate:
    key: str
    path: Path
    score: int
    last_modified: datetime


def _classify_flat_report(path: Path, ticker: str) -> str | None:
    name = path.name.lower()
    ticker_prefix = f"{ticker.lower()}_"
    if not name.startswith(ticker_prefix):
        return None

    if "_research_synthesis" in name:
        return "research"
    if "_market" in name:
        return "market"
    if "_sentiment" in name:
        return "sentiment"
    if "_news" in name:
        return "news"
    if "_fundamentals" in name:
        return "fundamentals"
    return None


def _classify_section_file(path: Path) -> str | None:
    return SECTION_FILE_KEYS.get(path.stem.lower())


def _candidate_score(path: Path, base_score: int) -> int:
    name = path.name.lower()
    score = base_score
    if "_main_" in name:
        score += 30
    if "agent_latest" in name:
        score += 20
    if "complete_report" in name:
        score -= 10
    if "llm" in name:
        score -= 10
    if "smoke" in name:
        score -= 20
    return score


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0)


def _trade_date(path: Path) -> str | None:
    match = DATE_PATTERN.search(path.name)
    if match:
        return match.group(1)

    for part in reversed(path.parts):
        if DATE_PATTERN.fullmatch(part):
            return part
    return None


def _word_count(content: str) -> int:
    return len(re.findall(r"\S+", content))


def _read_report(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _plain_preview(content: str, limit: int = 260) -> str:
    text = re.sub(r"<style[\s\S]*?</style>", " ", content, flags=re.IGNORECASE)
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"[#*_`|>\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _parse_log_timestamp(line: str) -> datetime | None:
    match = TIMESTAMP_PATTERN.search(line)
    if not match:
        return None
    value = match.group(1).replace("T", " ")
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _strip_log_timestamp(line: str) -> str:
    return LOG_PREFIX_PATTERN.sub("", line).strip()


def _is_traceback_noise(message: str) -> bool:
    text = message.strip()
    if not text:
        return True
    if text.startswith(("Traceback ", "The above exception", "During handling of the above exception")):
        return True
    if re.match(r'^File ".+", line \d+, in ', text):
        return True
    if re.fullmatch(r"[\^~\s]+", text):
        return True
    if re.match(
        r"^(return|raise|self\.|result\s*=|response\s*=|response:|input_\s*=|output\s*=|output_path\s*=|reports\s*=|reports\[|report,\s*trace|main\(\)|do\s*=|cls\.|errors\.|_[A-Za-z_]+\()",
        text,
    ):
        return True
    if re.match(r"^[A-Za-z_][\w\.\[\]]+\(", text) and not text.startswith("["):
        return True
    normalized = text.lower()
    if "failed download" in normalized:
        return True
    if "possibly delisted" in normalized and "no price data found" in normalized:
        return True
    return False


def _friendly_runtime_message(message: str) -> str | None:
    text = _strip_log_timestamp(message)
    if _is_traceback_noise(text):
        return None

    normalized = text.lower()
    if "samefileerror" in normalized and "are the same file" in normalized:
        return "[Hệ thống] File báo cáo đã nằm đúng trong thư mục reports; bỏ qua bước sao chép mirror để tránh ghi đè chính nó."
    if "resource_exhausted" in normalized or "quota exceeded" in normalized or "current quota" in normalized:
        model_match = re.search(r"model[:=]\s*'?([A-Za-z0-9._/\-]+)'?", text)
        model_text = f" cho model {model_match.group(1)}" if model_match else ""
        retry_match = re.search(r"retry in ([0-9.]+)s", text, flags=re.IGNORECASE)
        retry_text = f" Có thể thử lại sau khoảng {round(float(retry_match.group(1)))} giây." if retry_match else ""
        return (
            f"[Hệ thống] Google Gemini đã hết quota hoặc vượt giới hạn sử dụng{model_text}. "
            "Hãy đổi model/provider hoặc kiểm tra gói/billing của API key."
            f"{retry_text}"
        )
    if "api key" in normalized and ("not set" in normalized or "invalid" in normalized or "permission" in normalized):
        return "[Hệ thống] API key LLM chưa hợp lệ hoặc chưa có quyền gọi model đã chọn. Hãy kiểm tra lại cấu hình LLM."
    if "chatgooglegenerativeaierror" in normalized:
        return "[Hệ thống] Google Gemini trả lỗi khi sinh báo cáo. Hãy kiểm tra quota, model và API key trong cấu hình LLM."
    if "clienterror" in normalized or "apierror" in normalized:
        return f"[Hệ thống] Provider LLM trả lỗi API: {text[-260:]}"
    if len(text) > 420:
        return text[:419].rstrip() + "..."
    return text


def _to_local_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(microsecond=0)
    return value.astimezone().replace(tzinfo=None, microsecond=0)


def _agent_from_text(value: str) -> str | None:
    normalized = value.lower()
    for key, (agent, _title) in REPORT_LABELS.items():
        if key in normalized or agent.lower().split()[0] in normalized:
            return agent
    if "bull" in normalized or "bear" in normalized or "research" in normalized:
        return REPORT_LABELS["research"][0]
    return None


def _iter_flat_candidates(reports_dir: Path, ticker: str) -> list[ReportCandidate]:
    if not reports_dir.exists():
        return []

    candidates: list[ReportCandidate] = []
    for path in reports_dir.glob(f"{ticker}_*.md"):
        if not path.is_file():
            continue
        key = _classify_flat_report(path, ticker)
        if key is None:
            continue
        candidates.append(
            ReportCandidate(
                key=key,
                path=path,
                score=_candidate_score(path, 20),
                last_modified=_mtime(path),
            )
        )
    return candidates


def _iter_log_candidates(logs_dir: Path, ticker: str) -> list[ReportCandidate]:
    ticker_dir = logs_dir / ticker
    if not ticker_dir.exists():
        return []

    candidates: list[ReportCandidate] = []
    for reports_dir in ticker_dir.glob("*/reports"):
        if not reports_dir.is_dir():
            continue
        for path in reports_dir.glob("*.md"):
            key = _classify_section_file(path)
            if key is None:
                continue
            candidates.append(
                ReportCandidate(
                    key=key,
                    path=path,
                    score=_candidate_score(path, 60),
                    last_modified=_mtime(path),
                )
            )

    for path in ticker_dir.glob("*/1_analysts/*.md"):
        key = _classify_section_file(path)
        if key is None or not path.is_file():
            continue
        candidates.append(
            ReportCandidate(
                key=key,
                path=path,
                score=_candidate_score(path, 70),
                last_modified=_mtime(path),
            )
        )

    return candidates


def _pick_latest_by_section(candidates: list[ReportCandidate]) -> list[ReportCandidate]:
    def rank(candidate: ReportCandidate) -> tuple[datetime, datetime, int]:
        trade_date = _trade_date(candidate.path)
        if trade_date:
            try:
                dated_rank = datetime.strptime(trade_date, "%Y-%m-%d")
            except ValueError:
                dated_rank = candidate.last_modified
        else:
            dated_rank = candidate.last_modified
        return (dated_rank, candidate.last_modified, candidate.score)

    selected: dict[str, ReportCandidate] = {}
    for candidate in candidates:
        previous = selected.get(candidate.key)
        if previous is None:
            selected[candidate.key] = candidate
            continue

        if rank(candidate) > rank(previous):
            selected[candidate.key] = candidate

    return sorted(selected.values(), key=lambda item: REPORT_ORDER.index(item.key))


def _collect_candidates(ticker: str) -> tuple[list[str], list[ReportCandidate]]:
    settings = get_settings()
    normalized_ticker = ticker.strip().upper()
    source_dirs = [str(path) for path in settings.analysis_report_dirs if path.exists()]
    flat_dir, logs_dir = settings.analysis_report_dirs
    candidates = [
        *_iter_flat_candidates(flat_dir, normalized_ticker),
        *_iter_log_candidates(logs_dir, normalized_ticker),
    ]
    return source_dirs, candidates


def _recent_file_logs(candidates: list[ReportCandidate], limit: int = 12) -> list[AnalysisRunLogEntry]:
    logs: list[AnalysisRunLogEntry] = []
    for candidate in sorted(candidates, key=lambda item: item.last_modified, reverse=True)[:limit]:
        try:
            content = _read_report(candidate.path)
        except OSError:
            continue
        agent, _title = REPORT_LABELS[candidate.key]
        logs.append(
            AnalysisRunLogEntry(
                timestamp=candidate.last_modified,
                agent=agent,
                message=f"Đã ghi {candidate.path.name}: {_word_count(content)} từ. {_plain_preview(content, 160)}",
                source=str(candidate.path),
            )
        )
    return logs


def _available_report_tickers(reports_dir: Path, limit: int = 12) -> list[str]:
    if not reports_dir.exists():
        return []

    tickers: set[str] = set()
    for path in reports_dir.glob("*.md"):
        prefix = path.name.split("_", 1)[0].strip().upper()
        if prefix:
            tickers.add(prefix)
    return sorted(tickers)[:limit]


def _recent_text_logs(logs_dir: Path, ticker: str, limit: int = 50) -> list[AnalysisRunLogEntry]:
    ticker_dir = logs_dir / ticker
    if not ticker_dir.exists():
        return []

    paths: list[Path] = []
    for pattern in ("*.log", "*.txt", "*.out", "*.err"):
        paths.extend(path for path in ticker_dir.rglob(pattern) if path.is_file())

    entries: list[AnalysisRunLogEntry] = []
    for path in sorted(paths, key=lambda item: item.stat().st_mtime, reverse=True)[:10]:
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        seen_messages: set[str] = set()
        for line in lines[-120:]:
            raw_message = line.strip()
            message = _friendly_runtime_message(raw_message)
            if not message:
                continue
            if message in seen_messages:
                continue
            seen_messages.add(message)
            entries.append(
                AnalysisRunLogEntry(
                    timestamp=_parse_log_timestamp(raw_message) or _mtime(path),
                    agent=_agent_from_text(f"{path.name} {raw_message} {message}"),
                    message=message[-420:],
                    source=str(path),
                )
            )

    return sorted(entries, key=lambda item: item.timestamp or datetime.min, reverse=True)[:limit]


def _append_run_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().replace(microsecond=0).isoformat(sep=" ")
    with path.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(f"{timestamp} {message}\n")


def _active_process(ticker: str) -> subprocess.Popen[str] | None:
    process = _RUN_PROCESSES.get(ticker)
    if process is None:
        return None
    if process.poll() is None:
        return process
    return None


def _stream_tradingagents_process(ticker: str, process: subprocess.Popen[str], log_path: Path) -> None:
    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                line = raw_line.rstrip()
                if line:
                    _append_run_log(log_path, line)
        return_code = process.wait()
        if return_code == 0:
            _append_run_log(log_path, "[Hệ thống] TradingAgents đã hoàn tất và ghi báo cáo.")
        else:
            _append_run_log(log_path, f"[Hệ thống] TradingAgents dừng với mã lỗi {return_code}.")
        _RUN_EXIT_CODES[ticker] = return_code
    except Exception as exc:  # pragma: no cover - defensive logging for background thread
        _append_run_log(log_path, f"[Hệ thống] Lỗi khi đọc log tiến trình: {exc}")
    finally:
        current = _RUN_PROCESSES.get(ticker)
        if current is process:
            _RUN_PROCESSES.pop(ticker, None)


def _launch_tradingagents_report(ticker: str, started_at: datetime) -> Path:
    settings = get_settings()
    source_dir = settings.tradingagents_source_path
    _flat_dir, logs_dir = settings.analysis_report_dirs
    run_id = f"{started_at:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
    log_path = logs_dir / ticker / run_id / "run.log"

    if _active_process(ticker) is not None:
        _append_run_log(log_path, "[Hệ thống] Đã có một lượt tạo báo cáo đang chạy cho mã này.")
        return log_path

    if source_dir is None or not (source_dir / "main.py").exists():
        _append_run_log(log_path, "[Hệ thống] Chưa tìm thấy source TradingAgents trong backend container.")
        return log_path

    analysis_date = settings.tradingagents_analysis_date or datetime.now().strftime("%Y-%m-%d")
    llm_config = get_llm_runtime_config()
    provider = llm_config.provider
    model = llm_config.model
    cmd = [
        sys.executable,
        "main.py",
        "--ticker",
        ticker,
        "--date",
        analysis_date,
        "--provider",
        provider,
        "--model",
        model,
        "--max-steps",
        str(settings.tradingagents_max_steps),
        "--look-back-days",
        str(settings.tradingagents_look_back_days),
        "--debate-rounds",
        str(settings.tradingagents_debate_rounds),
    ]

    env = os.environ.copy()
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "TRADINGAGENTS_OUTPUT_LANGUAGE": "Vietnamese",
            "TRADINGAGENTS_PORTAL_REPORTS_DIR": str(source_dir / "reports"),
            "TRADINGAGENTS_WAREHOUSE_POSTGRES_HOST": settings.postgres_host,
            "TRADINGAGENTS_WAREHOUSE_POSTGRES_PORT": str(settings.postgres_port),
            "TRADINGAGENTS_WAREHOUSE_POSTGRES_DB": settings.postgres_db,
            "TRADINGAGENTS_WAREHOUSE_POSTGRES_USER": settings.postgres_user,
            "TRADINGAGENTS_WAREHOUSE_POSTGRES_PASSWORD": settings.postgres_password,
            "TRADINGAGENTS_WAREHOUSE_SCHEMA": settings.postgres_schema,
        }
    )

    _append_run_log(
        log_path,
        f"[Hệ thống] Bắt đầu tạo báo cáo {ticker} bằng API key provider={provider}, model={model}, ngày phân tích {analysis_date}.",
    )

    if llm_config.key_env and not llm_config.api_key:
        _append_run_log(
            log_path,
            f"[Hệ thống] Chưa cấu hình {llm_config.key_env}. Hãy mở cấu hình LLM và lưu API key trước khi kích hoạt báo cáo.",
        )
        _RUN_EXIT_CODES[ticker] = 2
        return log_path

    if llm_config.key_env and llm_config.api_key:
        env[str(llm_config.key_env)] = llm_config.api_key

    _RUN_EXIT_CODES.pop(ticker, None)
    try:
        process = subprocess.Popen(
            cmd,
            cwd=source_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        _append_run_log(log_path, f"[Hệ thống] Không khởi chạy được TradingAgents: {exc}")
        return log_path

    _RUN_PROCESSES[ticker] = process
    threading.Thread(
        target=_stream_tradingagents_process,
        args=(ticker, process, log_path),
        daemon=True,
    ).start()
    return log_path


def start_analysis_report_run(ticker: str) -> AnalysisRunStatusResponse:
    normalized_ticker = ticker.strip().upper()
    started_at = datetime.now().replace(microsecond=0)
    _RUN_STATE[normalized_ticker] = started_at
    _launch_tradingagents_report(normalized_ticker, started_at)
    return get_analysis_run_status(normalized_ticker)


def get_analysis_run_status(ticker: str, started_at: datetime | None = None) -> AnalysisRunStatusResponse:
    normalized_ticker = ticker.strip().upper()
    source_dirs, candidates = _collect_candidates(normalized_ticker)
    selected = {candidate.key: candidate for candidate in _pick_latest_by_section(candidates)}

    run_started_at = _to_local_naive(started_at) or _RUN_STATE.get(normalized_ticker)
    now = datetime.now().replace(microsecond=0)
    active_process = _active_process(normalized_ticker)
    last_exit_code = _RUN_EXIT_CODES.get(normalized_ticker)
    steps: list[AnalysisRunStep] = []
    done_count = 0
    running_assigned = False

    for key in REPORT_ORDER:
        agent, title = REPORT_LABELS[key]
        candidate = selected.get(key)
        content = ""
        status = "waiting"
        detail = "Đang chờ agent sinh báo cáo."
        preview: str | None = None
        word_count: int | None = None

        if candidate is not None:
            try:
                content = _read_report(candidate.path)
            except OSError:
                content = ""
            word_count = _word_count(content) if content else 0
            preview = _plain_preview(content)
            is_current_run_output = run_started_at is None or candidate.last_modified >= run_started_at
            if is_current_run_output or run_started_at is None:
                status = "done"
                done_count += 1
                detail = f"Đã có kết quả từ {agent}, cập nhật {candidate.last_modified:%d/%m/%Y %H:%M}."
            else:
                status = "waiting"
                detail = f"Đang hiển thị báo cáo gần nhất trước lần kích hoạt: {candidate.last_modified:%d/%m/%Y %H:%M}."

        if status == "waiting" and run_started_at and now - run_started_at <= RUN_STATE_TTL and not running_assigned:
            status = "running"
            running_assigned = True
            detail = "Đang theo dõi thư mục báo cáo/log cho agent này. Kết quả sẽ hiển thị khi file mới được ghi."

        steps.append(
            AnalysisRunStep(
                key=key,
                title=title,
                agent=agent,
                status=status,
                detail=detail,
                source_file=str(candidate.path) if candidate else None,
                last_modified=candidate.last_modified if candidate else None,
                word_count=word_count,
                preview=preview,
            )
        )

    flat_dir, logs_dir = get_settings().analysis_report_dirs
    text_logs = _recent_text_logs(logs_dir, normalized_ticker) if run_started_at or active_process else []
    if run_started_at:
        text_logs = [entry for entry in text_logs if not entry.timestamp or entry.timestamp >= run_started_at]
    file_log_candidates = candidates
    if run_started_at:
        file_log_candidates = [candidate for candidate in candidates if candidate.last_modified >= run_started_at]
    file_logs = _recent_file_logs(file_log_candidates)
    logs = sorted([*text_logs, *file_logs], key=lambda item: item.timestamp or datetime.min, reverse=True)[:60]
    if not logs:
        available_tickers = _available_report_tickers(flat_dir)
        available_text = ", ".join(available_tickers) if available_tickers else "chưa có mã nào"
        logs = [
            AnalysisRunLogEntry(
                timestamp=now,
                agent=None,
                message=(
                    f"Chưa có báo cáo/log cho {normalized_ticker} trong thư mục đang được gắn vào backend. "
                    f"Backend đang đọc báo cáo tại {flat_dir}. "
                    f"Các mã hiện có báo cáo: {available_text}. "
                    "Bấm Kích hoạt báo cáo để backend tạo báo cáo mới bằng API key đã cấu hình."
                ),
                source=str(flat_dir),
            )
        ]

    progress = round(done_count / len(REPORT_ORDER), 4) if REPORT_ORDER else 0.0
    running = bool(active_process)
    if progress >= 1:
        message = "Đã đọc đủ kết quả của các agent và bản tổng hợp."
    elif last_exit_code is not None and last_exit_code != 0:
        message = f"Lượt tạo báo cáo đã dừng với mã lỗi {last_exit_code}; có thể bấm Kích hoạt báo cáo để chạy lại."
    elif active_process:
        message = "TradingAgents đang tạo báo cáo bằng API key đã cấu hình; log sẽ cập nhật theo từng bước."
    elif run_started_at and now - run_started_at <= RUN_STATE_TTL:
        message = "Đang theo dõi tiến trình tạo báo cáo từ thư mục báo cáo/log."
    else:
        message = "Chưa có lượt chạy đang hoạt động; đang hiển thị trạng thái báo cáo hiện có."

    return AnalysisRunStatusResponse(
        ticker=normalized_ticker,
        source_dirs=source_dirs,
        started_at=run_started_at,
        updated_at=now,
        running=running,
        progress=progress,
        message=message,
        steps=steps,
        logs=logs,
    )


def get_analysis_reports(ticker: str) -> AnalysisReportsResponse:
    normalized_ticker = ticker.strip().upper()
    source_dirs, candidates = _collect_candidates(normalized_ticker)
    selected = _pick_latest_by_section(candidates)

    sections: list[AnalysisReportSection] = []
    for candidate in selected:
        content = _read_report(candidate.path)
        agent, title = REPORT_LABELS[candidate.key]
        sections.append(
            AnalysisReportSection(
                key=candidate.key,
                title=title,
                agent=agent,
                source_file=str(candidate.path),
                last_modified=candidate.last_modified,
                trade_date=_trade_date(candidate.path),
                content=content,
                word_count=_word_count(content),
            )
        )

    updated_at = max((section.last_modified for section in sections), default=None)
    return AnalysisReportsResponse(
        ticker=normalized_ticker,
        source_dirs=source_dirs,
        updated_at=updated_at,
        total=len(sections),
        sections=sections,
    )
