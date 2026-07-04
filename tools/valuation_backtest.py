from __future__ import annotations

import math
from io import BytesIO
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from minio import Minio


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs"

DB_CONFIG = {
    "host": "localhost",
    "port": 5400,
    "dbname": "postgres",
    "user": "admin",
    "password": "change_me",
}

MINIO_CONFIG = {
    "endpoint": "localhost:9004",
    "access_key": "minioadmin",
    "secret_key": "minioadmin",
    "secure": False,
    "bucket": "warehouse",
}

BANK_TICKERS = {
    "ACB",
    "BID",
    "CTG",
    "EIB",
    "HDB",
    "LPB",
    "MBB",
    "OCB",
    "SHB",
    "SSB",
    "STB",
    "TCB",
    "TPB",
    "VCB",
    "VIB",
    "VPB",
}

REPORT_CRITERIA = {
    ("IS", "profit"),
    ("IS", "revenue"),
    ("IS", "cogs"),
    ("IS", "sales_expenses"),
    ("IS", "admin_expenses"),
    ("BS", "equity"),
    ("BS", "liabilities"),
    ("BS", "cash"),
    ("CF", "cf_operating"),
    ("CF", "fixed_assets_purchases"),
    ("CF", "cash"),
}


def clamp(value: float | None, lower: float, upper: float) -> float | None:
    if value is None or pd.isna(value):
        return None
    return max(lower, min(float(value), upper))


def weighted_average(values: list[tuple[float | None, float]]) -> float | None:
    usable = [(value, weight) for value, weight in values if value is not None and not pd.isna(value) and weight > 0]
    total_weight = sum(weight for _, weight in usable)
    if total_weight == 0:
        return None
    return sum(value * weight for value, weight in usable) / total_weight


def growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or pd.isna(current) or pd.isna(previous) or previous <= 0:
        return None
    return current / previous - 1


def compound_growth(value: float | None, years: float) -> float | None:
    if value is None or pd.isna(value):
        return None
    value = clamp(value, -0.8, 1.5)
    return (1 + value) ** years - 1


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if (
        numerator is None
        or denominator is None
        or pd.isna(numerator)
        or pd.isna(denominator)
        or denominator == 0
    ):
        return None
    return numerator / denominator


def quarter_end(year: int, quarter: int) -> pd.Timestamp:
    month = quarter * 3
    return pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)


def report_available_date(year: int, quarter: int) -> pd.Timestamp:
    # Conservative lag to reduce look-ahead: quarterly reports after 45 days,
    # annual/Q4 reports after 90 days.
    lag_days = 90 if quarter == 4 else 45
    return quarter_end(year, quarter) + pd.Timedelta(days=lag_days)


@dataclass(frozen=True)
class EvalResult:
    ticker: str
    eval_date: pd.Timestamp
    method: str
    current_price: float
    target_price_6m: float | None
    target_price_12m: float | None
    upside_6m: float | None
    upside_12m: float | None
    pe_pb_target_price_12m: float | None
    ev_ebitda_target_price_12m: float | None
    dcf_target_price: float | None
    actual_return_3m: float | None
    actual_return_6m: float | None
    actual_return_12m: float | None
    industry: str | None
    is_bank: bool


def load_prices_from_minio() -> pd.DataFrame:
    client = Minio(
        MINIO_CONFIG["endpoint"],
        access_key=MINIO_CONFIG["access_key"],
        secret_key=MINIO_CONFIG["secret_key"],
        secure=MINIO_CONFIG["secure"],
    )
    frames = []
    objects = list(client.list_objects(MINIO_CONFIG["bucket"], prefix="gold/prices_1d/", recursive=True))
    for obj in objects:
        if not obj.object_name.endswith(".parquet"):
            continue
        response = client.get_object(MINIO_CONFIG["bucket"], obj.object_name)
        try:
            frames.append(pd.read_parquet(BytesIO(response.read())))
        finally:
            response.close()
            response.release_conn()
    if not frames:
        raise RuntimeError("No gold/prices_1d parquet objects found in MinIO warehouse.")
    prices = pd.concat(frames, ignore_index=True)
    prices = prices[prices["ticker"].notna() & ~prices["ticker"].astype(str).str.endswith("INDEX")].copy()
    return prices


