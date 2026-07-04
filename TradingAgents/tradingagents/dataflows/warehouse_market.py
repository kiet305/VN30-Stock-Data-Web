"""Warehouse-backed market data for TradingAgents.

This module reads the project's PostgreSQL warehouse tables produced by the
Dagster pipeline. It is intentionally shaped like the existing yfinance data
vendor: every public function returns prompt-ready text and raises
``NoMarketDataError`` when a symbol/date range is genuinely unavailable so the
router can fall back to the next configured vendor.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Iterable, Optional

import numpy as np
import pandas as pd
import psycopg2
from psycopg2 import sql

from tradingagents.dataflows.symbol_utils import NoMarketDataError


DEFAULT_SCHEMA = "warehouse"
PRICES_TABLE = "warehouse_prices_1d"
OVERVIEW_TABLE = "warehouse_overview"
INDEX_TICKERS = ("VNINDEX", "VN30", "VN100", "HNX30", "UPCOMINDEX")

DEFAULT_SNAPSHOT_INDICATORS: tuple[str, ...] = (
    "close_10_ema",
    "close_50_sma",
    "close_200_sma",
    "rsi",
    "boll",
    "boll_ub",
    "boll_lb",
    "macd",
    "macds",
    "macdh",
    "atr",
    "vwma",
    "mfi",
    "obv",
    "cmf",
    "volume_20_sma",
    "volume_50_sma",
    "volume_ratio_20",
    "volume_zscore_20",
)

INDICATOR_DESCRIPTIONS = {
    "close_50_sma": (
        "50 SMA: A medium-term trend indicator. Usage: Identify trend "
        "direction and dynamic support/resistance."
    ),
    "close_200_sma": (
        "200 SMA: A long-term trend benchmark. Usage: Confirm the broader "
        "market trend and strategic bias."
    ),
    "close_10_ema": (
        "10 EMA: A responsive short-term average. Usage: Capture quick "
        "momentum shifts and potential entry timing."
    ),
    "macd": "MACD: Difference between 12-day and 26-day EMAs.",
    "macds": "MACD Signal: 9-day EMA of the MACD line.",
    "macdh": "MACD Histogram: MACD minus signal line.",
    "rsi": "RSI: 14-period momentum oscillator for overbought/oversold pressure.",
    "boll": "Bollinger Middle: 20-day moving average.",
    "boll_ub": "Bollinger Upper Band: 20-day average plus two standard deviations.",
    "boll_lb": "Bollinger Lower Band: 20-day average minus two standard deviations.",
    "atr": "ATR: 14-period average true range, a volatility measure.",
    "vwma": "VWMA: 20-day volume-weighted moving average.",
    "mfi": "MFI: 14-period money-flow index using price and volume.",
    "obv": (
        "OBV: On-Balance Volume, a cumulative signed-volume measure. "
        "Usage: Confirm whether volume is accumulating with price advances "
        "or distributing during declines."
    ),
    "cmf": (
        "CMF: 20-period Chaikin Money Flow. Usage: Identify accumulation "
        "(positive values) or distribution (negative values) using close "
        "location within the high-low range and volume."
    ),
    "volume_20_sma": "Volume 20 SMA: average daily volume over the last 20 trading rows.",
    "volume_50_sma": "Volume 50 SMA: average daily volume over the last 50 trading rows.",
    "volume_ratio_20": (
        "Relative Volume 20D: current volume divided by 20-day average volume. "
        "Values above 1.0 indicate above-average participation."
    ),
    "volume_zscore_20": (
        "Volume Z-Score 20D: how many 20-day standard deviations current "
        "volume is above or below its 20-day average."
    ),
}

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NUMERIC_RE = r"^-?[0-9]+(\.[0-9]+)?$"


def _env(primary: str, fallback: str | None = None, default: str | None = None) -> str | None:
    value = os.getenv(primary)
    if value not in (None, ""):
        return value
    if fallback:
        value = os.getenv(fallback)
        if value not in (None, ""):
            return value
    return default


def _schema() -> str:
    value = _env("TRADINGAGENTS_WAREHOUSE_SCHEMA", "WAREHOUSE_SCHEMA", DEFAULT_SCHEMA)
    if not value or not _IDENT_RE.fullmatch(value):
        raise ValueError(f"Unsafe warehouse schema name: {value!r}")
    return value


def _warehouse_symbol(symbol: str) -> str:
    """Normalize common Vietnamese ticker spellings to warehouse tickers."""
    s = str(symbol).strip().upper()
    for suffix in (".VN", ".VND", ".HOSE", ".HSX", ".HNX", ".UPCOM"):
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


@contextmanager
def _connect():
    host = _env("TRADINGAGENTS_WAREHOUSE_POSTGRES_HOST", "POSTGRES_HOST", "localhost")
    port = _env("TRADINGAGENTS_WAREHOUSE_POSTGRES_PORT", "POSTGRES_PORT", "5400")
    dbname = _env("TRADINGAGENTS_WAREHOUSE_POSTGRES_DB", "POSTGRES_DB", "postgres")
    user = _env("TRADINGAGENTS_WAREHOUSE_POSTGRES_USER", "POSTGRES_USER", "admin")
    password = _env("TRADINGAGENTS_WAREHOUSE_POSTGRES_PASSWORD", "POSTGRES_PASSWORD", "")
    conn = psycopg2.connect(
        host=host,
        port=int(port),
        dbname=dbname,
        user=user,
        password=password,
    )
    try:
        yield conn
    finally:
        conn.close()


def _read_sql(query: sql.Composed, params: tuple = ()) -> pd.DataFrame:
    with _connect() as conn:
        query_text = query.as_string(conn) if hasattr(query, "as_string") else str(query)
        with conn.cursor() as cur:
            cur.execute(query_text, params)
            if cur.description is None:
                return pd.DataFrame()
            columns = [desc[0] for desc in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=columns)


def _prices_query(select_sql: str, where_sql: str, order_sql: str = "ORDER BY date") -> sql.Composed:
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
        table=sql.Identifier(PRICES_TABLE),
        where_sql=sql.SQL(where_sql),
        order_sql=sql.SQL(order_sql),
    )


def _base_select() -> str:
    return """
        ticker,
        date::date AS "Date",
        open AS "Open",
        high AS "High",
        low AS "Low",
        close AS "Close",
        volume AS "Volume",
        market_cap,
        pe,
        pb,
        chg_1d,
        chg_1w,
        chg_1m,
        chg_3m,
        chg_6m,
        chg_1y,
        chg_3y
    """


def _history(symbol: str, curr_date: str, min_rows: int = 260) -> pd.DataFrame:
    ticker = _warehouse_symbol(symbol)
    datetime.strptime(curr_date, "%Y-%m-%d")
    query = _prices_query(
        _base_select(),
        "WHERE UPPER(ticker) = UPPER(%s) AND date::date <= %s",
        "ORDER BY date DESC LIMIT %s",
    )
    df = _read_sql(query, (ticker, curr_date, int(min_rows)))
    if df.empty:
        raise NoMarketDataError(ticker, ticker, f"no warehouse rows on or before {curr_date}")
    df = df.sort_values("Date").reset_index(drop=True)
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def _fmt(value) -> str:
    if value is None:
        return "N/A"
    try:
        if pd.isna(value):
            return "N/A"
    except TypeError:
        pass
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (np.integer, int)):
        return f"{int(value)}"
    if isinstance(value, (np.floating, float)):
        return f"{float(value):.2f}"
    return str(value)


def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close = pd.to_numeric(out["Close"], errors="coerce")
    high = pd.to_numeric(out["High"], errors="coerce")
    low = pd.to_numeric(out["Low"], errors="coerce")
    volume = pd.to_numeric(out["Volume"], errors="coerce")

    out["close_10_ema"] = close.ewm(span=10, adjust=False).mean()
    out["close_50_sma"] = close.rolling(50, min_periods=1).mean()
    out["close_200_sma"] = close.rolling(200, min_periods=1).mean()

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    out["macd"] = ema12 - ema26
    out["macds"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["macdh"] = out["macd"] - out["macds"]

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14, min_periods=14).mean()
    avg_loss = loss.rolling(14, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out["rsi"] = 100 - (100 / (1 + rs))
    out.loc[(avg_loss == 0) & (avg_gain > 0), "rsi"] = 100
    out.loc[(avg_loss == 0) & (avg_gain == 0), "rsi"] = 50

    out["boll"] = close.rolling(20, min_periods=1).mean()
    std20 = close.rolling(20, min_periods=2).std()
    out["boll_ub"] = out["boll"] + 2 * std20
    out["boll_lb"] = out["boll"] - 2 * std20

    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr"] = true_range.rolling(14, min_periods=1).mean()

    out["volume_20_sma"] = volume.rolling(20, min_periods=1).mean()
    out["volume_50_sma"] = volume.rolling(50, min_periods=1).mean()
    out["volume_ratio_20"] = volume / out["volume_20_sma"].replace(0, np.nan)
    vol20_std = volume.rolling(20, min_periods=2).std()
    out["volume_zscore_20"] = (volume - out["volume_20_sma"]) / vol20_std.replace(0, np.nan)

    volume_filled = volume.fillna(0)
    direction = pd.Series(np.sign(close.diff()), index=out.index).fillna(0)
    out["obv"] = (direction * volume_filled).cumsum()

    money_flow_multiplier = (
        ((close - low) - (high - close))
        / (high - low).replace(0, np.nan)
    ).replace([np.inf, -np.inf], np.nan).fillna(0)
    money_flow_volume = money_flow_multiplier * volume_filled
    out["cmf"] = (
        money_flow_volume.rolling(20, min_periods=1).sum()
        / volume_filled.rolling(20, min_periods=1).sum().replace(0, np.nan)
    )

    vol20 = volume.rolling(20, min_periods=1).sum()
    out["vwma"] = (close * volume).rolling(20, min_periods=1).sum() / vol20.replace(0, np.nan)

    typical = (high + low + close) / 3
    raw_money = typical * volume
    positive_flow = raw_money.where(typical.diff() > 0, 0)
    negative_flow = raw_money.where(typical.diff() < 0, 0)
    pos14 = positive_flow.rolling(14, min_periods=14).sum()
    neg14 = negative_flow.rolling(14, min_periods=14).sum()
    money_ratio = pos14 / neg14.replace(0, np.nan)
    out["mfi"] = 100 - (100 / (1 + money_ratio))
    return out


def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """Return OHLCV and warehouse market metrics for a date range."""
    ticker = _warehouse_symbol(symbol)
    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")
    query = _prices_query(
        _base_select(),
        "WHERE UPPER(ticker) = UPPER(%s) AND date::date BETWEEN %s AND %s",
    )
    df = _read_sql(query, (ticker, start_date, end_date))
    if df.empty:
        raise NoMarketDataError(ticker, ticker, f"no warehouse rows between {start_date} and {end_date}")

    for col in ("Open", "High", "Low", "Close", "market_cap"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(2)
    header = (
        f"# Warehouse stock data for {ticker} from {start_date} to {end_date}\n"
        f"# Source: {_schema()}.{PRICES_TABLE}\n"
        f"# Total records: {len(df)}\n"
        f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    return header + df.to_csv(index=False)


def get_indicator(symbol: str, indicator: str, curr_date: str, look_back_days: int = 30) -> str:
    """Return one technical indicator calculated from warehouse OHLCV rows."""
    ind = indicator.strip().lower()
    if ind not in INDICATOR_DESCRIPTIONS:
        raise ValueError(
            f"Indicator {indicator} is not supported by warehouse. "
            f"Please choose from: {list(INDICATOR_DESCRIPTIONS.keys())}"
        )

    look_back_days = int(look_back_days)
    rows_needed = max(420, look_back_days)
    df = _add_indicators(_history(symbol, curr_date, min_rows=rows_needed))
    start = pd.to_datetime(curr_date) - pd.Timedelta(days=look_back_days)
    window = df[(df["Date"] >= start) & (df["Date"] <= pd.to_datetime(curr_date))]
    if window.empty:
        ticker = _warehouse_symbol(symbol)
        raise NoMarketDataError(ticker, ticker, f"no indicator rows through {curr_date}")

    lines = [
        f"{row['Date'].strftime('%Y-%m-%d')}: {_fmt(row.get(ind))}"
        for _, row in window.iterrows()
    ]
    return (
        f"## {ind} values from {start.strftime('%Y-%m-%d')} to {curr_date}\n\n"
        + "\n".join(lines)
        + f"\n\nSource: {_schema()}.{PRICES_TABLE} (warehouse trading rows only)."
        + "\n\n"
        + INDICATOR_DESCRIPTIONS[ind]
    )


def resolve_instrument_identity(symbol: str) -> dict[str, str]:
    """Resolve ticker identity from warehouse overview; fail open on errors."""
    ticker = _warehouse_symbol(symbol)
    query = sql.SQL(
        """
        SELECT ticker, name, trading_floor, industry, subindustry, cap_group, sector
        FROM {schema}.{table}
        WHERE UPPER(ticker) = UPPER(%s)
        LIMIT 1
        """
    ).format(schema=sql.Identifier(_schema()), table=sql.Identifier(OVERVIEW_TABLE))
    try:
        df = _read_sql(query, (ticker,))
    except Exception:
        return {}
    if df.empty:
        return {}
    row = df.iloc[0]
    identity: dict[str, str] = {}
    if pd.notna(row.get("name")):
        identity["company_name"] = str(row["name"])
    industry = row.get("industry")
    sector = row.get("sector")
    subindustry = row.get("subindustry")
    trading_floor = row.get("trading_floor")
    if pd.notna(sector):
        identity["sector"] = str(sector)
    elif pd.notna(industry):
        identity["sector"] = str(industry)
    if pd.notna(subindustry) and not str(subindustry).strip().isdigit():
        identity["industry"] = str(subindustry)
    if pd.notna(trading_floor) and str(trading_floor).strip().upper() not in {"TRUE", "FALSE"}:
        identity["exchange"] = str(trading_floor)
    if pd.notna(row.get("cap_group")):
        identity["cap_group"] = str(row["cap_group"])
    identity["quote_type"] = "EQUITY"
    return identity


def _overview_lines(symbol: str) -> list[str]:
    identity = resolve_instrument_identity(symbol)
    if not identity:
        return []
    labels = {
        "company_name": "Company",
        "sector": "Industry",
        "industry": "Subindustry",
        "exchange": "Trading floor",
        "cap_group": "Capitalization group",
    }
    return [f"| {labels[k]} | {v} |" for k, v in identity.items() if k in labels]


def _market_context(latest_date: str) -> str:
    """Return market breadth and index context for the snapshot date."""
    numeric_chg = (
        f"CASE WHEN chg_1d ~ '{_NUMERIC_RE}' THEN chg_1d::numeric ELSE NULL END"
    )
    breadth_query = sql.SQL(
        """
        SELECT
            COUNT(*) AS stocks,
            COUNT(*) FILTER (WHERE {numeric_chg} > 0) AS advancers,
            COUNT(*) FILTER (WHERE {numeric_chg} < 0) AS decliners,
            COUNT(*) FILTER (WHERE {numeric_chg} = 0) AS unchanged,
            ROUND(AVG({numeric_chg}), 2) AS avg_chg_1d,
            ROUND((SUM(volume) / 1000000.0)::numeric, 2) AS total_volume_m
        FROM {schema}.{table}
        WHERE date::date = %s AND ticker <> ALL(%s)
        """
    ).format(
        numeric_chg=sql.SQL(numeric_chg),
        schema=sql.Identifier(_schema()),
        table=sql.Identifier(PRICES_TABLE),
    )
    index_query = _prices_query(
        _base_select(),
        "WHERE date::date = %s AND ticker = ANY(%s)",
        "ORDER BY ticker",
    )
    try:
        breadth = _read_sql(breadth_query, (latest_date, list(INDEX_TICKERS)))
        indices = _read_sql(index_query, (latest_date, list(INDEX_TICKERS)))
    except Exception as exc:
        return f"Market context unavailable from warehouse ({type(exc).__name__})."

    lines = ["### Same-day market context", ""]
    if not breadth.empty:
        row = breadth.iloc[0]
        lines += [
            "| Metric | Value |",
            "|---|---:|",
            f"| Stocks covered | {_fmt(row.get('stocks'))} |",
            f"| Advancers | {_fmt(row.get('advancers'))} |",
            f"| Decliners | {_fmt(row.get('decliners'))} |",
            f"| Unchanged | {_fmt(row.get('unchanged'))} |",
            f"| Average 1D change (%) | {_fmt(row.get('avg_chg_1d'))} |",
            f"| Total volume (million shares) | {_fmt(row.get('total_volume_m'))} |",
            "",
        ]
    if not indices.empty:
        lines += ["### Index references", "", "| Ticker | Close | Chg 1D | Chg 1W | Chg 1M | P/E | P/B |", "|---|---:|---:|---:|---:|---:|---:|"]
        for _, row in indices.iterrows():
            lines.append(
                f"| {row['ticker']} | {_fmt(row.get('Close'))} | {_fmt(row.get('chg_1d'))} | "
                f"{_fmt(row.get('chg_1w'))} | {_fmt(row.get('chg_1m'))} | "
                f"{_fmt(row.get('pe'))} | {_fmt(row.get('pb'))} |"
            )
    return "\n".join(lines)


def build_verified_market_snapshot(
    symbol: str,
    curr_date: str,
    look_back_days: int = 30,
    indicators: Optional[Iterable[str]] = None,
) -> str:
    """Render a deterministic market snapshot from warehouse data."""
    ticker = _warehouse_symbol(symbol)
    rows_needed = max(420, int(look_back_days))
    df = _add_indicators(_history(ticker, curr_date, min_rows=rows_needed))
    latest = df.iloc[-1]
    latest_date = latest["Date"].strftime("%Y-%m-%d")
    recent = df.tail(max(1, min(int(look_back_days), 30)))

    lines = [
        f"## Verified warehouse market data snapshot for {ticker}",
        "",
        f"- Requested analysis date: {curr_date}",
        f"- Latest trading row used: {latest_date}",
        f"- Source table: {_schema()}.{PRICES_TABLE}",
        "- Rows after the requested analysis date are excluded before verification.",
        "",
    ]

    overview = _overview_lines(ticker)
    if overview:
        lines += ["### Instrument identity", "", "| Field | Value |", "|---|---|", *overview, ""]

    lines += [
        "### Latest verified OHLCV and market metrics",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    for field in ("Open", "High", "Low", "Close", "Volume"):
        lines.append(f"| {field} | {_fmt(latest.get(field))} |")
    for field in ("market_cap", "pe", "pb", "chg_1d", "chg_1w", "chg_1m", "chg_3m", "chg_6m", "chg_1y", "chg_3y"):
        lines.append(f"| {field} | {_fmt(latest.get(field))} |")

    selected = tuple(indicators or DEFAULT_SNAPSHOT_INDICATORS)
    lines += ["", "### Verified technical indicators (latest row)", "", "| Indicator | Value |", "|---|---:|"]
    for name in selected:
        lines.append(f"| {name} | {_fmt(latest.get(name))} |")

    lines += ["", f"### Recent verified closes (last {len(recent)} trading rows)", "", "| Date | Close | Volume |", "|---|---:|---:|"]
    for _, row in recent.iterrows():
        lines.append(f"| {row['Date'].strftime('%Y-%m-%d')} | {_fmt(row.get('Close'))} | {_fmt(row.get('Volume'))} |")

    lines += [
        "",
        _market_context(latest_date),
        "",
        "Use this snapshot as the source of truth for exact OHLCV, price-level, "
        "valuation, performance-change, and indicator-value claims. If another "
        "tool output conflicts with it, flag the discrepancy rather than "
        "inventing a reconciled number.",
    ]
    return "\n".join(lines)
