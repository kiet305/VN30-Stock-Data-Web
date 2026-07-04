"""Local CSV social-sentiment context for TradingAgents.

The project-level ``trend/social.csv`` file contains market-wide social
reaction metrics by ticker and date. This module turns those raw counters into
prompt-ready context for a sentiment-only agent.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


SOCIAL_COLUMNS = [
    "likesCount",
    "sharesCount",
    "reactionLoveCount",
    "reactionWowCount",
    "reactionHahaCount",
    "reactionSadCount",
]


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _fmt(value, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return "N/A"
        if abs(value) >= 1000:
            return f"{value:,.{decimals}f}"
        return f"{value:.{decimals}f}"
    return str(value)


def _fmt_int(value) -> str:
    try:
        if value is None or not math.isfinite(float(value)):
            return "N/A"
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return "N/A"


def _table(headers: list[str], rows: list[list[str]], align_right: set[int] | None = None) -> str:
    align_right = align_right or set()
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---:" if i in align_right else "---" for i in range(len(headers))) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item).replace("\n", " ") for item in row) + " |")
    return "\n".join(lines)


def _to_float(value) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(value) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _read_social(path: Optional[str] = None) -> tuple[list[dict], Path]:
    social_path = Path(path) if path else _workspace_root() / "trend" / "social.csv"
    rows: list[dict] = []
    with social_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            ticker = str(raw.get("ticker", "")).upper().strip()
            date = _parse_date(raw.get("date"))
            if not ticker or date is None:
                continue
            row = {"ticker": ticker, "date": date}
            for col in SOCIAL_COLUMNS:
                row[col] = _to_float(raw.get(col))
            row["post_count"] = _to_float(raw.get("post_count", 1.0)) or 1.0
            rows.append(row)
    return rows, social_path


def _latest_trending_file() -> Optional[Path]:
    trend_dir = _workspace_root() / "trend"
    files = sorted(
        [
            path
            for path in trend_dir.glob("trending_VN_7d_*.csv")
            if not path.name.endswith(".bak")
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def _read_trends(limit: int = 12) -> tuple[list[dict], Optional[Path]]:
    path = _latest_trending_file()
    if path is None:
        return [], None
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))[:limit], path


def latest_social_date(social_path: Optional[str] = None) -> str:
    """Return the latest date available in the local social CSV."""
    rows, _ = _read_social(social_path)
    if not rows:
        raise ValueError("No social rows found in local social CSV.")
    return max(row["date"] for row in rows).strftime("%Y-%m-%d")


def _score_row(row: dict) -> dict:
    out = dict(row)
    out["attention"] = (
        out.get("likesCount", 0.0)
        + 3.0 * out.get("sharesCount", 0.0)
        + 2.0 * out.get("reactionLoveCount", 0.0)
        + out.get("reactionWowCount", 0.0)
        + 0.5 * out.get("reactionHahaCount", 0.0)
        + out.get("reactionSadCount", 0.0)
    )
    out["positive_reactions"] = (
        out.get("reactionLoveCount", 0.0)
        + 0.5 * out.get("reactionWowCount", 0.0)
        + 0.25 * out.get("reactionHahaCount", 0.0)
    )
    out["negative_reactions"] = out.get("reactionSadCount", 0.0)
    denominator = out["positive_reactions"] + out["negative_reactions"]
    out["sentiment_score"] = (
        (out["positive_reactions"] - out["negative_reactions"]) / denominator
        if denominator
        else 0.0
    )
    return out


def _with_scores(rows: list[dict]) -> list[dict]:
    return [_score_row(row) for row in rows]


def _date_window(rows: list[dict], curr_date: Optional[str], look_back_days: int) -> tuple[datetime, datetime]:
    end = _parse_date(curr_date) if curr_date else max(row["date"] for row in rows)
    if end is None:
        end = max(row["date"] for row in rows)
    start = end - timedelta(days=int(look_back_days))
    return start, end


def _sum_rows(rows: list[dict], group_key: str | None = None) -> list[dict]:
    groups: dict[object, dict] = {}
    for row in rows:
        key = row[group_key] if group_key else "__all__"
        if key not in groups:
            groups[key] = {group_key: key} if group_key else {}
            for col in SOCIAL_COLUMNS + ["post_count"]:
                groups[key][col] = 0.0
        for col in SOCIAL_COLUMNS + ["post_count"]:
            groups[key][col] += _to_float(row.get(col))
    return [_score_row(group) for group in groups.values()]


def build_market_social_context(
    ticker: str = "MARKET",
    curr_date: Optional[str] = None,
    look_back_days: int = 7,
    social_path: Optional[str] = None,
    top_n: int = 12,
) -> str:
    """Return market-wide and ticker-specific social context from local CSV."""
    rows, path = _read_social(social_path)
    rows = _with_scores(rows)
    start, end = _date_window(rows, curr_date, look_back_days)
    window = [row for row in rows if start <= row["date"] <= end]
    if not window:
        return (
            f"No local social rows found between {start.date()} and {end.date()} "
            f"from {path}."
        )

    ticker_upper = str(ticker).upper().strip()
    ticker_rows = [row for row in window if row["ticker"] == ticker_upper]

    by_date: defaultdict[datetime, list[dict]] = defaultdict(list)
    by_ticker: defaultdict[str, list[dict]] = defaultdict(list)
    for row in window:
        by_date[row["date"]].append(row)
        by_ticker[row["ticker"]].append(row)

    market_daily = []
    for date, grouped in by_date.items():
        summed = _sum_rows(grouped)[0]
        summed["date"] = date
        market_daily.append(summed)
    market_daily.sort(key=lambda item: item["date"])

    ticker_totals = []
    for ticker_key, grouped in by_ticker.items():
        summed = _sum_rows(grouped)[0]
        summed["ticker"] = ticker_key
        ticker_totals.append(summed)
    ticker_totals.sort(key=lambda item: item["attention"], reverse=True)

    market_rows = [
        [
            row["date"].strftime("%Y-%m-%d"),
            _fmt_int(row["post_count"]),
            _fmt_int(row["likesCount"]),
            _fmt_int(row["sharesCount"]),
            _fmt_int(row["reactionLoveCount"]),
            _fmt_int(row["reactionWowCount"]),
            _fmt_int(row["reactionHahaCount"]),
            _fmt_int(row["reactionSadCount"]),
            _fmt(row["attention"]),
            _fmt(row["sentiment_score"]),
        ]
        for row in market_daily
    ]

    top_rows = [
        [
            row["ticker"],
            _fmt_int(row["post_count"]),
            _fmt_int(row["likesCount"]),
            _fmt_int(row["sharesCount"]),
            _fmt_int(row["reactionLoveCount"]),
            _fmt_int(row["reactionSadCount"]),
            _fmt(row["attention"]),
            _fmt(row["sentiment_score"]),
        ]
        for row in ticker_totals[:top_n]
    ]

    ticker_section = ""
    if ticker_upper != "MARKET":
        if not ticker_rows:
            ticker_section = (
                f"## Ticker-specific social metrics for {ticker_upper}\n\n"
                f"No rows for {ticker_upper} in this window. Treat ticker-specific social signal as unavailable and rely on market-wide context.\n"
            )
        else:
            ticker_agg = _sum_rows(ticker_rows)[0]
            ticker_daily = []
            grouped_by_date: defaultdict[datetime, list[dict]] = defaultdict(list)
            for row in ticker_rows:
                grouped_by_date[row["date"]].append(row)
            for date, grouped in grouped_by_date.items():
                summed = _sum_rows(grouped)[0]
                summed["date"] = date
                ticker_daily.append(summed)
            ticker_daily.sort(key=lambda item: item["date"])
            ticker_section = "\n".join(
                [
                    f"## Ticker-specific social metrics for {ticker_upper}",
                    "",
                    _table(
                        ["Metric", "Value"],
                        [
                            ["Rows/posts", _fmt_int(ticker_agg["post_count"])],
                            ["Likes", _fmt_int(ticker_agg["likesCount"])],
                            ["Shares", _fmt_int(ticker_agg["sharesCount"])],
                            ["Love reactions", _fmt_int(ticker_agg["reactionLoveCount"])],
                            ["Wow reactions", _fmt_int(ticker_agg["reactionWowCount"])],
                            ["Haha reactions", _fmt_int(ticker_agg["reactionHahaCount"])],
                            ["Sad reactions", _fmt_int(ticker_agg["reactionSadCount"])],
                            ["Attention index", _fmt(ticker_agg["attention"])],
                            ["Reaction sentiment score (-1 to 1)", _fmt(ticker_agg["sentiment_score"])],
                        ],
                        {1},
                    ),
                    "",
                    _table(
                        ["Date", "Posts", "Likes", "Shares", "Love", "Wow", "Haha", "Sad", "Attention", "Score"],
                        [
                            [
                                row["date"].strftime("%Y-%m-%d"),
                                _fmt_int(row["post_count"]),
                                _fmt_int(row["likesCount"]),
                                _fmt_int(row["sharesCount"]),
                                _fmt_int(row["reactionLoveCount"]),
                                _fmt_int(row["reactionWowCount"]),
                                _fmt_int(row["reactionHahaCount"]),
                                _fmt_int(row["reactionSadCount"]),
                                _fmt(row["attention"]),
                                _fmt(row["sentiment_score"]),
                            ]
                            for row in ticker_daily
                        ],
                        set(range(1, 10)),
                    ),
                ]
            )

    trends, trends_path = _read_trends()
    trends_section = "No local Google Trends file found."
    if trends:
        trends_rows = [
            [
                str(row.get("Trends", "")),
                str(row.get("Search volume", "")),
                str(row.get("Started", "")),
                str(row.get("Trend breakdown", "")),
            ]
            for row in trends
        ]
        trends_section = "\n".join(
            [
                f"Source file: {trends_path}",
                _table(["Trend", "Search volume", "Started", "Breakdown"], trends_rows),
            ]
        )

    return "\n\n".join(
        [
            "# Local Market Social Sentiment Context",
            f"- Source file: {path}",
            f"- Requested ticker: {ticker_upper}",
            f"- Window: {start.date()} to {end.date()}",
            f"- Market rows in window: {len(window)}",
            "- Attention index = likes + 3*shares + 2*love + wow + 0.5*haha + sad.",
            "- Reaction sentiment score = (positive reactions - sad reactions) / (positive reactions + sad reactions), where positive = love + 0.5*wow + 0.25*haha.",
            "## Market-wide daily social metrics",
            _table(
                ["Date", "Posts", "Likes", "Shares", "Love", "Wow", "Haha", "Sad", "Attention", "Score"],
                market_rows,
                set(range(1, 10)),
            ),
            "## Top tickers by social attention",
            _table(
                ["Ticker", "Posts", "Likes", "Shares", "Love", "Sad", "Attention", "Score"],
                top_rows,
                set(range(1, 8)),
            ),
            ticker_section,
            "## Vietnam Google Trends Context",
            trends_section,
        ]
    )


def build_deterministic_social_report(
    ticker: str = "MARKET",
    curr_date: Optional[str] = None,
    look_back_days: int = 7,
    social_path: Optional[str] = None,
    top_n: int = 8,
) -> str:
    """Build a deterministic sentiment report directly from local social CSV."""
    rows, path = _read_social(social_path)
    rows = _with_scores(rows)
    start, end = _date_window(rows, curr_date, look_back_days)
    window = [row for row in rows if start <= row["date"] <= end]
    if not window:
        ticker_upper = str(ticker).upper().strip()
        return "\n\n".join(
            [
                "## Mã cổ phiếu",
                ticker_upper,
                "## Ngày đánh giá",
                end.strftime("%Y-%m-%d"),
                "## Nhận định tổng quát",
                f"Không có dòng social local nào trong giai đoạn {start.date()} đến {end.date()} từ `{path}`.",
                "## Luận điểm 1 - Kết luận: Hold",
                "- Luận cứ 1 - Dẫn chứng: Tín hiệu sentiment không đủ để nghiêng về mua hoặc bán; Dẫn chứng: tập dữ liệu local không có dòng phù hợp trong cửa sổ phân tích.",
                "- Luận cứ 2 - Dẫn chứng: Không thể xác nhận attention hoặc phản ứng cảm xúc; Dẫn chứng: không có post_count, attention index, hoặc reaction sentiment score khả dụng.",
                "## Luận điểm 2 - Kết luận: Hold",
                "- Luận cứ 1 - Dẫn chứng: Nên trung lập cho đến khi có thêm dữ liệu; Dẫn chứng: thiếu dữ liệu trực tiếp cho mã và thị trường chung.",
                "- Luận cứ 2 - Dẫn chứng: Cần đối chiếu với market, news và fundamentals; Dẫn chứng: social fallback chỉ báo thiếu dữ liệu, không phải khuyến nghị độc lập.",
                "## Kết luận tổng",
                "Kết luận tổng: Hold vì dữ liệu social local không đủ để đưa ra nhận định thiên lệch theo một phía.",
            ]
        )

    ticker_upper = str(ticker).upper().strip()
    market_agg = _sum_rows(window)[0]
    positive = market_agg["positive_reactions"]
    negative = market_agg["negative_reactions"]
    market_score_raw = (positive - negative) / max(positive + negative, 1)
    score_10 = round((market_score_raw + 1) * 5, 2)
    if score_10 >= 7.5:
        band = "Bullish"
    elif score_10 >= 6:
        band = "Mildly Bullish"
    elif score_10 <= 2.5:
        band = "Bearish"
    elif score_10 <= 4:
        band = "Mildly Bearish"
    else:
        band = "Neutral"

    confidence = "high" if len(window) >= 40 else "medium" if len(window) >= 15 else "low"

    if score_10 >= 7.5:
        market_rating = "Buy"
    elif score_10 >= 6:
        market_rating = "Overweight"
    elif score_10 <= 2.5:
        market_rating = "Sell"
    elif score_10 <= 4:
        market_rating = "Underweight"
    else:
        market_rating = "Hold"

    by_ticker: defaultdict[str, list[dict]] = defaultdict(list)
    for row in window:
        by_ticker[row["ticker"]].append(row)
    ticker_totals = []
    for ticker_key, grouped in by_ticker.items():
        summed = _sum_rows(grouped)[0]
        summed["ticker"] = ticker_key
        ticker_totals.append(summed)
    ticker_totals.sort(key=lambda item: item["attention"], reverse=True)
    top_attention_evidence = "; ".join(
        f"{row['ticker']}: attention {_fmt(row['attention'])}, score {_fmt(row['sentiment_score'])}"
        for row in ticker_totals[: min(5, top_n, len(ticker_totals))]
    ) or "không có ticker attention nổi bật"

    ticker_row = None
    ticker_rating = "Hold"
    ticker_evidence = "Không có dòng social riêng cho ticker này trong cửa sổ phân tích."
    if ticker_upper != "MARKET":
        ticker_row = next((row for row in ticker_totals if row["ticker"] == ticker_upper), None)
        if ticker_row is not None:
            ticker_score_10 = round((ticker_row["sentiment_score"] + 1) * 5, 2)
            if ticker_score_10 >= 7.5:
                ticker_rating = "Buy"
            elif ticker_score_10 >= 6:
                ticker_rating = "Overweight"
            elif ticker_score_10 <= 2.5:
                ticker_rating = "Sell"
            elif ticker_score_10 <= 4:
                ticker_rating = "Underweight"
            else:
                ticker_rating = "Hold"
            ticker_evidence = (
                f"{ticker_upper} có {_fmt_int(ticker_row['post_count'])} dòng/post, "
                f"attention {_fmt(ticker_row['attention'])}, reaction sentiment score "
                f"{_fmt(ticker_row['sentiment_score'])}."
            )

    trends, _ = _read_trends(limit=8)
    trends_evidence = (
        "; ".join(
            f"{row.get('Trends', '')}: volume {row.get('Search volume', '')}"
            for row in trends[:5]
        )
        if trends
        else "Không tìm thấy file Google Trends local."
    )

    if market_score_raw > 0.2:
        crowding_note = (
            "- Attention cao va score tich cuc co the xac nhan tam ly thuan loi, "
            "nhung van can kiem tra dong tien/gia co xac nhan khong."
        )
    elif market_score_raw >= -0.2:
        crowding_note = (
            "- Attention cao nhung score yeu/mixed nen duoc xem nhu canh bao crowding "
            "hon la bullish confirmation."
        )
    else:
        crowding_note = (
            "- Attention cao voi score tieu cuc la canh bao rui ro sentiment xau "
            "hoac phan ung phong thu cua thi truong."
        )

    final_rating = ticker_rating if ticker_row is not None else market_rating

    return "\n\n".join(
        [
            "## Mã cổ phiếu",
            ticker_upper,
            "## Ngày đánh giá",
            end.strftime("%Y-%m-%d"),
            "## Nhận định tổng quát",
            (
                f"Social sentiment tổng thể là {band} với score {score_10}/10 và confidence {confidence}; "
                f"nguồn dữ liệu là `{path}`, cửa sổ {start.date()} đến {end.date()}."
            ),
            f"## Luận điểm 1 - Kết luận: {market_rating}",
            (
                f"- Luận cứ 1 - Dẫn chứng: Tâm lý thị trường chung nghiêng "
                f"{'tích cực' if market_score_raw > 0.2 else 'tiêu cực' if market_score_raw < -0.2 else 'trung tính'}; "
                f"Dẫn chứng: {_fmt_int(market_agg['post_count'])} dòng/post, attention index "
                f"{_fmt(market_agg['attention'])}, reaction sentiment score {_fmt(market_score_raw)}."
            ),
            f"- Luận cứ 2 - Dẫn chứng: Nhóm mã được chú ý nhất phản ánh mood thị trường; Dẫn chứng: {top_attention_evidence}.",
            f"## Luận điểm 2 - Kết luận: {ticker_rating}",
            f"- Luận cứ 1 - Dẫn chứng: Tín hiệu riêng của ticker được đánh giá theo dữ liệu local; Dẫn chứng: {ticker_evidence}",
            "- Luận cứ 2 - Dẫn chứng: Tín hiệu ticker phải được xem như bổ trợ, không phải tín hiệu giá độc lập; Dẫn chứng: dữ liệu chỉ gồm counters tổng hợp, không có nội dung từng bài viết.",
            "## Luận điểm 3 - Kết luận: Hold",
            f"- Luận cứ 1 - Dẫn chứng: Google Trends chỉ là bối cảnh tìm kiếm đại chúng tại Việt Nam; Dẫn chứng: {trends_evidence}.",
            f"- Luận cứ 2 - Dẫn chứng: {crowding_note.removeprefix('- ')} Dẫn chứng: attention và score cần được đối chiếu với market, news và fundamentals.",
            "## Kết luận tổng",
            (
                f"Kết luận tổng: {final_rating}. Social sentiment hiện ở band {band}, "
                f"score {score_10}/10, confidence {confidence}; chỉ nên dùng như tín hiệu bổ trợ "
                "và cần đối chiếu với phân tích kỹ thuật, tin tức và cơ bản."
            ),
        ]
    )
