import pandas as pd
from dagster import AllPartitionMapping, asset, AssetIn, Output
from datetime import date, datetime
import re
from etl_pipeline.assets.bronze.reports import report_partitions

def extract_issued_shares(title: str) -> float | None:
    if pd.isna(title):
        return None
    # tìm cụm số có dấu . hoặc ,
    match = re.search(r"([\d\.,]+)", title)
    if not match:
        return None
    # bỏ dấu phân cách hàng nghìn
    number_str = match.group(1).replace(".", "").replace(",", "")
    try:
        return float(number_str)
    except ValueError:
        return None
    
import numpy as np

def safe_divide(numer, denom):
    return np.where(
        (denom > 0) & pd.notna(denom),
        numer / denom,
        np.nan,
    )


def safe_divide_nonzero(numer, denom):
    return np.where(
        (denom != 0) & pd.notna(denom),
        numer / denom,
        np.nan,
    )


FINANCIAL_CRITERIA_ALIASES = {
    "net_profit_loss_after_tax": "profit",
    "profit_after_tax": "profit",
    "attributable_to_parent_company": "parent_profit",
    "net_profit_loss_after_tax_for_shareholders_of_parent_company": "parent_profit",
    "profit_after_tax_for_shareholders_of_parent_company": "parent_profit",
    "parent_profit": "parent_profit",
    "owners_equity": "equity",
    "owner_s_equity": "equity",
    "total_owner_s_equity": "equity",
    "total_equity": "equity",
    "total_assets": "total_assets",
    "total_liabilities": "liabilities",
    "total_operating_income": "revenue",
    "revenue": "revenue",
    "interest_and_similar_income": "interest_income",
    "interest_and_similar_expenses": "interest_expenses",
    "balances_with_the_sbv": "deposit_at_SBV",
    "balances_with_state_bank_of_vietnam": "deposit_at_SBV",
    "placements_with_and_loans_to_other_credit_institutions": "deposit_at_FI",
    "deposits_with_and_loans_to_other_credit_institutions": "deposit_at_FI",
    "investment_securities": "investment_securities",
    "securities_investments": "investment_securities",
    "loans_and_advances_to_customers_net": "customer_loan",
    "loans_to_customers": "customer_loan",
}

RATIO_SUMMARY_METRIC_COLUMNS = [
    "year_report",
    "number_of_shares_mkt_cap",
    "market_cap",
    "pe",
    "pb",
    "dividend_yield",
    "roe",
    "roa",
    "gross_margin",
    "ebit_margin",
    "pre_tax_profit_margin",
    "after_tax_profit_margin",
    "net_interest_margin",
    "average_yield_on_earning_assets",
    "average_cost_of_financing",
    "cost_to_income",
    "roic",
    "date_fetched",
]
SHARE_DILUTION_EVENT_TYPE_IDS = {2, 3, 4}
SHARE_SNAPSHOT_LAG_DAYS = 7

TICKER_METRIC_COLUMNS = [
    "ticker",
    "year",
    "quarter",
    "eps",
    "bvps",
    "price",
    "industry",
    "pe_industry",
    "pb_industry",
    "bvps_industry",
    "roe_industry",
    "roa_industry",
    "ros_industry",
    "nim_industry",
    *RATIO_SUMMARY_METRIC_COLUMNS,
]


def _with_metric_criteria(reports: pd.DataFrame) -> pd.DataFrame:
    df = reports.copy()
    df["metric_criteria"] = (
        df["criteria"].astype(str).replace(FINANCIAL_CRITERIA_ALIASES)
    )
    return df