def load_warehouse() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with psycopg2.connect(**DB_CONFIG) as conn:
        reports = pd.read_sql_query(
            """
            SELECT ticker, year, quarter, report_type, criteria, value
            FROM warehouse.warehouse_reports
            WHERE ticker IS NOT NULL
              AND year >= 2019
              AND value IS NOT NULL
            """,
            conn,
        )
        overview = pd.read_sql_query(
            """
            SELECT DISTINCT ON (ticker)
                ticker, name, trading_floor, industry, subindustry, issue_share, date_fetched
            FROM warehouse.warehouse_overview
            WHERE ticker IS NOT NULL
            ORDER BY ticker, date_fetched DESC NULLS LAST
            """,
            conn,
        )

    prices = load_prices_from_minio()
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices[(prices["date"] >= "2020-01-01") & prices["close"].notna()].copy()
    for column in ["close", "volume", "market_cap", "pe", "pb"]:
        prices[column] = pd.to_numeric(prices[column], errors="coerce")

    reports = reports[reports.apply(lambda row: (row["report_type"], row["criteria"]) in REPORT_CRITERIA, axis=1)]
    reports["value"] = pd.to_numeric(reports["value"], errors="coerce")
    reports["available_date"] = [
        report_available_date(int(year), int(quarter)) for year, quarter in zip(reports["year"], reports["quarter"])
    ]

    overview["ticker"] = overview["ticker"].astype(str).str.upper()
    return prices, reports, overview


def eval_dates_from_prices(prices: pd.DataFrame) -> list[pd.Timestamp]:
    by_month = prices.groupby(prices["date"].dt.to_period("M"))["date"].max().sort_values()
    quarter_months = {3, 6, 9, 12}
    dates = [ts for period, ts in by_month.items() if period.month in quarter_months and ts >= pd.Timestamp("2020-03-01")]
    max_date = prices["date"].max()
    return [ts for ts in dates if ts + pd.DateOffset(months=12) <= max_date]


def build_price_lookup(prices: pd.DataFrame) -> tuple[dict[pd.Timestamp, pd.DataFrame], dict[str, pd.DataFrame]]:
    price_by_date = {
        eval_date: frame.copy()
        for eval_date, frame in prices.groupby("date", sort=False)
    }
    sorted_prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)
    price_by_ticker = {ticker: frame for ticker, frame in sorted_prices.groupby("ticker", sort=False)}
    return price_by_date, price_by_ticker


def build_report_lookup(reports: pd.DataFrame) -> dict[str, pd.DataFrame]:
    reports = reports.sort_values(["ticker", "available_date", "year", "quarter"])
    return {ticker: frame for ticker, frame in reports.groupby("ticker", sort=False)}


def forward_return(price_by_ticker: dict[str, pd.DataFrame], ticker: str, eval_date: pd.Timestamp, months: int) -> float | None:
    rows = price_by_ticker.get(ticker)
    if rows is None or rows.empty:
        return None
    start = rows[rows["date"] <= eval_date].tail(1)
    if start.empty:
        return None
    end_date = eval_date + pd.DateOffset(months=months)
    end = rows[rows["date"] >= end_date].head(1)
    if end.empty:
        return None
    start_price = float(start.iloc[0]["close"])
    end_price = float(end.iloc[0]["close"])
    if start_price <= 0:
        return None
    return end_price / start_price - 1


def period_key(row: pd.Series) -> tuple[int, int]:
    return int(row["year"]), int(row["quarter"])


def latest_periods(
    reports_by_ticker: dict[str, pd.DataFrame],
    ticker: str,
    eval_date: pd.Timestamp,
    limit: int = 8,
) -> tuple[list[tuple[int, int]], dict]:
    ticker_reports = reports_by_ticker.get(ticker)
    if ticker_reports is None:
        return [], {}

    subset = ticker_reports[ticker_reports["available_date"] <= eval_date]
    if subset.empty:
        return [], {}

    periods = sorted({period_key(row) for _, row in subset.iterrows()})[-limit:]
    period_set = set(periods)
    subset = subset[subset.apply(lambda row: period_key(row) in period_set, axis=1)]
    values = {
        (int(row.year), int(row.quarter), str(row.report_type), str(row.criteria)): float(row.value)
        for row in subset.itertuples(index=False)
        if not pd.isna(row.value)
    }
    return periods, values


