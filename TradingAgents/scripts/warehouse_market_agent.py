"""Standalone warehouse-backed Market Analysis agent.

Run from the workspace root:

    python TradingAgents/scripts/warehouse_market_agent.py --ticker HPG --date 2026-01-29

The script intentionally avoids LangGraph/LLM dependencies so it can be tested
against the local data warehouse first. It reads PostgreSQL warehouse tables,
calculates deterministic technical indicators, and emits a markdown report.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from psycopg2 import sql


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tradingagents.dataflows.warehouse_market import (  # noqa: E402
    INDEX_TICKERS,
    OVERVIEW_TABLE,
    PRICES_TABLE,
    _add_indicators,
    _history,
    _read_sql,
    _schema,
    _warehouse_symbol,
    resolve_instrument_identity,
)


def _to_float(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return np.nan
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _fmt(value: Any, decimals: int = 2) -> str:
    number = _to_float(value)
    if not np.isnan(number):
        if abs(number) >= 1000:
            return f"{number:,.{decimals}f}"
        return f"{number:.{decimals}f}"
    if value is None:
        return "N/A"
    text = str(value)
    return text if text else "N/A"


def _fmt_int(value: Any) -> str:
    number = _to_float(value)
    if np.isnan(number):
        return "N/A"
    return f"{int(round(number)):,}"


def _fmt_pct(value: Any) -> str:
    number = _to_float(value)
    if np.isnan(number):
        return "N/A"
    return f"{number:.2f}%"


def _table(headers: list[str], rows: list[list[Any]], align_right: set[int] | None = None) -> str:
    align_right = align_right or set()
    separator = ["---:" if i in align_right else "---" for i in range(len(headers))]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(lines)


def _query(query: str, params: tuple = ()) -> pd.DataFrame:
    return _read_sql(
        sql.SQL(query).format(
            schema=sql.Identifier(_schema()),
            prices=sql.Identifier(PRICES_TABLE),
            overview=sql.Identifier(OVERVIEW_TABLE),
        ),
        params,
    )


def _latest_date_for_ticker(ticker: str) -> str:
    df = _query(
        """
        SELECT MAX(date)::date AS trade_date
        FROM {schema}.{prices}
        WHERE UPPER(ticker) = UPPER(%s)
        """,
        (_warehouse_symbol(ticker),),
    )
    if df.empty or pd.isna(df.iloc[0]["trade_date"]):
        raise ValueError(f"No warehouse price data found for {ticker}.")
    return pd.to_datetime(df.iloc[0]["trade_date"]).strftime("%Y-%m-%d")


def _market_breadth(trade_date: str) -> pd.DataFrame:
    return _query(
        """
        SELECT
            COUNT(*) AS stocks,
            COUNT(*) FILTER (
                WHERE CASE WHEN chg_1d ~ '^-?[0-9]+(\\.[0-9]+)?$'
                THEN chg_1d::numeric END > 0
            ) AS advancers,
            COUNT(*) FILTER (
                WHERE CASE WHEN chg_1d ~ '^-?[0-9]+(\\.[0-9]+)?$'
                THEN chg_1d::numeric END < 0
            ) AS decliners,
            COUNT(*) FILTER (
                WHERE CASE WHEN chg_1d ~ '^-?[0-9]+(\\.[0-9]+)?$'
                THEN chg_1d::numeric END = 0
            ) AS unchanged,
            ROUND(AVG(
                CASE WHEN chg_1d ~ '^-?[0-9]+(\\.[0-9]+)?$'
                THEN chg_1d::numeric END
            ), 2) AS avg_chg_1d,
            ROUND((SUM(volume) / 1000000.0)::numeric, 2) AS total_volume_m
        FROM {schema}.{prices}
        WHERE date::date = %s
          AND ticker <> ALL(%s)
        """,
        (trade_date, list(INDEX_TICKERS)),
    )


def _index_context(trade_date: str) -> pd.DataFrame:
    return _query(
        """
        SELECT ticker, close, chg_1d, chg_1w, chg_1m, chg_3m, chg_6m, chg_1y, pe, pb
        FROM {schema}.{prices}
        WHERE date::date = %s
          AND ticker IN ('VNINDEX', 'VN30')
        ORDER BY ticker
        """,
        (trade_date,),
    )


def _peer_context(ticker: str, trade_date: str, subindustry: str | None) -> pd.DataFrame:
    if not subindustry:
        return pd.DataFrame()
    return _query(
        """
        SELECT p.ticker, o.name, p.close, p.volume, p.market_cap, p.pe, p.pb,
               p.chg_1d, p.chg_1w, p.chg_1m, p.chg_3m, p.chg_6m, p.chg_1y
        FROM {schema}.{prices} p
        JOIN {schema}.{overview} o ON o.ticker = p.ticker
        WHERE p.date::date = %s
          AND o.subindustry = %s
          AND p.ticker <> ALL(%s)
        ORDER BY (p.ticker = %s) DESC, p.market_cap DESC NULLS LAST
        LIMIT 6
        """,
        (trade_date, subindustry, list(INDEX_TICKERS), _warehouse_symbol(ticker)),
    )


def _stance(latest: pd.Series, rolling: dict[str, float]) -> tuple[str, list[str]]:
    close = _to_float(latest.get("Close"))
    ema10 = _to_float(latest.get("close_10_ema"))
    sma50 = _to_float(latest.get("close_50_sma"))
    sma200 = _to_float(latest.get("close_200_sma"))
    rsi = _to_float(latest.get("rsi"))
    vol_ratio = rolling.get("vol_vs_20d", np.nan)

    score = 0
    reasons: list[str] = []
    if close > ema10:
        score += 1
        reasons.append("price is above EMA10")
    if close > sma50:
        score += 1
        reasons.append("price is above SMA50")
    if close > sma200:
        score += 1
        reasons.append("price is above SMA200")
    if 50 <= rsi <= 70:
        score += 1
        reasons.append("RSI is bullish but not overbought")
    elif rsi > 70:
        score -= 1
        reasons.append("RSI is overbought")
    elif rsi < 40:
        score -= 1
        reasons.append("RSI is weak")
    if not np.isnan(vol_ratio) and vol_ratio < 0.8:
        score -= 1
        reasons.append("volume is below its 20-day average")
    elif not np.isnan(vol_ratio) and vol_ratio > 1.2:
        score += 1
        reasons.append("volume confirms the move")

    if score >= 4:
        label = "Bullish"
    elif score >= 2:
        label = "Mildly bullish"
    elif score <= -2:
        label = "Bearish"
    elif score <= 0:
        label = "Neutral to cautious"
    else:
        label = "Neutral"
    return label, reasons


@dataclass
class WarehouseMarketAnalysisAgent:
    ticker: str
    trade_date: str | None = None
    lookback_rows: int = 420

    def run(self) -> str:
        ticker = _warehouse_symbol(self.ticker)
        trade_date = self.trade_date or _latest_date_for_ticker(ticker)
        hist = _add_indicators(_history(ticker, trade_date, self.lookback_rows))
        if hist.empty:
            raise ValueError(f"No warehouse history found for {ticker}.")

        latest = hist.iloc[-1]
        latest_date = pd.to_datetime(latest["Date"]).strftime("%Y-%m-%d")
        last20 = hist.tail(20)
        last50 = hist.tail(50)
        last252 = hist.tail(min(252, len(hist)))

        rolling = self._rolling_metrics(hist, latest, last20, last50, last252)
        identity = resolve_instrument_identity(ticker)
        overview = self._overview_text(ticker, identity)
        stance, reasons = _stance(latest, rolling)
        breadth = _market_breadth(latest_date)
        indices = _index_context(latest_date)
        peers = _peer_context(ticker, latest_date, identity.get("industry"))

        return self._render_report(
            ticker=ticker,
            trade_date=trade_date,
            latest_date=latest_date,
            latest=latest,
            rolling=rolling,
            overview=overview,
            identity=identity,
            stance=stance,
            reasons=reasons,
            breadth=breadth,
            indices=indices,
            peers=peers,
        )

    def _rolling_metrics(
        self,
        hist: pd.DataFrame,
        latest: pd.Series,
        last20: pd.DataFrame,
        last50: pd.DataFrame,
        last252: pd.DataFrame,
    ) -> dict[str, float]:
        def ret(offset: int) -> float:
            if len(hist) <= offset:
                return np.nan
            return (_to_float(latest["Close"]) / _to_float(hist.iloc[-offset - 1]["Close"]) - 1) * 100

        high252 = _to_float(last252["High"].max())
        low252 = _to_float(last252["Low"].min())
        close = _to_float(latest["Close"])
        position_52w = (close - low252) / (high252 - low252) * 100 if high252 != low252 else np.nan
        vol20 = _to_float(last20["Volume"].mean())

        return {
            "ret_5d": ret(5),
            "ret_20d": ret(20),
            "ret_60d": ret(60),
            "ret_120d": ret(120),
            "ret_252d": ret(252),
            "vol20": vol20,
            "vol50": _to_float(last50["Volume"].mean()),
            "vol_vs_20d": _to_float(latest["Volume"]) / vol20 if vol20 else np.nan,
            "high20": _to_float(last20["High"].max()),
            "low20": _to_float(last20["Low"].min()),
            "high50": _to_float(last50["High"].max()),
            "low50": _to_float(last50["Low"].min()),
            "high252": high252,
            "low252": low252,
            "position_52w_pct": position_52w,
        }

    def _overview_text(self, ticker: str, identity: dict[str, str]) -> str:
        parts = [
            identity.get("company_name") or ticker,
            identity.get("exchange"),
            identity.get("sector"),
            identity.get("industry"),
            identity.get("cap_group"),
        ]
        return " | ".join(part for part in parts if part)

    def _render_report(
        self,
        *,
        ticker: str,
        trade_date: str,
        latest_date: str,
        latest: pd.Series,
        rolling: dict[str, float],
        overview: str,
        identity: dict[str, str],
        stance: str,
        reasons: list[str],
        breadth: pd.DataFrame,
        indices: pd.DataFrame,
        peers: pd.DataFrame,
    ) -> str:
        lines = [
            f"# Warehouse Market Analysis: {ticker}",
            "",
            f"- Requested trade date: `{trade_date}`",
            f"- Latest trading row used: `{latest_date}`",
            f"- Instrument: {overview}",
            f"- Technical stance: **{stance}**",
            "",
            "## Executive Summary",
            "",
            (
                f"{ticker} closed at {_fmt(latest.get('Close'))}, with "
                f"{_fmt_pct(latest.get('chg_1d'))} in the latest session and "
                f"{_fmt_pct(latest.get('chg_1m'))} over one month. "
                f"The setup is {stance.lower()} because "
                f"{'; '.join(reasons) if reasons else 'signals are mixed'}."
            ),
            "",
            "## Latest Market Data",
            "",
            _table(
                ["Metric", "Value"],
                [
                    ["Open", _fmt(latest.get("Open"))],
                    ["High", _fmt(latest.get("High"))],
                    ["Low", _fmt(latest.get("Low"))],
                    ["Close", _fmt(latest.get("Close"))],
                    ["Volume", _fmt_int(latest.get("Volume"))],
                    ["Market cap", _fmt(latest.get("market_cap"))],
                    ["P/E", _fmt(latest.get("pe"))],
                    ["P/B", _fmt(latest.get("pb"))],
                    ["1D change", _fmt_pct(latest.get("chg_1d"))],
                    ["1W change", _fmt_pct(latest.get("chg_1w"))],
                    ["1M change", _fmt_pct(latest.get("chg_1m"))],
                    ["6M change", _fmt_pct(latest.get("chg_6m"))],
                    ["1Y change", _fmt_pct(latest.get("chg_1y"))],
                ],
                {1},
            ),
            "",
            "## Technical Indicators",
            "",
            _table(
                ["Indicator", "Value", "Read"],
                [
                    ["EMA10", _fmt(latest.get("close_10_ema")), "short-term trend"],
                    ["SMA50", _fmt(latest.get("close_50_sma")), "medium-term trend"],
                    ["SMA200", _fmt(latest.get("close_200_sma")), "long-term trend"],
                    ["RSI14", _fmt(latest.get("rsi")), "momentum"],
                    ["Bollinger middle", _fmt(latest.get("boll")), "20-day mean"],
                    ["Bollinger upper", _fmt(latest.get("boll_ub")), "near resistance"],
                    ["Bollinger lower", _fmt(latest.get("boll_lb")), "near support"],
                    ["MACD", _fmt(latest.get("macd")), "trend momentum"],
                    ["MACD signal", _fmt(latest.get("macds")), "signal line"],
                    ["MACD histogram", _fmt(latest.get("macdh")), "momentum spread"],
                    ["ATR14", _fmt(latest.get("atr")), "volatility"],
                    ["VWMA20", _fmt(latest.get("vwma")), "volume-weighted trend"],
                    ["MFI14", _fmt(latest.get("mfi")), "money flow"],
                    ["OBV", _fmt_int(latest.get("obv")), "cumulative volume pressure"],
                    ["CMF20", _fmt(latest.get("cmf")), "accumulation/distribution"],
                    ["Volume SMA20", _fmt_int(latest.get("volume_20_sma")), "short-term liquidity baseline"],
                    ["Volume SMA50", _fmt_int(latest.get("volume_50_sma")), "medium-term liquidity baseline"],
                    ["Relative volume 20D", _fmt(latest.get("volume_ratio_20")) + "x", "current vs 20D average volume"],
                    ["Volume z-score 20D", _fmt(latest.get("volume_zscore_20")), "unusual volume detection"],
                ],
                {1},
            ),
            "",
            "## Trend, Liquidity, And Levels",
            "",
            _table(
                ["Metric", "Value"],
                [
                    ["5D return", _fmt_pct(rolling["ret_5d"])],
                    ["20D return", _fmt_pct(rolling["ret_20d"])],
                    ["60D return", _fmt_pct(rolling["ret_60d"])],
                    ["120D return", _fmt_pct(rolling["ret_120d"])],
                    ["252D return", _fmt_pct(rolling["ret_252d"])],
                    ["20D average volume", _fmt_int(rolling["vol20"])],
                    ["50D average volume", _fmt_int(rolling["vol50"])],
                    ["Volume / 20D average", _fmt(rolling["vol_vs_20d"]) + "x"],
                    ["20D high", _fmt(rolling["high20"])],
                    ["20D low", _fmt(rolling["low20"])],
                    ["50D high", _fmt(rolling["high50"])],
                    ["50D low", _fmt(rolling["low50"])],
                    ["52W high", _fmt(rolling["high252"])],
                    ["52W low", _fmt(rolling["low252"])],
                    ["Position in 52W range", _fmt_pct(rolling["position_52w_pct"])],
                ],
                {1},
            ),
        ]

        if not breadth.empty:
            row = breadth.iloc[0]
            lines += [
                "",
                "## Market Breadth",
                "",
                _table(
                    ["Metric", "Value"],
                    [
                        ["Stocks covered", _fmt_int(row.get("stocks"))],
                        ["Advancers", _fmt_int(row.get("advancers"))],
                        ["Decliners", _fmt_int(row.get("decliners"))],
                        ["Unchanged", _fmt_int(row.get("unchanged"))],
                        ["Average 1D change", _fmt_pct(row.get("avg_chg_1d"))],
                        ["Total volume", _fmt(row.get("total_volume_m")) + "M shares"],
                    ],
                    {1},
                ),
            ]

        if not indices.empty:
            lines += [
                "",
                "## Index Context",
                "",
                _table(
                    ["Ticker", "Close", "1D", "1W", "1M", "6M", "1Y", "P/E", "P/B"],
                    [
                        [
                            row["ticker"],
                            _fmt(row.get("close")),
                            _fmt_pct(row.get("chg_1d")),
                            _fmt_pct(row.get("chg_1w")),
                            _fmt_pct(row.get("chg_1m")),
                            _fmt_pct(row.get("chg_6m")),
                            _fmt_pct(row.get("chg_1y")),
                            _fmt(row.get("pe")),
                            _fmt(row.get("pb")),
                        ]
                        for _, row in indices.iterrows()
                    ],
                    set(range(1, 9)),
                ),
            ]

        if not peers.empty:
            lines += [
                "",
                "## Peer Context",
                "",
                _table(
                    ["Ticker", "Name", "Close", "Volume", "Market cap", "P/E", "P/B", "1M", "1Y"],
                    [
                        [
                            row["ticker"],
                            row.get("name") or "",
                            _fmt(row.get("close")),
                            _fmt_int(row.get("volume")),
                            _fmt(row.get("market_cap")),
                            _fmt(row.get("pe")),
                            _fmt(row.get("pb")),
                            _fmt_pct(row.get("chg_1m")),
                            _fmt_pct(row.get("chg_1y")),
                        ]
                        for _, row in peers.iterrows()
                    ],
                    {2, 3, 4, 5, 6, 7, 8},
                ),
            ]

        lines += [
            "",
            "## Source",
            "",
            f"`{_schema()}.{PRICES_TABLE}` and `{_schema()}.{OVERVIEW_TABLE}`.",
        ]
        return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run standalone warehouse market analysis.")
    parser.add_argument("--ticker", required=True, help="Ticker symbol, e.g. HPG")
    parser.add_argument("--date", help="Trade date in YYYY-MM-DD. Defaults to latest warehouse date for ticker.")
    parser.add_argument("--lookback-rows", type=int, default=420, help="Trading rows used for indicators.")
    parser.add_argument("--output", help="Optional markdown output path.")
    args = parser.parse_args()

    report = WarehouseMarketAnalysisAgent(
        ticker=args.ticker,
        trade_date=args.date,
        lookback_rows=args.lookback_rows,
    ).run()

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