def select_ratio_summary_metrics(
    ratio_summary: pd.DataFrame,
    year: int,
    quarter: int,
) -> pd.DataFrame:
    if ratio_summary is None or ratio_summary.empty:
        return pd.DataFrame(columns=["ticker", "year", "quarter"])

    df = ratio_summary.copy()
    if "ticker" not in df.columns and "symbol" in df.columns:
        df["ticker"] = df["symbol"]
    if "ticker" not in df.columns:
        return pd.DataFrame(columns=["ticker", "year", "quarter"])

    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["year"] = pd.to_numeric(df.get("year"), errors="coerce")
    df["quarter"] = pd.to_numeric(df.get("quarter"), errors="coerce")
    df = df[(df["year"] == year) & (df["quarter"] == quarter)].copy()
    if df.empty:
        return pd.DataFrame(columns=["ticker", "year", "quarter"])

    if "ratio_type" in df.columns:
        ttm_df = df[df["ratio_type"].astype(str).str.upper().eq("RATIO_TTM")]
        if not ttm_df.empty:
            df = ttm_df.copy()

    if "date_fetched" in df.columns:
        df["date_fetched"] = pd.to_datetime(df["date_fetched"], errors="coerce")
        df = df.sort_values(["ticker", "date_fetched"])
    else:
        df = df.sort_values(["ticker"])

    df = df.drop_duplicates(subset=["ticker", "year", "quarter"], keep="last")
    selected_columns = [
        column
        for column in ["ticker", "year", "quarter", *RATIO_SUMMARY_METRIC_COLUMNS]
        if column in df.columns
    ]
    return df[selected_columns].copy()


def _parse_ratio_number(value: str) -> float | None:
    value = str(value).strip().replace(" ", "")
    if not value:
        return None
    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".")
    elif "," in value:
        value = value.replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None


def share_factor_from_ratio_display(value: object) -> float | None:
    if pd.isna(value):
        return None

    text = str(value).strip().lower()
    ratio_match = re.search(
        r"(\d+(?:[\.,]\d+)?)\s*[:/]\s*(\d+(?:[\.,]\d+)?)",
        text,
    )
    if ratio_match:
        original = _parse_ratio_number(ratio_match.group(1))
        split = _parse_ratio_number(ratio_match.group(2))
        if original and split and original > 0 and split > 0:
            return 1 + split / original

    percent_match = re.search(r"(\d+(?:[\.,]\d+)?)\s*%", text)
    if percent_match:
        percent = _parse_ratio_number(percent_match.group(1))
        if percent and percent > 0:
            return 1 + percent / 100

    return None


def build_share_dilution_events(events: pd.DataFrame) -> pd.DataFrame:
    required_columns = {"ticker", "event_type_id", "exright_date"}
    if events is None or events.empty or not required_columns.issubset(events.columns):
        return pd.DataFrame(columns=["ticker", "exright_date", "share_factor"])

    df = events.copy()
    if "event_id" in df.columns:
        df = df.drop_duplicates(subset=["event_id"], keep="last")

    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["event_type_id"] = pd.to_numeric(df["event_type_id"], errors="coerce").astype("Int64")
    df["exright_date"] = pd.to_datetime(df["exright_date"], errors="coerce")
    if "ratio_display" not in df.columns:
        df["ratio_display"] = None
    df["share_factor"] = df["ratio_display"].apply(share_factor_from_ratio_display)
    if {"rate_original", "rate_split"}.issubset(df.columns):
        df["rate_original"] = pd.to_numeric(df["rate_original"], errors="coerce")
        df["rate_split"] = pd.to_numeric(df["rate_split"], errors="coerce")
        fallback_factor = 1 + df["rate_split"] / df["rate_original"]
        valid_fallback = (
            df["rate_original"].notna()
            & df["rate_split"].notna()
            & (df["rate_original"] > 0)
            & (df["rate_split"] > 0)
        )
        df["share_factor"] = df["share_factor"].where(
            df["share_factor"].notna(),
            fallback_factor.where(valid_fallback),
        )

    df = df[
        df["event_type_id"].isin(SHARE_DILUTION_EVENT_TYPE_IDS)
        & df["exright_date"].notna()
        & (df["share_factor"] > 1)
    ].copy()
    if df.empty:
        return pd.DataFrame(columns=["ticker", "exright_date", "share_factor"])

    df["ratio_display_key"] = df["ratio_display"].astype(str).str.strip().str.lower()
    df = df.sort_values(["ticker", "exright_date"])
    df = df.drop_duplicates(
        subset=[
            "ticker",
            "exright_date",
            "event_type_id",
            "ratio_display_key",
            "share_factor",
        ],
        keep="last",
    )

    return df[["ticker", "exright_date", "share_factor"]].sort_values(
        ["ticker", "exright_date"]
    )