def sum_values(values: dict, periods: list[tuple[int, int]], report_type: str, criteria: str) -> float | None:
    result = []
    for year, quarter in periods:
        value = values.get((year, quarter, report_type, criteria))
        if value is None or pd.isna(value):
            return None
        result.append(value)
    return sum(result)


def trailing_sum(values: dict, periods: list[tuple[int, int]], report_type: str, criteria: str, limit: int = 4) -> float | None:
    if len(periods) < limit:
        return None
    return sum_values(values, periods[-limit:], report_type, criteria)


def latest_value(values: dict, periods: list[tuple[int, int]], report_type: str, criteria: str) -> float | None:
    for year, quarter in reversed(periods):
        value = values.get((year, quarter, report_type, criteria))
        if value is not None and not pd.isna(value):
            return value
    return None


def period_growth(values: dict, periods: list[tuple[int, int]], report_type: str, criteria: str, trailing_periods: int) -> float | None:
    if len(periods) < trailing_periods:
        return None
    recent_periods = periods[-trailing_periods:]
    previous_year_periods = [(year - 1, quarter) for year, quarter in recent_periods]
    recent = sum_values(values, recent_periods, report_type, criteria)
    previous = sum_values(values, previous_year_periods, report_type, criteria)
    result = growth(recent, previous)
    if result is not None:
        return result
    if len(periods) < trailing_periods * 2:
        return None
    previous_periods = periods[-trailing_periods * 2 : -trailing_periods]
    previous = sum_values(values, previous_periods, report_type, criteria)
    return growth(recent, previous)


def trailing_ebitda_proxy(values: dict, periods: list[tuple[int, int]]) -> float | None:
    revenue = trailing_sum(values, periods, "IS", "revenue")
    cogs = trailing_sum(values, periods, "IS", "cogs")
    sales_expenses = trailing_sum(values, periods, "IS", "sales_expenses") or 0
    admin_expenses = trailing_sum(values, periods, "IS", "admin_expenses") or 0
    if revenue is not None and cogs is not None:
        operating_profit = revenue + cogs + sales_expenses + admin_expenses
        if operating_profit > 0:
            return operating_profit
    profit = trailing_sum(values, periods, "IS", "profit")
    return profit if profit is not None and profit > 0 else None


def dcf_target_price(
    values: dict,
    periods: list[tuple[int, int]],
    issue_share: float | None,
    growth_12m: float | None,
    equity: float | None,
    liabilities: float | None,
) -> float | None:
    if issue_share is None or issue_share <= 0 or len(periods) < 4:
        return None

    trailing_profit = trailing_sum(values, periods, "IS", "profit")
    trailing_revenue = trailing_sum(values, periods, "IS", "revenue")
    trailing_cfo = trailing_sum(values, periods, "CF", "cf_operating")
    trailing_capex = trailing_sum(values, periods, "CF", "fixed_assets_purchases")

    raw_fcf = trailing_cfo + trailing_capex if trailing_cfo is not None and trailing_capex is not None else None
    if raw_fcf is not None and raw_fcf > 0:
        normalized_fcf = raw_fcf
    elif trailing_profit is not None and trailing_profit > 0:
        normalized_fcf = trailing_profit * 0.65
    elif trailing_revenue is not None and trailing_revenue > 0:
        normalized_fcf = trailing_revenue * 0.06
    else:
        normalized_fcf = None

    if normalized_fcf is None or normalized_fcf <= 0:
        return None

    leverage = 0.0
    if equity is not None and liabilities is not None and equity > 0:
        leverage = clamp(liabilities / equity, 0, 2) or 0

    discount_rate = clamp(0.105 + leverage * 0.018, 0.095, 0.16) or 0.105
    projection_growth = clamp(growth_12m if growth_12m is not None else 0.06, -0.03, 0.18) or 0.06
    terminal_growth = clamp(projection_growth * 0.25, 0.01, 0.04) or 0.02

    present_value = 0.0
    for year in range(1, 6):
        fade = (5 - year) / 4
        year_growth = terminal_growth + (projection_growth - terminal_growth) * fade
        cash_flow = normalized_fcf * ((1 + year_growth) ** year)
        present_value += cash_flow / ((1 + discount_rate) ** year)

    terminal_cash_flow = normalized_fcf * ((1 + terminal_growth) ** 5) * (1 + terminal_growth)
    terminal_value = terminal_cash_flow / max(discount_rate - terminal_growth, 0.01)
    present_value += terminal_value / ((1 + discount_rate) ** 5)
    return present_value * 1_000_000 / issue_share


