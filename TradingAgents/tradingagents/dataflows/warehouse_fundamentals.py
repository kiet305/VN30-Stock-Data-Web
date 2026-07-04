"""Warehouse-backed fundamental data for TradingAgents."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

import pandas as pd
from psycopg2 import sql

from tradingagents.dataflows.warehouse_market import _read_sql, _schema, _warehouse_symbol


OVERVIEW_TABLE = "warehouse_overview"
REPORTS_TABLE = "warehouse_reports"
METRICS_TABLE = "warehouse_ticker_metric"
SHAREHOLDERS_TABLE = "warehouse_shareholders"
OFFICERS_TABLE = "warehouse_officers"
EVENTS_TABLE = "warehouse_events"

REPORT_TYPE_LABELS = {
    "BS": "Balance Sheet",
    "CF": "Cash Flow",
    "IS": "Income Statement",
}


def _parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.now()
    return datetime.strptime(value, "%Y-%m-%d")


def _fmt(value, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        if pd.isna(value):
            return "N/A"
    except TypeError:
        pass
    if isinstance(value, (int, float)) or hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, (int, float)):
        return f"{float(value):,.{decimals}f}"
    return str(value).strip() or "N/A"


def _fmt_pct(value) -> str:
    try:
        if value is None or pd.isna(value):
            return "N/A"
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def _period_key(year: int, quarter: int) -> str:
    return f"{int(year)}Q{int(quarter)}"


def _period_end(year: int, quarter: int) -> pd.Timestamp:
    month_day = {
        1: (3, 31),
        2: (6, 30),
        3: (9, 30),
        4: (12, 31),
    }.get(int(quarter), (12, 31))
    return pd.Timestamp(year=int(year), month=month_day[0], day=month_day[1])


def _table(headers: list[str], rows: list[list[str]], align_right: set[int] | None = None) -> str:
    align_right = align_right or set()
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---:" if i in align_right else "---" for i in range(len(headers))) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item).replace("\n", " ") for item in row) + " |")
    return "\n".join(lines)


def _query_table(table: str, select_sql: str, where_sql: str, order_sql: str = "") -> sql.Composed:
    return sql.SQL(
        """
        SELECT {select_sql}
        FROM {schema}.{table}
        {where_sql}
        {order_sql}
        """
    ).format(
        select_sql=sql.SQL(select_sql),
        schema=sql.Identifier(_schema()),
        table=sql.Identifier(table),
        where_sql=sql.SQL(where_sql),
        order_sql=sql.SQL(order_sql),
    )


def _load_reports(
    ticker: str,
    report_type: str,
    freq: str = "quarterly",
    curr_date: str | None = None,
    periods: int = 8,
) -> pd.DataFrame:
    symbol = _warehouse_symbol(ticker)
    report_type = report_type.upper()
    trade_date = pd.Timestamp(_parse_date(curr_date).date())
    query = _query_table(
        REPORTS_TABLE,
        "ticker, year, quarter, report_type, criteria, value",
        "WHERE UPPER(ticker) = UPPER(%s) AND report_type = %s",
        "ORDER BY year DESC, quarter DESC, criteria",
    )
    df = _read_sql(query, (symbol, report_type))
    if df.empty:
        return df

    df["period_end"] = [
        _period_end(int(row.year), int(row.quarter)) for row in df.itertuples()
    ]
    df = df[df["period_end"] <= trade_date]
    if freq.lower().startswith("annual"):
        df = df[df["quarter"].astype(int) == 4]

    period_frame = (
        df[["year", "quarter", "period_end"]]
        .drop_duplicates()
        .sort_values(["year", "quarter"], ascending=False)
        .head(periods)
    )
    if period_frame.empty:
        return pd.DataFrame()
    keys = {(int(row.year), int(row.quarter)) for row in period_frame.itertuples()}
    df = df[df.apply(lambda row: (int(row["year"]), int(row["quarter"])) in keys, axis=1)]
    return df.sort_values(["year", "quarter", "criteria"], ascending=[False, False, True])


def _render_statement(
    ticker: str,
    report_type: str,
    freq: str = "quarterly",
    curr_date: str | None = None,
    periods: int = 8,
) -> str:
    symbol = _warehouse_symbol(ticker)
    df = _load_reports(symbol, report_type, freq, curr_date, periods)
    label = REPORT_TYPE_LABELS.get(report_type, report_type)
    if df.empty:
        return f"No warehouse {label} data found for {symbol} through {curr_date or 'today'}."

    df = df.copy()
    df["period"] = [
        _period_key(row.year, row.quarter) for row in df.itertuples()
    ]
    pivot = df.pivot_table(
        index="criteria",
        columns="period",
        values="value",
        aggfunc="first",
    )
    periods_order = (
        df[["year", "quarter", "period"]]
        .drop_duplicates()
        .sort_values(["year", "quarter"], ascending=False)["period"]
        .tolist()
    )
    pivot = pivot.reindex(columns=periods_order)

    rows = []
    for criteria, values in pivot.iterrows():
        rows.append([criteria, *[_fmt(values.get(period)) for period in periods_order]])

    return "\n".join(
        [
            f"## Warehouse {label} for {symbol}",
            "",
            f"- Frequency: {freq}",
            f"- Current analysis date: {curr_date or datetime.now().strftime('%Y-%m-%d')}",
            f"- Source table: {_schema()}.{REPORTS_TABLE}",
            "- Period filter: only fiscal periods ending on or before the analysis date are included.",
            "- Units: warehouse statement values, typically billion VND for Vietnamese equities.",
            "",
            _table(["Criteria", *periods_order], rows, set(range(1, len(periods_order) + 1))),
        ]
    )


def _overview(ticker: str) -> pd.DataFrame:
    query = _query_table(
        OVERVIEW_TABLE,
        "ticker, name, trading_floor, industry, subindustry, history, company_profile, issue_share, cap_group, date_fetched",
        "WHERE UPPER(ticker) = UPPER(%s)",
        "LIMIT 1",
    )
    return _read_sql(query, (_warehouse_symbol(ticker),))


def _metrics(ticker: str, curr_date: str | None = None, periods: int = 8) -> pd.DataFrame:
    trade_date = pd.Timestamp(_parse_date(curr_date).date())
    query = _query_table(
        METRICS_TABLE,
        """
        ticker, year, quarter, eps, bvps, roe, roa, ros, nim, industry,
        bvps_industry, roe_industry, roa_industry, ros_industry, nim_industry
        """,
        "WHERE UPPER(ticker) = UPPER(%s)",
        "ORDER BY year DESC, quarter DESC",
    )
    df = _read_sql(query, (_warehouse_symbol(ticker),))
    if df.empty:
        return df
    df["period_end"] = [
        _period_end(int(row.year), int(row.quarter)) for row in df.itertuples()
    ]
    return df[df["period_end"] <= trade_date].head(periods)


def _simple_rows(table: str, select_sql: str, ticker: str, order_sql: str, limit: int = 10) -> pd.DataFrame:
    query = _query_table(
        table,
        select_sql,
        "WHERE UPPER(ticker) = UPPER(%s)",
        f"{order_sql} LIMIT %s",
    )
    return _read_sql(query, (_warehouse_symbol(ticker), int(limit)))


def _render_overview_section(df: pd.DataFrame) -> str:
    if df.empty:
        return "No company overview found in warehouse."
    row = df.iloc[0]
    lines = [
        "## Company Profile",
        "",
        _table(
            ["Field", "Value"],
            [
                ["Ticker", _fmt(row.get("ticker"))],
                ["Name", _fmt(row.get("name"))],
                ["Exchange", _fmt(row.get("trading_floor"))],
                ["Industry", _fmt(row.get("industry"))],
                ["Subindustry", _fmt(row.get("subindustry"))],
                ["Capitalization group", _fmt(row.get("cap_group"))],
                ["Issue shares", _fmt(row.get("issue_share"), 0)],
                ["Data fetched", _fmt(row.get("date_fetched"))],
            ],
        ),
        "",
        "### Business Description",
        "",
        _fmt(row.get("company_profile")),
        "",
        "### Company History",
        "",
        _fmt(row.get("history"))[:2500],
    ]
    return "\n".join(lines)


def _render_metrics_section(df: pd.DataFrame) -> str:
    if df.empty:
        return "## Key Ratios\n\nNo warehouse ticker metrics found."
    rows = []
    for _, row in df.iterrows():
        rows.append(
            [
                _period_key(row["year"], row["quarter"]),
                _fmt(row.get("eps")),
                _fmt(row.get("bvps")),
                _fmt_pct(row.get("roe")),
                _fmt_pct(row.get("roa")),
                _fmt_pct(row.get("ros")),
                _fmt(row.get("bvps_industry")),
                _fmt_pct(row.get("roe_industry")),
                _fmt_pct(row.get("roa_industry")),
                _fmt_pct(row.get("ros_industry")),
            ]
        )
    return "\n".join(
        [
            "## Key Ratios And Industry Benchmarks",
            "",
            f"Source table: {_schema()}.{METRICS_TABLE}",
            "",
            _table(
                [
                    "Period",
                    "EPS",
                    "BVPS",
                    "ROE",
                    "ROA",
                    "ROS",
                    "Industry BVPS",
                    "Industry ROE",
                    "Industry ROA",
                    "Industry ROS",
                ],
                rows,
                set(range(1, 10)),
            ),
        ]
    )


def _statement_latest_summary(ticker: str, report_type: str, curr_date: str | None = None) -> str:
    df = _load_reports(ticker, report_type, "quarterly", curr_date, periods=1)
    label = REPORT_TYPE_LABELS.get(report_type, report_type)
    if df.empty:
        return f"## Latest {label} Summary\n\nNo warehouse data found."
    latest_period = _period_key(int(df.iloc[0]["year"]), int(df.iloc[0]["quarter"]))
    rows = [[row["criteria"], _fmt(row["value"])] for _, row in df.iterrows()]
    return "\n".join(
        [
            f"## Latest {label} Summary",
            "",
            f"- Period: {latest_period}",
            f"- Source table: {_schema()}.{REPORTS_TABLE}",
            "",
            _table(["Criteria", "Value"], rows, {1}),
        ]
    )


def _render_simple_table(title: str, df: pd.DataFrame, columns: Iterable[str], right_cols: set[int] | None = None) -> str:
    if df.empty:
        return f"## {title}\n\nNo warehouse data found."
    headers = [column.replace("_", " ").title() for column in columns]
    rows = [[_fmt(row.get(column)) for column in columns] for _, row in df.iterrows()]
    return "\n".join(["## " + title, "", _table(headers, rows, right_cols or set())])


def get_fundamentals(ticker: str, curr_date: str | None = None) -> str:
    """Return comprehensive warehouse fundamental context for a ticker."""
    symbol = _warehouse_symbol(ticker)
    overview = _overview(symbol)
    metrics = _metrics(symbol, curr_date)
    shareholders = _simple_rows(
        SHAREHOLDERS_TABLE,
        "share_holder, quantity, share_own_percent, update_date",
        symbol,
        "ORDER BY update_date DESC NULLS LAST, share_own_percent DESC NULLS LAST",
        limit=6,
    )
    officers = _simple_rows(
        OFFICERS_TABLE,
        "officer_name, officer_position, officer_own_quantity, officer_own_percent, update_date",
        symbol,
        "ORDER BY update_date DESC NULLS LAST, officer_own_percent DESC NULLS LAST",
        limit=6,
    )
    events = _simple_rows(
        EVENTS_TABLE,
        "event_title, event_type, ratio, value, public_date, issue_date, record_date, exright_date",
        symbol,
        "ORDER BY COALESCE(NULLIF(public_date, ''), '1900-01-01') DESC",
        limit=6,
    )

    return "\n\n".join(
        [
            f"# Warehouse Fundamentals: {symbol}",
            f"Current analysis date: {curr_date or datetime.now().strftime('%Y-%m-%d')}",
            f"Primary source schema: {_schema()}",
            _render_overview_section(overview),
            _render_metrics_section(metrics),
            _statement_latest_summary(symbol, "IS", curr_date),
            _statement_latest_summary(symbol, "BS", curr_date),
            _statement_latest_summary(symbol, "CF", curr_date),
            _render_simple_table(
                "Major Shareholders",
                shareholders,
                ["share_holder", "quantity", "share_own_percent", "update_date"],
                {1, 2},
            ),
            _render_simple_table(
                "Officers",
                officers,
                ["officer_name", "officer_position", "officer_own_quantity", "officer_own_percent", "update_date"],
                {2, 3},
            ),
            _render_simple_table(
                "Corporate Events",
                events,
                ["event_title", "event_type", "ratio", "value", "public_date", "issue_date", "record_date", "exright_date"],
                {2, 3},
            ),
        ]
    )


def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    return _render_statement(ticker, "BS", freq, curr_date, periods=6)


def get_cashflow(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    return _render_statement(ticker, "CF", freq, curr_date, periods=6)


def get_income_statement(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    return _render_statement(ticker, "IS", freq, curr_date, periods=6)