def quarter_end_timestamp(year: pd.Series, quarter: pd.Series) -> pd.Series:
    result = pd.Series(pd.NaT, index=year.index, dtype="datetime64[ns]")
    valid = year.notna() & quarter.notna()
    if valid.any():
        result.loc[valid] = pd.PeriodIndex.from_fields(
            year=year.loc[valid].astype(int),
            quarter=quarter.loc[valid].astype(int),
            freq="Q",
        ).to_timestamp(how="end").normalize()
    return result


def shift_quarter(year: int, quarter: int, n: int = 2) -> tuple[int, int]:
    shifted_quarter = quarter - n
    shifted_year = year
    while shifted_quarter <= 0:
        shifted_quarter += 4
        shifted_year -= 1
    return shifted_year, shifted_quarter


def adjusted_shares_from_base_period(
    ratio_summary: pd.DataFrame,
    events: pd.DataFrame,
    year: int,
    quarter: int,
    today: date | None = None,
) -> pd.DataFrame:
    base_year, base_quarter = shift_quarter(year, quarter, n=2)
    base_metrics = select_ratio_summary_metrics(ratio_summary, base_year, base_quarter)
    if base_metrics.empty and ratio_summary is not None and not ratio_summary.empty:
        fallback = ratio_summary.copy()
        if "ticker" not in fallback.columns and "symbol" in fallback.columns:
            fallback["ticker"] = fallback["symbol"]
        required = {"ticker", "year", "quarter", "number_of_shares_mkt_cap"}
        if required.issubset(fallback.columns):
            fallback["ticker"] = fallback["ticker"].astype(str).str.strip().str.upper()
            fallback["year"] = pd.to_numeric(fallback["year"], errors="coerce")
            fallback["quarter"] = pd.to_numeric(fallback["quarter"], errors="coerce")
            fallback["period_order"] = fallback["year"] * 4 + fallback["quarter"]
            base_order = base_year * 4 + base_quarter
            fallback = fallback[
                fallback["period_order"].notna()
                & (fallback["period_order"] <= base_order)
            ].copy()
            if "ratio_type" in fallback.columns:
                ttm_df = fallback[fallback["ratio_type"].astype(str).str.upper().eq("RATIO_TTM")]
                if not ttm_df.empty:
                    fallback = ttm_df.copy()
            if "date_fetched" in fallback.columns:
                fallback["date_fetched"] = pd.to_datetime(
                    fallback["date_fetched"], errors="coerce"
                )
                fallback = fallback.sort_values(["ticker", "period_order", "date_fetched"])
            else:
                fallback = fallback.sort_values(["ticker", "period_order"])
            base_metrics = fallback.drop_duplicates("ticker", keep="last")

    base_columns = [
        column
        for column in ["ticker", "number_of_shares_mkt_cap", "date_fetched"]
        if column in base_metrics.columns
    ]
    if not base_columns:
        return pd.DataFrame(
            columns=["ticker", "year", "quarter", "number_of_shares_mkt_cap", "date_fetched"]
        )

    shares = base_metrics[base_columns].copy()
    for column in ["ticker", "number_of_shares_mkt_cap", "date_fetched"]:
        if column not in shares.columns:
            shares[column] = np.nan

    shares["ticker"] = shares["ticker"].astype(str).str.strip().str.upper()
    shares["year"] = year
    shares["quarter"] = quarter
    shares["base_year"] = base_year
    shares["base_quarter"] = base_quarter
    shares["number_of_shares_mkt_cap"] = pd.to_numeric(
        shares["number_of_shares_mkt_cap"],
        errors="coerce",
    )

    dilution_events = build_share_dilution_events(events)
    if not dilution_events.empty:
        today_ts = pd.Timestamp(today or date.today()).normalize()
        base_period_end = pd.Period(
            year=base_year,
            quarter=base_quarter,
            freq="Q",
        ).to_timestamp(how="end").normalize()

        for ticker, row_index in shares.groupby("ticker").groups.items():
            ticker_events = dilution_events[
                (dilution_events["ticker"] == ticker)
                & (dilution_events["exright_date"] > base_period_end)
                & (dilution_events["exright_date"] <= today_ts)
            ]
            if ticker_events.empty:
                continue

            factor = ticker_events["share_factor"].prod()
            shares.loc[row_index, "number_of_shares_mkt_cap"] = (
                shares.loc[row_index, "number_of_shares_mkt_cap"] * factor
            )

    return shares[["ticker", "year", "quarter", "number_of_shares_mkt_cap", "date_fetched"]]