def bank_target(
    eps: float | None,
    bvps: float | None,
    pe: float | None,
    pb: float | None,
    industry_pe: float | None,
    industry_pb: float | None,
    roe: float | None,
    industry_roe: float | None,
    earnings_growth: float | None,
    book_growth: float | None,
) -> float | None:
    pe_benchmark = industry_pe if industry_pe is not None and industry_pe > 0 else pe
    pb_benchmark = industry_pb if industry_pb is not None and industry_pb > 0 else pb
    if pe_benchmark is not None:
        pe_benchmark = clamp(pe_benchmark, 4, 18)
    if pb_benchmark is not None:
        roe_adjustment = 1.0
        if roe is not None and industry_roe is not None and industry_roe > 0:
            roe_adjustment = clamp(roe / industry_roe, 0.75, 1.2) or 1.0
        pb_benchmark = clamp(pb_benchmark * roe_adjustment, 0.4, 3.0)

    pe_target = eps * (1 + (earnings_growth or 0)) * pe_benchmark / 1000 if eps and eps > 0 and pe_benchmark else None
    pb_target = bvps * (1 + (book_growth or 0)) * pb_benchmark / 1000 if bvps and bvps > 0 and pb_benchmark else None
    return weighted_average([(pb_target, 0.65), (pe_target, 0.35)])


def compute_industry_benchmarks(
    day_prices: pd.DataFrame,
    overview: pd.DataFrame,
    reports_by_ticker: dict[str, pd.DataFrame],
    eval_date: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, float]]:
    if "industry" in day_prices.columns:
        merged = day_prices.copy()
    else:
        merged = day_prices.merge(overview[["ticker", "industry"]], on="ticker", how="left")
    pe_pb = (
        merged.assign(
            pe_valid=lambda frame: frame["pe"].where((frame["pe"] > 0) & (frame["pe"] < 80)),
            pb_valid=lambda frame: frame["pb"].where((frame["pb"] > 0) & (frame["pb"] < 20)),
        )
        .groupby("industry", dropna=True)
        .agg(industry_pe=("pe_valid", "mean"), industry_pb=("pb_valid", "mean"), peer_count=("ticker", "count"))
        .reset_index()
    )

    ev_rows = []
    for row in merged.itertuples(index=False):
        if pd.isna(row.industry) or pd.isna(row.market_cap) or row.market_cap <= 0 or row.close <= 0:
            continue
        periods, values = latest_periods(reports_by_ticker, row.ticker, eval_date)
        if len(periods) < 4:
            continue
        liabilities = latest_value(values, periods, "BS", "liabilities")
        cash = latest_value(values, periods, "BS", "cash")
        if cash is None:
            cash = latest_value(values, periods, "CF", "cash")
        ebitda = trailing_ebitda_proxy(values, periods)
        if liabilities is None or ebitda is None or ebitda <= 0:
            continue
        enterprise_value = row.market_cap + liabilities - (cash or 0)
        ev_ebitda = safe_div(enterprise_value, ebitda)
        if ev_ebitda is not None and 0 < ev_ebitda < 50:
            ev_rows.append({"industry": row.industry, "ev_ebitda": ev_ebitda})

    if not ev_rows:
        return pe_pb, {}
    ev = pd.DataFrame(ev_rows).groupby("industry")["ev_ebitda"].mean().to_dict()
    return pe_pb, ev


