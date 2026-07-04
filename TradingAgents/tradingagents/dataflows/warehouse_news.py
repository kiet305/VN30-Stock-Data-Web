"""Warehouse-backed news data for TradingAgents."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from psycopg2 import sql

from tradingagents.dataflows.warehouse_market import (
    INDEX_TICKERS,
    _read_sql,
    _schema,
    _warehouse_symbol,
)


NEWS_TABLE = "warehouse_news"
NEWS_DATE_EXPR = "CASE WHEN date_posted::text ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN date_posted::date END"
NEWS_SENTIMENT_EXPR = "CASE WHEN UPPER(COALESCE(sentiment, '')) ~ '^[A-Z]{2,5}[0-9]?$' THEN '' ELSE sentiment END"
NEWS_SOURCE_EXPR = "CASE WHEN TRIM(COALESCE(source, '')) = '[]' THEN '' ELSE source END"
NEWS_BLANK_TICKER_EXPR = "COALESCE(NULLIF(TRIM(ticker), ''), '') = ''"
NEWS_BAD_BLANK_TICKER_EXPR = (
    f"({NEWS_BLANK_TICKER_EXPR} AND UPPER(COALESCE(sentiment, '')) ~ '^[A-Z]{{2,5}}[0-9]?$')"
)


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def _fmt(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()


def _news_query(
    where_sql: str,
    order_sql: str = f"ORDER BY {NEWS_DATE_EXPR} DESC, ticker NULLS LAST",
) -> sql.Composed:
    return sql.SQL(
        """
        SELECT
            url,
            title,
            date_posted,
            {sentiment_sql} AS sentiment,
            ticker,
            {source_sql} AS source,
            summary,
            section,
            tags
        FROM {schema}.{table}
        {where_sql}
        {order_sql}
        """
    ).format(
        schema=sql.Identifier(_schema()),
        table=sql.Identifier(NEWS_TABLE),
        sentiment_sql=sql.SQL(NEWS_SENTIMENT_EXPR),
        source_sql=sql.SQL(NEWS_SOURCE_EXPR),
        where_sql=sql.SQL(where_sql),
        order_sql=sql.SQL(order_sql),
    )


def _render_news(
    title: str,
    rows: pd.DataFrame,
    empty_message: str,
    ref_prefix: str = "N",
) -> str:
    if rows.empty:
        return empty_message

    lines = [title, "", f"Source: {_schema()}.{NEWS_TABLE}", f"Articles returned: {len(rows)}", ""]
    lines += [
        "## Evidence links",
        "",
        "| Ref | Date | Ticker | Sentiment | Source | Title | Link |",
        "|---|---|---|---|---|---|---|",
    ]
    prepared_rows = []
    for idx, (_, row) in enumerate(rows.iterrows(), start=1):
        headline = _fmt(row.get("title")) or "Untitled"
        source = _fmt(row.get("source")) or "Unknown"
        date_posted = _fmt(row.get("date_posted"))
        ticker = _fmt(row.get("ticker"))
        sentiment = _fmt(row.get("sentiment"))
        summary = _fmt(row.get("summary"))
        url = _fmt(row.get("url"))
        ref = f"{ref_prefix}{idx}"
        prepared_rows.append((ref, headline, source, date_posted, ticker, sentiment, summary, url))
        link = f"[link]({url})" if url else ""
        lines.append(
            f"| [{ref}] | {date_posted} | {ticker} | {sentiment} | "
            f"{source} | {headline} | {link} |"
        )

    lines += ["", "## Article details", ""]
    for ref, headline, source, date_posted, ticker, sentiment, summary, url in prepared_rows:
        meta = [item for item in (date_posted, source, ticker, sentiment) if item]
        lines.append(f"### [{ref}] {headline}")
        if meta:
            lines.append(f"- Metadata: {' | '.join(meta)}")
        if summary:
            lines.append(summary)
        if url:
            lines.append(f"Link: {url}")
        lines.append("")

    sentiment_counts = rows["sentiment"].fillna("").replace("", "Unlabeled").value_counts()
    if not sentiment_counts.empty:
        lines += ["## Sentiment distribution", "", "| Sentiment | Count |", "|---|---:|"]
        for sentiment, count in sentiment_counts.items():
            lines.append(f"| {sentiment} | {int(count)} |")

    return "\n".join(lines)


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    """Return ticker-specific news from the warehouse."""
    symbol = _warehouse_symbol(ticker)
    _parse_date(start_date)
    _parse_date(end_date)
    query = _news_query(
        """
        WHERE UPPER(ticker) = UPPER(%s)
          AND {date_expr} BETWEEN %s AND %s
        """.format(date_expr=NEWS_DATE_EXPR),
        f"ORDER BY {NEWS_DATE_EXPR} DESC, source, title",
    )
    df = _read_sql(query, (symbol, start_date, end_date))
    return _render_news(
        f"## Warehouse news for {symbol}, from {start_date} to {end_date}",
        df,
        f"No warehouse news found for {symbol} between {start_date} and {end_date}.",
        ref_prefix="N",
    )


def get_global_news(
    curr_date: str,
    look_back_days: Optional[int] = None,
    limit: Optional[int] = None,
) -> str:
    """Return broad market/macro news from the warehouse."""
    from tradingagents.dataflows.config import get_config

    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]

    end_dt = _parse_date(curr_date)
    start_dt = end_dt - timedelta(days=int(look_back_days))
    start_date = start_dt.strftime("%Y-%m-%d")

    index_tickers = list(INDEX_TICKERS)
    query = _news_query(
        """
        WHERE {date_expr} BETWEEN %s AND %s
          AND (
            {blank_ticker_expr}
            OR UPPER(ticker) = ANY(%s)
          )
          AND NOT {bad_blank_ticker_expr}
        """.format(
            date_expr=NEWS_DATE_EXPR,
            blank_ticker_expr=NEWS_BLANK_TICKER_EXPR,
            bad_blank_ticker_expr=NEWS_BAD_BLANK_TICKER_EXPR,
        ),
        f"ORDER BY {NEWS_DATE_EXPR} DESC, source, title LIMIT %s",
    )
    df = _read_sql(query, (start_date, curr_date, index_tickers, int(limit)))
    return _render_news(
        f"## Warehouse global market news, from {start_date} to {curr_date}",
        df,
        f"No warehouse global market news found between {start_date} and {curr_date}.",
        ref_prefix="G",
    )