def adjust_current_shares_to_period(
    metrics: pd.DataFrame,
    events: pd.DataFrame,
) -> pd.Series:
    current_shares = pd.to_numeric(
        metrics.get("number_of_shares_mkt_cap"),
        errors="coerce",
    )
    if metrics.empty:
        return current_shares

    dilution_events = build_share_dilution_events(events)
    if dilution_events.empty:
        return current_shares

    period_end = quarter_end_timestamp(metrics["year"], metrics["quarter"])
    snapshot_date = pd.to_datetime(metrics.get("date_fetched"), errors="coerce")
    adjusted_shares = current_shares.copy()

    for ticker, row_index in metrics.groupby("ticker").groups.items():
        ticker_events = dilution_events[dilution_events["ticker"] == ticker]
        if ticker_events.empty:
            continue

        rows = metrics.loc[row_index]
        for idx in rows.index:
            shares = current_shares.loc[idx]
            start_date = period_end.loc[idx]
            end_date = snapshot_date.loc[idx]
            if pd.isna(shares) or shares <= 0 or pd.isna(start_date) or pd.isna(end_date):
                continue

            reflected_cutoff = end_date - pd.Timedelta(days=SHARE_SNAPSHOT_LAG_DAYS)
            future_events = ticker_events[
                (ticker_events["exright_date"] > start_date)
                & (ticker_events["exright_date"] <= reflected_cutoff)
            ]
            if future_events.empty:
                continue

            adjusted_shares.loc[idx] = shares / future_events["share_factor"].prod()

    return adjusted_shares
    
def date_to_quarter(d, delay: int = 0):
    dt = pd.to_datetime(d)
    q = (dt.month - 1) // 3 + 1 - delay
    y = dt.year
    if q == 0:
        q = 4
        y = y -1
    return y, q

def calc_trailing(s: pd.Series, period: int = 4) -> pd.Series:
    rolling_sum = s.rolling(period, min_periods=period).sum()
    expanding_mean = s.expanding(1).mean() * period
    return rolling_sum.fillna(expanding_mean)

def build_wide_financials(reports: pd.DataFrame) -> pd.DataFrame:
    reports = _with_metric_criteria(reports)
    df = reports[
        reports["metric_criteria"].isin(
            [
                "profit",
                "parent_profit",
                "equity",
                "total_assets",
                "revenue",
                "interest_income",
                "interest_expenses",
                "deposit_at_SBV",
                "deposit_at_FI",
                "investment_securities",
                "customer_loan",
            ]
        )
    ].copy()

    wide = (
        df.pivot_table(
            index=["ticker", "year", "quarter"],
            columns="metric_criteria",
            values="value",
            aggfunc="first",
        )
        .reset_index()
        .sort_values(["ticker", "year", "quarter"])
    )

    # ===== ADD earning assets =====
    EARNING_COLS = [
        "deposit_at_SBV",
        "deposit_at_FI",
        "investment_securities",
        "customer_loan",
    ]

    for col in EARNING_COLS:
        if col not in wide.columns:
            wide[col] = 0
    wide[EARNING_COLS] = wide[EARNING_COLS].fillna(0)
    wide["earning_assets"] = wide[EARNING_COLS].sum(axis=1)

    if "profit" not in wide.columns:
        wide["profit"] = np.nan
    if "parent_profit" in wide.columns:
        wide["profit"] = wide["parent_profit"].combine_first(wide["profit"])

    return wide


