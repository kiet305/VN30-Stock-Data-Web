import pandas as pd
import pytest

from tradingagents.dataflows import warehouse_news


NEWS_COLUMNS = [
    "url",
    "title",
    "date_posted",
    "sentiment",
    "ticker",
    "source",
    "summary",
    "section",
    "tags",
]


@pytest.mark.unit
def test_news_date_filter_casts_date_posted_to_text_before_regex(monkeypatch):
    seen: list[tuple[str, str]] = []
    original_news_query = warehouse_news._news_query

    def spy_news_query(where_sql: str, order_sql: str = ""):
        seen.append((where_sql, order_sql))
        return original_news_query(where_sql, order_sql)

    monkeypatch.setattr(warehouse_news, "_news_query", spy_news_query)
    monkeypatch.setattr(
        warehouse_news,
        "_read_sql",
        lambda query, params=(): pd.DataFrame(columns=NEWS_COLUMNS),
    )

    warehouse_news.get_news("HPG", "2026-06-25", "2026-07-03")

    where_sql, order_sql = seen[-1]
    combined_sql = f"{where_sql}\n{order_sql}"
    assert "date_posted ~" not in combined_sql
    assert "date_posted::text ~" in combined_sql
    assert "date_posted::date" in combined_sql


@pytest.mark.unit
def test_global_news_filters_blank_ticker_rows_with_ticker_like_sentiment(monkeypatch):
    seen: list[tuple[str, str]] = []
    original_news_query = warehouse_news._news_query

    def spy_news_query(where_sql: str, order_sql: str = ""):
        seen.append((where_sql, order_sql))
        return original_news_query(where_sql, order_sql)

    monkeypatch.setattr(warehouse_news, "_news_query", spy_news_query)
    monkeypatch.setattr(
        warehouse_news,
        "_read_sql",
        lambda query, params=(): pd.DataFrame(columns=NEWS_COLUMNS),
    )

    warehouse_news.get_global_news("2026-07-03", look_back_days=7, limit=5)

    where_sql, order_sql = seen[-1]
    combined_sql = f"{where_sql}\n{order_sql}"
    assert "AND NOT" in combined_sql
    assert "COALESCE(NULLIF(TRIM(ticker), ''), '') = ''" in combined_sql
    assert "UPPER(COALESCE(sentiment, '')) ~ '^[A-Z]{2,5}[0-9]?$'" in combined_sql