def value_one_date(
    eval_date: pd.Timestamp,
    day_prices: pd.DataFrame,
    price_by_ticker: dict[str, pd.DataFrame],
    reports_by_ticker: dict[str, pd.DataFrame],
    overview: pd.DataFrame,
) -> list[EvalResult]:
    day_prices = day_prices.merge(
        overview[["ticker", "industry", "subindustry"]],
        on="ticker",
        how="left",
    )

    # Keep the investable sample reasonably liquid and avoid tiny, stale names.
    day_prices["turnover_proxy"] = day_prices["close"] * day_prices["volume"]
    day_prices = day_prices[
        (day_prices["close"] > 0)
        & (day_prices["market_cap"] > 500)
        & (day_prices["turnover_proxy"].fillna(0) > 100_000)
    ].copy()
    if day_prices.empty:
        return []

    industry_pe_pb, industry_ev = compute_industry_benchmarks(day_prices, overview, reports_by_ticker, eval_date)
    day_prices = day_prices.merge(industry_pe_pb, on="industry", how="left")

    results = []
    for row in day_prices.itertuples(index=False):
        periods, values = latest_periods(reports_by_ticker, row.ticker, eval_date)
        if len(periods) < 4:
            continue

        pe = clamp(row.pe, 3, 35) if not pd.isna(row.pe) and row.pe > 0 else None
        pb = clamp(row.pb, 0.2, 6) if not pd.isna(row.pb) and row.pb > 0 else None
        eps = row.close * 1000 / pe if pe else None
        bvps = row.close * 1000 / pb if pb else None
        issue_share = row.market_cap * 1_000_000 / row.close if row.market_cap and row.close > 0 else None

        profit_growth_6m = period_growth(values, periods, "IS", "profit", 2)
        profit_growth_12m = period_growth(values, periods, "IS", "profit", 4)
        revenue_growth_6m = period_growth(values, periods, "IS", "revenue", 2)
        revenue_growth_12m = period_growth(values, periods, "IS", "revenue", 4)
        equity_growth_12m = period_growth(values, periods, "BS", "equity", 4) or 0.0
        growth_6m = profit_growth_6m if profit_growth_6m is not None else revenue_growth_6m
        growth_12m = profit_growth_12m if profit_growth_12m is not None else revenue_growth_12m
        earnings_growth_6m = compound_growth(growth_6m, 0.5)
        earnings_growth_12m = compound_growth(growth_12m, 1.0)
        book_growth_6m = compound_growth(equity_growth_12m, 0.5)
        book_growth_12m = compound_growth(equity_growth_12m, 1.0)

        latest_equity = latest_value(values, periods, "BS", "equity")
        latest_liabilities = latest_value(values, periods, "BS", "liabilities")
        latest_cash = latest_value(values, periods, "BS", "cash")
        if latest_cash is None:
            latest_cash = latest_value(values, periods, "CF", "cash")

        eps_target_6m = eps * (1 + (earnings_growth_6m or 0)) * pe / 1000 if eps and pe else None
        eps_target_12m = eps * (1 + (earnings_growth_12m or 0)) * pe / 1000 if eps and pe else None
        bvps_target_6m = bvps * (1 + (book_growth_6m or 0)) * pb / 1000 if bvps and pb else None
        bvps_target_12m = bvps * (1 + (book_growth_12m or 0)) * pb / 1000 if bvps and pb else None
        pe_pb_6m = weighted_average([(eps_target_6m, 0.7), (bvps_target_6m, 0.3)])
        pe_pb_12m = weighted_average([(eps_target_12m, 0.7), (bvps_target_12m, 0.3)])

        trailing_ebitda = trailing_ebitda_proxy(values, periods)
        enterprise_value = None
        net_debt = None
        ev_ebitda = None
        if row.market_cap and latest_liabilities is not None:
            net_debt = latest_liabilities - (latest_cash or 0)
            enterprise_value = row.market_cap + net_debt
        if enterprise_value is not None and enterprise_value > 0 and trailing_ebitda and trailing_ebitda > 0:
            ev_ebitda = enterprise_value / trailing_ebitda
        ev_benchmark = industry_ev.get(row.industry) if row.industry in industry_ev else ev_ebitda

        ev_6m = None
        ev_12m = None
        if trailing_ebitda and ev_benchmark and issue_share:
            for_growth_6m = trailing_ebitda * (1 + (earnings_growth_6m or 0))
            for_growth_12m = trailing_ebitda * (1 + (earnings_growth_12m or 0))
            equity_value_6m = for_growth_6m * ev_benchmark - (net_debt or 0)
            equity_value_12m = for_growth_12m * ev_benchmark - (net_debt or 0)
            ev_6m = equity_value_6m * 1_000_000 / issue_share if equity_value_6m > 0 else None
            ev_12m = equity_value_12m * 1_000_000 / issue_share if equity_value_12m > 0 else None

        multiple_6m = weighted_average([(pe_pb_6m, 0.75), (ev_6m, 0.25)])
        multiple_12m = weighted_average([(pe_pb_12m, 0.75), (ev_12m, 0.25)])
        dcf_12m = dcf_target_price(values, periods, issue_share, growth_12m, latest_equity, latest_liabilities)
        dcf_6m = row.close + (dcf_12m - row.close) * 0.5 if dcf_12m is not None else None
        target_6m = weighted_average([(multiple_6m, 0.6 if dcf_12m is not None else 1.0), (dcf_6m, 0.4)])
        target_12m = weighted_average([(multiple_12m, 0.6 if dcf_12m is not None else 1.0), (dcf_12m, 0.4)])
        method = "blended"

        is_bank = row.ticker in BANK_TICKERS or (isinstance(row.industry, str) and "Ngân hàng" in row.industry)
        if is_bank:
            industry_roe = None
            roe = safe_div(profit_growth_12m, 1.0)
            pe_pb_6m = bank_target(
                eps,
                bvps,
                pe,
                pb,
                row.industry_pe if not pd.isna(row.industry_pe) else None,
                row.industry_pb if not pd.isna(row.industry_pb) else None,
                roe,
                industry_roe,
                earnings_growth_6m,
                book_growth_6m,
            )
            pe_pb_12m = bank_target(
                eps,
                bvps,
                pe,
                pb,
                row.industry_pe if not pd.isna(row.industry_pe) else None,
                row.industry_pb if not pd.isna(row.industry_pb) else None,
                roe,
                industry_roe,
                earnings_growth_12m,
                book_growth_12m,
            )
            ev_12m = None
            dcf_12m = None
            target_6m = pe_pb_6m
            target_12m = pe_pb_12m
            method = "bank_pe_pb_roe"

        if target_12m is None or not math.isfinite(target_12m):
            continue

        upside_6m = target_6m / row.close - 1 if target_6m is not None and row.close > 0 else None
        upside_12m = target_12m / row.close - 1 if row.close > 0 else None
        results.append(
            EvalResult(
                ticker=row.ticker,
                eval_date=eval_date,
                method=method,
                current_price=float(row.close),
                target_price_6m=target_6m,
                target_price_12m=target_12m,
                upside_6m=upside_6m,
                upside_12m=upside_12m,
                pe_pb_target_price_12m=pe_pb_12m,
                ev_ebitda_target_price_12m=ev_12m,
                dcf_target_price=dcf_12m,
                actual_return_3m=forward_return(price_by_ticker, row.ticker, eval_date, 3),
                actual_return_6m=forward_return(price_by_ticker, row.ticker, eval_date, 6),
                actual_return_12m=forward_return(price_by_ticker, row.ticker, eval_date, 12),
                industry=row.industry if isinstance(row.industry, str) else None,
                is_bank=is_bank,
            )
        )
    return results