def build_profit_ttm_from_reports(reports: pd.DataFrame) -> pd.DataFrame:
    reports = _with_metric_criteria(reports)
    profit_df = reports[
        reports["metric_criteria"].isin(["parent_profit", "profit"])
        & (reports["year"] >= 2020)
    ][["ticker", "year", "quarter", "metric_criteria", "value"]].copy()

    if profit_df.empty:
        return pd.DataFrame(
            columns=["ticker", "year", "quarter", "profit", "profit_ttm"]
        )

    profit_df["profit_priority"] = profit_df["metric_criteria"].map(
        {"parent_profit": 0, "profit": 1}
    ).fillna(9)
    profit_df = (
        profit_df.sort_values(
            ["ticker", "year", "quarter", "profit_priority"],
        )
        .drop_duplicates(subset=["ticker", "year", "quarter"], keep="first")
        .rename(columns={"value": "profit"})
        [["ticker", "year", "quarter", "profit"]]
    )

    profit_df = profit_df.sort_values(["ticker", "year", "quarter"])
    profit_df["profit_ttm"] = (
        profit_df
        .groupby("ticker")["profit"]
        .transform(lambda s: calc_trailing(s, 4))
    )
    return profit_df


def apply_report_eps_bvps_from_ticker_metric_shares(
    final_df: pd.DataFrame,
    events: pd.DataFrame,
) -> pd.DataFrame:
    df = final_df.copy()

    def numeric_column(name: str) -> pd.Series:
        if name not in df.columns:
            return pd.Series(np.nan, index=df.index, dtype="float64")
        return pd.to_numeric(df[name], errors="coerce")

    raw_ticker_metric_shares = numeric_column("number_of_shares_mkt_cap")
    if "number_of_shares_mkt_cap" in df.columns:
        ticker_metric_shares = adjust_current_shares_to_period(df, events)
    else:
        ticker_metric_shares = raw_ticker_metric_shares
    fallback_shares = raw_ticker_metric_shares
    shares_for_metrics = ticker_metric_shares.where(
        ticker_metric_shares > 0,
        fallback_shares,
    )
    valid_shares = shares_for_metrics > 0

    df["eps_bvps_share_source"] = np.where(
        ticker_metric_shares > 0,
        "ticker_metric.number_of_shares_mkt_cap_reverse_adjusted",
        np.where(fallback_shares > 0, "silver_ticker_metric.number_of_shares_mkt_cap", None),
    )

    if "profit_ttm" in df.columns:
        valid_eps = valid_shares & pd.to_numeric(df["profit_ttm"], errors="coerce").notna()
        df.loc[valid_eps, "eps"] = (
            df.loc[valid_eps, "profit_ttm"]
            / shares_for_metrics.loc[valid_eps]
            * 1_000_000_000
        )

    if "equity" in df.columns:
        valid_bvps = valid_shares & pd.to_numeric(df["equity"], errors="coerce").notna()
        df.loc[valid_bvps, "bvps"] = (
            df.loc[valid_bvps, "equity"]
            / shares_for_metrics.loc[valid_bvps]
            * 1_000_000_000
        )

    if "number_of_shares_mkt_cap" in df.columns:
        df["number_of_shares_mkt_cap"] = ticker_metric_shares.where(
            ticker_metric_shares > 0,
            shares_for_metrics,
        )

    return df

def calc_roe_roa_with_trailing(
    df: pd.DataFrame,
    period: int = 2,
) -> pd.DataFrame:

    df = df.copy()
    # Equity & Assets trailing average 2 quý
    df["avg_equity"] = (
        df.groupby("ticker")["equity"]
        .transform(lambda s: calc_trailing(s, period)) / period
    )

    df["avg_assets"] = (
        df.groupby("ticker")["total_assets"]
        .transform(lambda s: calc_trailing(s, period)) / period
    )

    # ROE & ROA
    df["roe"] = safe_divide(
        df["profit"],
        df["avg_equity"],
    )

    df["roa"] = safe_divide(
        df["profit"],
        df["avg_assets"],
    )
    return df

def calc_bvps(
    df: pd.DataFrame,
    share_col: str = "issue_shares",
) -> pd.DataFrame:

    df = df.copy()
    df["bvps"] = df["equity"] / df[share_col]
    return df


