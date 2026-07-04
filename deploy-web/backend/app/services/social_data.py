from __future__ import annotations

import csv
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.schemas import SocialResponse, SocialTickerItem


SOCIAL_TIMEZONE = timezone(timedelta(hours=7))


def _trend_data_dir() -> Path:
    configured = os.getenv("TREND_DATA_DIR")
    if configured:
        return Path(configured)

    container_path = Path("/app/trend")
    if container_path.exists():
        return container_path

    return Path(__file__).resolve().parents[4] / "trend"


def _selected_social_file() -> Path:
    configured_file = os.getenv("SOCIAL_DATA_FILE", "social.csv")
    social_file = Path(configured_file)
    if not social_file.is_absolute():
        social_file = _trend_data_dir() / social_file
    if not social_file.exists():
        raise FileNotFoundError(f"Không tìm thấy file social: {social_file}")

    return social_file


def _to_float(value: str | None) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def _to_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _interest_score(metrics: dict[str, float]) -> float:
    return (
        metrics["likes"] * 1.0
        + metrics["shares"] * 2.2
        + metrics["love"] * 1.15
        + metrics["wow"] * 1.35
        + metrics["haha"] * 1.0
        + metrics["sad"] * 1.0
    )


def get_social_rankings(limit: int = 50) -> SocialResponse:
    social_file = _selected_social_file()
    updated_at = datetime.fromtimestamp(social_file.stat().st_mtime, tz=SOCIAL_TIMEZONE)

    grouped: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "posts": 0,
            "dates": set(),
            "latest_date": None,
            "likes": 0.0,
            "shares": 0.0,
            "love": 0.0,
            "wow": 0.0,
            "haha": 0.0,
            "sad": 0.0,
        }
    )
    all_dates: list[date] = []

    with social_file.open(encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    for row in rows:
        ticker = (row.get("ticker") or "").strip().upper()
        if not ticker:
            continue

        row_date = _to_date(row.get("date"))
        if row_date:
            all_dates.append(row_date)

        bucket = grouped[ticker]
        post_count = max(int(_to_float(row.get("post_count"))), 1)
        bucket["posts"] = int(bucket["posts"]) + post_count
        if row_date:
            dates = bucket["dates"]
            assert isinstance(dates, set)
            dates.add(row_date)
            latest_date = bucket["latest_date"]
            if latest_date is None or row_date > latest_date:
                bucket["latest_date"] = row_date

        bucket["likes"] = float(bucket["likes"]) + _to_float(row.get("likesCount"))
        bucket["shares"] = float(bucket["shares"]) + _to_float(row.get("sharesCount"))
        bucket["love"] = float(bucket["love"]) + _to_float(row.get("reactionLoveCount"))
        bucket["wow"] = float(bucket["wow"]) + _to_float(row.get("reactionWowCount"))
        bucket["haha"] = float(bucket["haha"]) + _to_float(row.get("reactionHahaCount"))
        bucket["sad"] = float(bucket["sad"]) + _to_float(row.get("reactionSadCount"))

    scored_rows: list[dict[str, object]] = []
    for ticker, values in grouped.items():
        metrics = {
            "likes": float(values["likes"]),
            "shares": float(values["shares"]),
            "love": float(values["love"]),
            "wow": float(values["wow"]),
            "haha": float(values["haha"]),
            "sad": float(values["sad"]),
        }
        interest_score = int(values["posts"])
        total_interactions = sum(metrics.values())
        dates = values["dates"]
        assert isinstance(dates, set)

        scored_rows.append(
            {
                "ticker": ticker,
                "interest_score": interest_score,
                "total_interactions": total_interactions,
                "posts": int(values["posts"]),
                "active_days": len(dates),
                "latest_date": values["latest_date"],
                **metrics,
            }
        )

    scored_rows.sort(key=lambda item: (-int(item["posts"]), -float(item["total_interactions"]), str(item["ticker"])))
    total_score = sum(float(item["interest_score"]) for item in scored_rows)

    items = [
        SocialTickerItem(
            rank=index,
            ticker=str(item["ticker"]),
            interest_score=round(float(item["interest_score"]), 2),
            attention_share=round((float(item["interest_score"]) / total_score * 100) if total_score else 0.0, 2),
            total_interactions=round(float(item["total_interactions"]), 2),
            posts=int(item["posts"]),
            active_days=int(item["active_days"]),
            latest_date=item["latest_date"],
            likes=round(float(item["likes"]), 2),
            shares=round(float(item["shares"]), 2),
            love=round(float(item["love"]), 2),
            wow=round(float(item["wow"]), 2),
            haha=round(float(item["haha"]), 2),
            sad=round(float(item["sad"]), 2),
        )
        for index, item in enumerate(scored_rows[:limit], start=1)
    ]

    return SocialResponse(
        source_file=social_file.name,
        updated_at=updated_at,
        date_from=min(all_dates) if all_dates else None,
        date_to=max(all_dates) if all_dates else None,
        total_tickers=len(scored_rows),
        total_interest_score=round(total_score, 2),
        items=items,
    )