def summarize_method(signal_df: pd.DataFrame, score_column: str, return_column: str) -> dict[str, float | int | str | None]:
    df = signal_df[[score_column, return_column, "eval_date"]].dropna()
    if df.empty:
        return {"score": score_column, "horizon": return_column, "n": 0}

    bucket_rows = []
    for _, group in df.groupby("eval_date"):
        if len(group) < 20:
            continue
        ranked = group.sort_values(score_column)
        bottom = ranked.head(max(1, len(ranked) // 5))
        top = ranked.tail(max(1, len(ranked) // 5))
        bucket_rows.append(
            {
                "top_return": top[return_column].mean(),
                "bottom_return": bottom[return_column].mean(),
                "long_short": top[return_column].mean() - bottom[return_column].mean(),
                "hit_rate": float((top[return_column] > 0).mean()),
                "rank_ic": group[score_column].rank().corr(group[return_column].rank()),
            }
        )
    buckets = pd.DataFrame(bucket_rows)
    if buckets.empty:
        return {"score": score_column, "horizon": return_column, "n": int(len(df))}

    return {
        "score": score_column,
        "horizon": return_column,
        "n": int(len(df)),
        "periods": int(len(buckets)),
        "top_return": buckets["top_return"].mean(),
        "bottom_return": buckets["bottom_return"].mean(),
        "long_short": buckets["long_short"].mean(),
        "hit_rate": buckets["hit_rate"].mean(),
        "rank_ic": buckets["rank_ic"].mean(),
    }


def make_method_scores(signal_df: pd.DataFrame) -> pd.DataFrame:
    df = signal_df.copy()
    for column in ["pe_pb_target_price_12m", "ev_ebitda_target_price_12m", "dcf_target_price", "target_price_12m"]:
        score_name = column.replace("target_price_12m", "upside").replace("dcf_target_price", "dcf_upside")
        df[score_name] = df[column] / df["current_price"] - 1
    return df


def write_report(signal_df: pd.DataFrame, summary_df: pd.DataFrame, eval_dates: list[pd.Timestamp]) -> Path:
    report_path = OUTPUT_DIR / "valuation_backtest_report.md"
    best = summary_df.sort_values("long_short", ascending=False).head(8)
    coverage = signal_df.groupby("eval_date")["ticker"].nunique()
    signal_periods = signal_df["eval_date"].nunique()

    lines = [
        "# Backtest định giá từ warehouse",
        "",
        f"- Mốc tín hiệu hợp lệ: {signal_df['eval_date'].min().date()} đến {signal_df['eval_date'].max().date()}",
        f"- Số mốc quý quét được từ giá: {len(eval_dates)}",
        f"- Số mốc quý có đủ dữ liệu định giá: {signal_periods}",
        f"- Số tín hiệu hợp lệ: {len(signal_df):,}",
        f"- Coverage trung bình mỗi kỳ: {coverage.mean():.0f} mã",
        "- Tránh look-ahead: BCTC quý giả định có sau 45 ngày, BCTC Q4/năm sau 90 ngày.",
        "- Universe lọc nhanh: market cap > 500 tỷ và turnover proxy > 100,000.",
        "",
        "## Hiệu suất theo phương pháp",
        "",
        best.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Cách đọc",
        "",
        "- `top_return`: lợi suất trung bình của nhóm 20% upside cao nhất.",
        "- `bottom_return`: lợi suất trung bình của nhóm 20% upside thấp nhất.",
        "- `long_short`: chênh lệch top minus bottom, càng cao càng tốt.",
        "- `rank_ic`: tương quan Spearman giữa upside dự báo và lợi suất tương lai.",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main() -> None:
    prices, reports, overview = load_warehouse()
    price_by_date, price_by_ticker = build_price_lookup(prices)
    reports_by_ticker = build_report_lookup(reports)
    eval_dates = eval_dates_from_prices(prices)

    all_results = []
    for eval_date in eval_dates:
        day_prices = price_by_date.get(eval_date)
        if day_prices is None:
            continue
        all_results.extend(value_one_date(eval_date, day_prices, price_by_ticker, reports_by_ticker, overview))

    if not all_results:
        raise RuntimeError("No valuation signals were produced.")

    signal_df = pd.DataFrame([result.__dict__ for result in all_results])
    signal_df = make_method_scores(signal_df)

    summary_rows = []
    scores = ["upside_12m", "pe_pb_upside", "ev_ebitda_upside", "dcf_upside"]
    horizons = ["actual_return_3m", "actual_return_6m", "actual_return_12m"]
    for score in scores:
        for horizon in horizons:
            summary_rows.append(summarize_method(signal_df, score, horizon))
    summary_df = pd.DataFrame(summary_rows)

    signal_path = OUTPUT_DIR / "valuation_backtest_signals.csv"
    summary_path = OUTPUT_DIR / "valuation_backtest_summary.csv"
    signal_df.to_csv(signal_path, index=False, encoding="utf-8-sig")
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    report_path = write_report(signal_df, summary_df, eval_dates)

    print(f"Wrote {signal_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {report_path}")
    print(summary_df.sort_values("long_short", ascending=False).head(12).to_string(index=False))


if __name__ == "__main__":
    main()