def latest_overview_by_ticker(overview: pd.DataFrame) -> pd.DataFrame:
    if overview is None or overview.empty:
        return pd.DataFrame(
            columns=["ticker", "industry", "date_fetched"]
        )

    df = overview.copy()
    if "ticker" not in df.columns and "symbol" in df.columns:
        df["ticker"] = df["symbol"]
    if "ticker" not in df.columns:
        return pd.DataFrame(
            columns=["ticker", "industry", "date_fetched"]
        )

    for column in ["industry", "date_fetched"]:
        if column not in df.columns:
            df[column] = np.nan

    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df = df[df["ticker"].ne("")]
    df["date_fetched"] = pd.to_datetime(df["date_fetched"], errors="coerce")

    if "_partition_key" in df.columns:
        partition_date = pd.to_datetime(df["_partition_key"], errors="coerce")
        df["_overview_sort_date"] = df["date_fetched"].fillna(partition_date)
    else:
        df["_overview_sort_date"] = df["date_fetched"]

    return (
        df.sort_values(["ticker", "_overview_sort_date"], na_position="first")
        .drop_duplicates("ticker", keep="last")
        .drop(columns=["_overview_sort_date"])
        .reset_index(drop=True)
    )

@asset(
    partitions_def=report_partitions,
    io_manager_key="minio_io_manager",
    ins={
        "overview": AssetIn(
            ["silver", "company_info", "silver_overview"],
            metadata={
                "load_latest_partition": True,
                "allow_unpartitioned_fallback": True,
            },
            partition_mapping=AllPartitionMapping(),
        ),
        "reports": AssetIn(
            ["silver", "silver_reports"],
            metadata={"load_all_partitions": True},
            partition_mapping=AllPartitionMapping(),
        ),
        "ratio_summary": AssetIn(
            ["silver", "silver_ticker_metric"],
            metadata={"load_all_partitions": True},
            partition_mapping=AllPartitionMapping(),
        ),
    },
    group_name="gold",
    key_prefix=["gold"],
)
def gold_ticker_metric(
    context,
    overview: pd.DataFrame,
    reports: pd.DataFrame,
    ratio_summary: pd.DataFrame,
) -> Output[pd.DataFrame]:
    year, quarter = map(int, context.partition_key.split("-Q"))
    reports_for_metrics = _with_metric_criteria(reports)
    overview = latest_overview_by_ticker(overview)

    # ======================
    # 1. EPS (TTM 4 quý)
    # ======================
    profit_df = build_profit_ttm_from_reports(reports_for_metrics)

    # ======================
    # 3. ROE / ROA (trailing = 2)
    # ======================
    wide_fin = build_wide_financials(reports_for_metrics)

    ratio_df = calc_roe_roa_with_trailing(
        wide_fin,
        period=2,
    )

    # trailing equity 4 quý cho NIM
    ratio_df["avg_earning_assets_4q"] = (
        ratio_df
        .groupby("ticker")["earning_assets"]
        .transform(lambda s: calc_trailing(s, 4)) / 4
    )

    ratio_df = ratio_df.merge(
        overview[["ticker", "industry"]],
        on="ticker",
        how="left",
    )

    BANK_MASK = (
        ratio_df["industry"]
        .str.lower()
        .str.contains("ngân hàng", na=False)
    )

    ratio_df["nim"] = np.nan

    ratio_df.loc[BANK_MASK, "nim"] = safe_divide(
        ratio_df.loc[BANK_MASK, "interest_income"]
        + ratio_df.loc[BANK_MASK, "interest_expenses"],
        ratio_df.loc[BANK_MASK, "avg_earning_assets_4q"],
    )*4

    ratio_metrics = select_ratio_summary_metrics(ratio_summary, year, quarter)
    share_df = ratio_metrics[
        [
            column
            for column in [
                "ticker",
                "year",
                "quarter",
                "number_of_shares_mkt_cap",
                "market_cap",
                "pe",
                "pb",
                "date_fetched",
            ]
            if column in ratio_metrics.columns
        ]
    ].copy()
    for column in [
        "ticker",
        "year",
        "quarter",
        "number_of_shares_mkt_cap",
        "market_cap",
        "pe",
        "pb",
        "date_fetched",
    ]:
        if column not in share_df.columns:
            share_df[column] = np.nan
    share_df["ticker"] = share_df["ticker"].astype(str).str.strip().str.upper()
    share_df["year"] = year
    share_df["quarter"] = quarter
    share_df["issue_share_adj"] = pd.to_numeric(
        share_df["number_of_shares_mkt_cap"],
        errors="coerce",
    )
    share_df["number_of_shares_mkt_cap"] = share_df["issue_share_adj"].round(0)
    share_df["issue_share_adj"] = share_df["number_of_shares_mkt_cap"]
    for column in ["market_cap", "pe", "pb"]:
        share_df[column] = pd.to_numeric(share_df[column], errors="coerce")
    share_df["price"] = safe_divide(
        share_df["market_cap"],
        share_df["number_of_shares_mkt_cap"],
    )

    profit_df = profit_df.drop(columns=["issue_share_adj", "eps"], errors="ignore")
    profit_df = profit_df.merge(
        share_df[["ticker", "year", "quarter", "issue_share_adj", "price", "pe"]],
        on=["ticker", "year", "quarter"],
        how="left",
    )
    profit_df["eps"] = safe_divide_nonzero(profit_df["price"], profit_df["pe"])

    # ======================
    # 4. BVPS
    # ======================
    ratio_df = ratio_df.merge(
        share_df[[
            "ticker",
            "year",
            "quarter",
            "issue_share_adj",
            "market_cap",
            "price",
            "pe",
            "pb",
        ]],
        on=["ticker", "year", "quarter"],
        how="left",
    )
    ratio_df = ratio_df.merge(
        profit_df[["ticker", "year", "quarter", "profit_ttm"]],
        on=["ticker", "year", "quarter"],
        how="left",
    )

    ratio_df["bvps"] = safe_divide_nonzero(ratio_df["price"], ratio_df["pb"])
    # ROS
    ratio_df["ros"] = safe_divide(
        ratio_df["profit"],
        ratio_df["revenue"],
    )

    ratio_df.loc[BANK_MASK, "ros"] = np.nan

    # ======================
    # 5. Merge output dạng WIDE
    # ======================

    eps_df = profit_df[
        ["ticker", "year", "quarter", "eps", "profit_ttm", "issue_share_adj"]
    ]

    ratio_out = ratio_df[
        ["ticker", "year", "quarter", "bvps", "roe", "roa", "ros", "nim", "equity"]
    ]

    final_df = eps_df.merge(
        ratio_out,
        on=["ticker", "year", "quarter"],
        how="left",
    )

    ratio_df = ratio_df.dropna(subset=["industry"])

    industry_agg = (
        ratio_df
        .groupby(["industry", "year", "quarter"])
        .agg(
            equity_sum=("equity", "sum"),
            shares_sum=("issue_share_adj", "sum"),
            profit_sum=("profit", "sum"),
            avg_equity_sum=("avg_equity", "sum"),
            avg_assets_sum=("avg_assets", "sum"),
            revenue_sum=("revenue", "sum"),
            market_cap_sum=("market_cap", "sum"),
            profit_ttm_sum=("profit_ttm", "sum"),
        )
        .reset_index()
    )
    industry_agg["market_cap_sum_billion"] = industry_agg["market_cap_sum"] / 1_000_000_000

    industry_agg["bvps_industry"] = safe_divide(
        industry_agg["equity_sum"],
        industry_agg["shares_sum"],
    ) * 1_000_000_000

    industry_agg["pe_industry"] = safe_divide_nonzero(
        industry_agg["market_cap_sum_billion"],
        industry_agg["profit_ttm_sum"],
    )

    industry_agg["pb_industry"] = safe_divide_nonzero(
        industry_agg["market_cap_sum_billion"],
        industry_agg["equity_sum"],
    )

    industry_agg["roe_industry"] = safe_divide(
        industry_agg["profit_sum"],
        industry_agg["avg_equity_sum"],
    )

    industry_agg["roa_industry"] = safe_divide(
        industry_agg["profit_sum"],
        industry_agg["avg_assets_sum"],
    )

    industry_agg["ros_industry"] = safe_divide(
        industry_agg["profit_sum"],
        industry_agg["revenue_sum"],
    )
    bank_industry_mask = (
        industry_agg["industry"]
        .str.lower()
        .str.contains("ngân hàng", na=False)
    )
    industry_agg.loc[bank_industry_mask, "ros_industry"] = np.nan

    final_df = final_df.merge(
        overview[["ticker", "industry"]],
        on="ticker",
        how="left",
    )

    nim_industry_df = (
        ratio_df[BANK_MASK]
        .groupby(["industry", "year", "quarter"])
        .agg(
            interest_income_sum=("interest_income", "sum"),
            interest_expenses_sum=("interest_expenses", "sum"),
            avg_equity_4q_sum=("avg_earning_assets_4q", "sum"),
        )
        .reset_index()
    )

    nim_industry_df["nim_industry"] = safe_divide(
        nim_industry_df["interest_income_sum"]
        + nim_industry_df["interest_expenses_sum"],
        nim_industry_df["avg_equity_4q_sum"],
    )*4

    industry_agg = industry_agg.merge(
        nim_industry_df[
            ["industry", "year", "quarter", "nim_industry"]
        ],
        on=["industry", "year", "quarter"],
        how="left",
    )

    final_df = final_df.merge(
        industry_agg[
            [
                "industry", "year", "quarter",
                "pe_industry", "pb_industry",
                "bvps_industry", "roe_industry",
                "roa_industry", "ros_industry",
                "nim_industry"
            ]
        ],
        on=["industry", "year", "quarter"],
        how="left",
    )

    final_df = final_df.merge(
        share_df[[
            "ticker",
            "year",
            "quarter",
            "number_of_shares_mkt_cap",
            "market_cap",
            "pe",
            "pb",
            "price",
            "date_fetched",
        ]],
        on=["ticker", "year", "quarter"],
        how="left",
    )

    ratio_metric_columns = [
        column
        for column in ratio_metrics.columns
        if column not in {"ticker", "year", "quarter"}
        and column not in final_df.columns
    ]
    if ratio_metric_columns:
        final_df = final_df.merge(
            ratio_metrics[["ticker", "year", "quarter", *ratio_metric_columns]],
            on=["ticker", "year", "quarter"],
            how="left",
        )

    # ======================
    # 6. ROUNDING METRICS
    # ======================

    FOUR_DEC_COLS = [
        "roe", "roa", "ros", "nim",
        "roe_industry", "roa_industry", "ros_industry", "nim_industry",
    ]

    TWO_DEC_COLS = [
        c for c in final_df.select_dtypes("number").columns
        if c not in FOUR_DEC_COLS
    ]

    final_df[FOUR_DEC_COLS] = final_df[FOUR_DEC_COLS].round(4)
    final_df[TWO_DEC_COLS] = final_df[TWO_DEC_COLS].round(2)

    out_df = final_df[
        (final_df["year"] == year)
        & (final_df["quarter"] == quarter)
    ].copy()

    for column in TICKER_METRIC_COLUMNS:
        if column not in out_df.columns:
            out_df[column] = np.nan

    out_df = out_df[TICKER_METRIC_COLUMNS]

    return Output(
        out_df,
        metadata={
            "num_records": len(out_df),
            "columns": TICKER_METRIC_COLUMNS,
            "eps_bvps_share_source": (
                "pe/pb, market_cap, and number_of_shares_mkt_cap are kept from "
                "silver_ticker_metric for current partition; "
                "price = market_cap / number_of_shares_mkt_cap; "
                "eps = price / pe; bvps = price / pb; "
                "industry pe = sum(market_cap / 1_000_000_000) / sum(profit_ttm); "
                "industry pb = sum(market_cap / 1_000_000_000) / sum(equity); "
                "gold_ticker_metric does not adjust shares from events"
            ),
            "share_base_period_lag_quarters": 0,
            "excluded_daily_market_metrics": [
                "ps",
                "price_to_cash_flow",
                "ev_to_ebitda",
            ],
        },
    )

@asset(
    partitions_def=report_partitions,
    ins={
        "gold_ticker_metric": AssetIn(
            key_prefix=["gold"]
        )
    },
    io_manager_key="psql_io_manager",
    key_prefix=["warehouse"],
    compute_kind="python",
    group_name="warehouse",
)
def warehouse_ticker_metric (gold_ticker_metric: pd.DataFrame,
) -> Output[pd.DataFrame]:

    return Output(
        gold_ticker_metric,
        metadata={
            "table": "warehouse.warehouse_ticker_metric",
            "rows_loaded": len(gold_ticker_metric),
            "unique_key": ["ticker", "year", "quarter"],
        },
    )
