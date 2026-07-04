import pandas as pd
import numpy as np
from dagster import AllPartitionMapping, AssetDep, asset, AssetIn, AssetKey, Output, MetadataValue
from datetime import datetime
from etl_pipeline.assets.partitions import price_1d_daily
from etl_pipeline.assets.bronze.prices import symbol_file_name
from etl_pipeline.assets.gold.ticker_metric import (
    build_profit_ttm_from_reports,
    build_share_dilution_events,
    build_wide_financials,
)
from etl_pipeline.ops.tickers import HOSE_INDEX_TICKERS

daily = price_1d_daily

INDEX_TICKERS = HOSE_INDEX_TICKERS
SILVER_PRICES_1D_KEY = AssetKey(["silver", "silver_prices_1d"])
GOLD_PRICES_1D_KEY = AssetKey(["gold", "gold_prices_1d"])
PRICE_ADJUSTMENT_EVENT_TYPE_IDS = {3, 4}
PRICE_COLUMNS_TO_ADJUST = ["open", "high", "low", "close"]
PRICE_DERIVED_COLUMNS_TO_ADJUST = ["market_cap"]
GOLD_PRICE_REQUIRED_COLUMNS = {
    "ticker",
    "date",
    "close",
    "market_cap",
    "number_of_shares_mkt_cap",
    "eps",
    "bvps",
    "pe",
    "pb",
}


def build_price_adjustment_events(events: pd.DataFrame, as_of_date=None) -> pd.DataFrame:
    required_columns = {"ticker", "event_type_id", "exright_date", "rate_original", "rate_split"}
    if events is None or events.empty or not required_columns.issubset(events.columns):
        return pd.DataFrame(columns=["event_id", "ticker", "exright_date", "price_adjustment_factor"])

    df = events.copy()
    if "event_id" in df.columns:
        df = df.drop_duplicates(subset=["event_id"], keep="last")
    else:
        df["event_id"] = None

    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["event_type_id"] = pd.to_numeric(df["event_type_id"], errors="coerce").astype("Int64")
    df["exright_date"] = pd.to_datetime(df["exright_date"], errors="coerce").dt.normalize()
    df["rate_original"] = pd.to_numeric(df["rate_original"], errors="coerce")
    df["rate_split"] = pd.to_numeric(df["rate_split"], errors="coerce")

    df = df[
        df["event_type_id"].isin(PRICE_ADJUSTMENT_EVENT_TYPE_IDS)
        & df["exright_date"].notna()
        & (df["rate_original"] > 0)
        & (df["rate_split"] > 0)
    ].copy()
    if df.empty:
        return pd.DataFrame(columns=["event_id", "ticker", "exright_date", "price_adjustment_factor"])

    if as_of_date is not None:
        as_of_date = pd.to_datetime(as_of_date).normalize()
        df = df[df["exright_date"] <= as_of_date].copy()

    if df.empty:
        return pd.DataFrame(columns=["event_id", "ticker", "exright_date", "price_adjustment_factor"])

    fallback_ids = (
        df["ticker"]
        + "|"
        + df["exright_date"].dt.strftime("%Y-%m-%d")
        + "|"
        + df["event_type_id"].astype(str)
        + "|"
        + df["rate_original"].astype(str)
        + ":"
        + df["rate_split"].astype(str)
    )
    df["event_id"] = df["event_id"].fillna(fallback_ids).astype(str)
    df["price_adjustment_factor"] = 1 + df["rate_split"] / df["rate_original"]
    return df[["event_id", "ticker", "exright_date", "price_adjustment_factor"]].sort_values(
        ["ticker", "exright_date"]
    )


def _append_marker(existing, marker: str):
    if pd.isna(existing) or existing in ("", None):
        return marker
    values = str(existing).split("|")
    if marker in values:
        return str(existing)
    return f"{existing}|{marker}"


def apply_due_price_adjustments(
    prices: pd.DataFrame,
    events: pd.DataFrame,
    *,
    as_of_date,
    only_missing_events: bool = False,
) -> pd.DataFrame:
    adjustment_events = build_price_adjustment_events(events, as_of_date=as_of_date)
    df = prices.copy()

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()

    if "price_adjustment_factor" not in df.columns:
        df["price_adjustment_factor"] = 1.0
    else:
        df["price_adjustment_factor"] = pd.to_numeric(
            df["price_adjustment_factor"],
            errors="coerce",
        ).fillna(1.0)

    if "price_adjusted" not in df.columns:
        df["price_adjusted"] = False
    if "price_adjustment_event_ids" not in df.columns:
        df["price_adjustment_event_ids"] = ""
    if "price_adjustment_exright_dates" not in df.columns:
        df["price_adjustment_exright_dates"] = ""
    if "price_adjustment_updated_at" not in df.columns:
        df["price_adjustment_updated_at"] = None

    if df.empty or adjustment_events.empty:
        return df

    updated_at = datetime.now().isoformat()

    for event in adjustment_events.itertuples(index=False):
        event_id = str(event.event_id)
        exright_date = pd.to_datetime(event.exright_date).normalize()
        factor = float(event.price_adjustment_factor)
        if not np.isfinite(factor) or factor <= 0:
            continue

        mask = (
            (df["ticker"].astype(str).str.upper() == event.ticker)
            & (df["date"] < exright_date)
        )
        if only_missing_events:
            mask &= ~df["price_adjustment_event_ids"].fillna("").astype(str).str.split("|").apply(
                lambda values: event_id in values
            )

        if not mask.any():
            continue

        for column in PRICE_COLUMNS_TO_ADJUST + PRICE_DERIVED_COLUMNS_TO_ADJUST:
            if column in df.columns:
                df.loc[mask, column] = pd.to_numeric(df.loc[mask, column], errors="coerce") / factor

        df.loc[mask, "price_adjustment_factor"] = df.loc[mask, "price_adjustment_factor"] * factor
        df.loc[mask, "price_adjusted"] = True
        df.loc[mask, "price_adjustment_event_ids"] = df.loc[mask, "price_adjustment_event_ids"].apply(
            lambda value: _append_marker(value, event_id)
        )
        exright_marker = exright_date.strftime("%Y-%m-%d")
        df.loc[mask, "price_adjustment_exright_dates"] = df.loc[mask, "price_adjustment_exright_dates"].apply(
            lambda value: _append_marker(value, exright_marker)
        )
        df.loc[mask, "price_adjustment_updated_at"] = updated_at

    return df


def refresh_historical_gold_price_adjustments(context, events: pd.DataFrame, as_of_date) -> dict:
    io = context.resources.minio_io_manager
    asset_key = context.asset_key
    adjustment_events = build_price_adjustment_events(events, as_of_date=as_of_date)
    if adjustment_events.empty:
        return {"partitions_checked": 0, "partitions_updated": 0, "rows_updated": 0}

    event_tickers = set(adjustment_events["ticker"].dropna().astype(str))
    earliest_exright = adjustment_events["exright_date"].min()
    partitions = [partition for partition in io.list_partitions(asset_key) if partition != context.partition_key]

    partitions_checked = 0
    partitions_updated = 0
    rows_updated = 0

    for partition_key in sorted(partitions):
        partition_date = pd.to_datetime(partition_key, errors="coerce")
        if pd.isna(partition_date) or partition_date >= earliest_exright:
            continue

        try:
            partition_df = io.load_partition(asset_key, partition_key)
        except FileNotFoundError:
            continue

        partitions_checked += 1
        if partition_df.empty or "ticker" not in partition_df.columns:
            continue

        before_factor = (
            pd.to_numeric(partition_df.get("price_adjustment_factor", 1.0), errors="coerce")
            .fillna(1.0)
            .copy()
        )
        if not partition_df["ticker"].astype(str).str.upper().isin(event_tickers).any():
            continue

        adjusted_df = apply_due_price_adjustments(
            partition_df,
            adjustment_events,
            as_of_date=as_of_date,
            only_missing_events=True,
        )
        after_factor = pd.to_numeric(adjusted_df["price_adjustment_factor"], errors="coerce").fillna(1.0)
        changed = after_factor.ne(before_factor)
        if not changed.any():
            continue

        io.write_partition(asset_key, partition_key, adjusted_df)
        partitions_updated += 1
        rows_updated += int(changed.sum())

    return {
        "partitions_checked": partitions_checked,
        "partitions_updated": partitions_updated,
        "rows_updated": rows_updated,
        "event_count": len(adjustment_events),
    }


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


def merge_share_base_from_ratio_summary(
    prices: pd.DataFrame,
    ratio_summary: pd.DataFrame,
) -> pd.DataFrame:
    df = prices.copy()
    df["share_count"] = np.nan
    df["share_source_year"] = np.nan
    df["share_source_quarter"] = np.nan
    df["share_source_date_fetched"] = pd.NaT

    required = {"ticker", "year", "quarter", "number_of_shares_mkt_cap"}
    if ratio_summary is None or ratio_summary.empty:
        return df

    source = ratio_summary.copy()
    if "ticker" not in source.columns and "symbol" in source.columns:
        source["ticker"] = source["symbol"]
    if not required.issubset(source.columns):
        return df

    source["ticker"] = source["ticker"].astype(str).str.strip().str.upper()
    source["year"] = pd.to_numeric(source["year"], errors="coerce")
    source["quarter"] = pd.to_numeric(source["quarter"], errors="coerce")
    source["number_of_shares_mkt_cap"] = pd.to_numeric(
        source["number_of_shares_mkt_cap"],
        errors="coerce",
    )
    source = source[
        source["ticker"].ne("")
        & source["year"].notna()
        & source["quarter"].notna()
        & source["number_of_shares_mkt_cap"].notna()
        & (source["number_of_shares_mkt_cap"] > 0)
    ].copy()
    if source.empty:
        return df

    if "ratio_type" in source.columns:
        ttm_source = source[source["ratio_type"].astype(str).str.upper().eq("RATIO_TTM")]
        if not ttm_source.empty:
            source = ttm_source.copy()

    if "date_fetched" in source.columns:
        source["date_fetched"] = pd.to_datetime(source["date_fetched"], errors="coerce")
    else:
        source["date_fetched"] = pd.NaT

    source["year"] = source["year"].astype("int64")
    source["quarter"] = source["quarter"].astype("int64")
    source["period_order"] = source["year"] * 4 + source["quarter"]
    source["period_order"] = source["period_order"].astype("int64")
    source = source.sort_values(["ticker", "period_order", "date_fetched"])
    source = source.drop_duplicates(["ticker", "period_order"], keep="last")

    left = df[["ticker", "share_base_year", "share_base_quarter"]].copy()
    left["_row_id"] = df.index
    left["share_base_year"] = pd.to_numeric(left["share_base_year"], errors="coerce")
    left["share_base_quarter"] = pd.to_numeric(left["share_base_quarter"], errors="coerce")
    left["share_base_order"] = left["share_base_year"] * 4 + left["share_base_quarter"]
    left = left[left["ticker"].notna() & left["share_base_order"].notna()].copy()
    if left.empty:
        return df
    left["share_base_order"] = left["share_base_order"].astype("int64")

    merged_parts = []
    for ticker, left_part in left.groupby("ticker", sort=False):
        source_part = source[source["ticker"] == ticker]
        if source_part.empty:
            continue
        merged = pd.merge_asof(
            left_part.sort_values("share_base_order"),
            source_part[
                [
                    "period_order",
                    "year",
                    "quarter",
                    "number_of_shares_mkt_cap",
                    "date_fetched",
                ]
            ].sort_values("period_order"),
            left_on="share_base_order",
            right_on="period_order",
            direction="backward",
        )
        merged_parts.append(merged)

    if not merged_parts:
        return df

    merged = pd.concat(merged_parts, ignore_index=True).set_index("_row_id")
    df.loc[merged.index, "share_count"] = merged["number_of_shares_mkt_cap"]
    df.loc[merged.index, "share_source_year"] = merged["year"]
    df.loc[merged.index, "share_source_quarter"] = merged["quarter"]
    df.loc[merged.index, "share_source_date_fetched"] = merged["date_fetched"]
    return df


def build_report_price_metrics(reports: pd.DataFrame) -> pd.DataFrame:
    columns = ["ticker", "year", "quarter", "profit_ttm", "equity"]
    if reports is None or reports.empty:
        return pd.DataFrame(columns=columns)

    profit_df = build_profit_ttm_from_reports(reports)
    wide_df = build_wide_financials(reports)
    if wide_df.empty and profit_df.empty:
        return pd.DataFrame(columns=columns)

    if wide_df.empty:
        metrics = profit_df.copy()
    else:
        equity_columns = ["ticker", "year", "quarter"]
        if "equity" in wide_df.columns:
            equity_columns.append("equity")
        metrics = wide_df[equity_columns].copy()
        if not profit_df.empty:
            metrics = metrics.merge(
                profit_df[["ticker", "year", "quarter", "profit_ttm"]],
                on=["ticker", "year", "quarter"],
                how="outer",
            )

    for column in columns:
        if column not in metrics.columns:
            metrics[column] = np.nan
    metrics["ticker"] = metrics["ticker"].astype(str).str.strip().str.upper()
    metrics["year"] = pd.to_numeric(metrics["year"], errors="coerce")
    metrics["quarter"] = pd.to_numeric(metrics["quarter"], errors="coerce")
    metrics["profit_ttm"] = pd.to_numeric(metrics["profit_ttm"], errors="coerce")
    metrics["equity"] = pd.to_numeric(metrics["equity"], errors="coerce")
    metrics = metrics[
        metrics["ticker"].ne("")
        & metrics["year"].notna()
        & metrics["quarter"].notna()
    ].copy()
    if metrics.empty:
        return pd.DataFrame(columns=columns)
    metrics["year"] = metrics["year"].astype("int64")
    metrics["quarter"] = metrics["quarter"].astype("int64")
    return metrics[columns].drop_duplicates(
        subset=["ticker", "year", "quarter"],
        keep="last",
    )


def merge_report_metrics_for_prices(prices: pd.DataFrame, reports: pd.DataFrame) -> pd.DataFrame:
    df = prices.copy()
    metrics = build_report_price_metrics(reports)
    if metrics.empty:
        df["profit_ttm"] = np.nan
        df["equity"] = np.nan
        return df

    metrics = metrics.rename(
        columns={
            "year": "share_base_year",
            "quarter": "share_base_quarter",
        }
    )
    return df.merge(
        metrics,
        on=["ticker", "share_base_year", "share_base_quarter"],
        how="left",
    )


def apply_share_dilution_to_daily_metrics(
    prices: pd.DataFrame,
    events: pd.DataFrame,
) -> pd.DataFrame:
    dilution_events = build_share_dilution_events(events)
    if prices.empty or dilution_events.empty:
        prices["share_adjustment_factor"] = 1.0
        return prices

    df = prices.copy()
    df["share_adjustment_factor"] = 1.0

    for ticker, row_index in df.groupby("ticker").groups.items():
        ticker_events = dilution_events[dilution_events["ticker"] == ticker]
        if ticker_events.empty:
            continue

        rows = df.loc[row_index]
        rows = rows[rows["date"].notna()]
        if rows.empty:
            continue

        event_dates = ticker_events["exright_date"].to_numpy(dtype="datetime64[ns]")
        cumulative_factors = ticker_events["share_factor"].cumprod().to_numpy()
        price_dates = rows["date"].to_numpy(dtype="datetime64[ns]")

        end_positions = np.searchsorted(event_dates, price_dates, side="right") - 1
        end_factors = np.where(end_positions >= 0, cumulative_factors[end_positions], 1.0)

        if "share_base_period_end" in rows.columns:
            share_start_dates = rows["share_base_period_end"].to_numpy(dtype="datetime64[ns]")
        else:
            share_start_dates = pd.Series(pd.NaT, index=rows.index).to_numpy(dtype="datetime64[ns]")
        share_start_positions = np.searchsorted(event_dates, share_start_dates, side="right") - 1
        share_start_factors = np.where(
            share_start_positions >= 0,
            cumulative_factors[share_start_positions],
            1.0,
        )
        share_adjustment_factors = end_factors / share_start_factors

        valid = np.isfinite(share_adjustment_factors) & (share_adjustment_factors > 0)
        target_index = rows.index[valid]
        df.loc[target_index, "share_adjustment_factor"] = share_adjustment_factors[valid]

    adjusted_shares = df["share_adjustment_factor"] > 1
    if "share_count" in df.columns:
        df.loc[adjusted_shares, "share_count"] = (
            df.loc[adjusted_shares, "share_count"]
            * df.loc[adjusted_shares, "share_adjustment_factor"]
        )
    return df

def load_nearest_partition(
    io,
    asset_key,
    target_date: str,
    max_lookback: int = 10,
    in_memory_partitions: dict[str, pd.DataFrame] | None = None,
):
    """
    Try to load partition at target_date.
    If not exists, fallback to nearest previous date (up to max_lookback days).
    """
    dt = pd.to_datetime(target_date)
    in_memory_partitions = in_memory_partitions or {}

    for i in range(max_lookback + 1):
        date_str = (dt - pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        if date_str in in_memory_partitions:
            return in_memory_partitions[date_str], date_str

        try:
            return io.load_partition(asset_key, date_str), date_str
        except FileNotFoundError:
            continue

    return None, None

def calc_pct_change(
    df_today: pd.DataFrame,
    df_past: pd.DataFrame,
) -> pd.Series:
    return (df_today["close"] / df_past["close"] - 1) * 100

OFFSETS = {
    "chg_1d": 1,
    "chg_1w": 7,
    "chg_1m": 30,
    "chg_3m": 90,
    "chg_6m": 180,
    "chg_1y": 365,
    "chg_3y": 1095,
}


def empty_gold_price_manifest() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "partition_date",
            "action",
            "reason",
            "source_file_path",
            "output_start_date",
            "output_end_date",
            "rows_output",
            "rows_stored",
            "history_hash",
            "file_path",
        ]
    )


def ticker_from_symbol_file(file_path: str) -> str:
    return file_path.replace("\\", "/").split("/")[-1].replace(".parquet", "").upper()


def manifest_from_silver_symbol_files(io) -> pd.DataFrame:
    files = [
        file_path
        for file_path in io.list_asset_files(SILVER_PRICES_1D_KEY)
        if file_path.lower().endswith(".parquet")
    ]
    return pd.DataFrame(
        [
            {
                "ticker": ticker_from_symbol_file(file_path),
                "action": "overwrite",
                "reason": "silver_symbol_file_fallback",
                "file_path": file_path,
                "output_start_date": None,
                "output_end_date": None,
            }
            for file_path in files
        ],
        columns=[
            "ticker",
            "action",
            "reason",
            "file_path",
            "output_start_date",
            "output_end_date",
        ],
    )


def dataframe_history_hash(df: pd.DataFrame) -> str:
    if df.empty:
        return ""

    import hashlib

    hash_df = df.copy()
    for column in hash_df.columns:
        if pd.api.types.is_datetime64_any_dtype(hash_df[column]):
            hash_df[column] = pd.to_datetime(hash_df[column], errors="coerce").dt.strftime("%Y-%m-%d")
    hash_df = hash_df.reindex(sorted(hash_df.columns), axis=1)
    hash_df = hash_df.sort_values(
        [column for column in ["ticker", "date"] if column in hash_df.columns]
    ).reset_index(drop=True)
    row_hashes = pd.util.hash_pandas_object(hash_df.astype("string"), index=False).values.tobytes()
    return hashlib.sha256(row_hashes).hexdigest()


def gold_symbol_needs_rebuild(io, file_path: str) -> bool:
    try:
        existing_df = io.load_asset_file(GOLD_PRICES_1D_KEY, file_path)
    except FileNotFoundError:
        return True
    return not GOLD_PRICE_REQUIRED_COLUMNS.issubset(existing_df.columns)


def existing_gold_skip_manifest_rows(
    io,
    manifest: pd.DataFrame,
    partition_key: str,
) -> list[dict]:
    if manifest is None or manifest.empty:
        return []

    rows = []
    for row in manifest.itertuples(index=False):
        action = str(getattr(row, "action", "") or "").lower()
        if action != "skip":
            continue

        file_path = getattr(row, "file_path", None)
        if not file_path or gold_symbol_needs_rebuild(io, file_path):
            continue

        try:
            existing_df = io.load_asset_file(GOLD_PRICES_1D_KEY, file_path)
        except FileNotFoundError:
            continue
        if existing_df.empty or "date" not in existing_df.columns:
            continue

        existing_df = existing_df.copy()
        existing_df["date"] = pd.to_datetime(existing_df["date"], errors="coerce")
        dates = existing_df["date"].dropna()
        if dates.empty:
            continue

        rows.append(
            {
                "ticker": str(getattr(row, "ticker", ticker_from_symbol_file(file_path))).strip().upper(),
                "partition_date": partition_key,
                "action": "skip",
                "reason": getattr(row, "reason", "up_to_date"),
                "source_file_path": file_path,
                "output_start_date": dates.min().strftime("%Y-%m-%d"),
                "output_end_date": dates.max().strftime("%Y-%m-%d"),
                "rows_output": 0,
                "rows_stored": len(existing_df),
                "history_hash": dataframe_history_hash(existing_df),
                "file_path": file_path,
            }
        )
    return rows


def load_prices_from_silver_manifest(io, manifest: pd.DataFrame) -> pd.DataFrame:
    if manifest is None or manifest.empty:
        return pd.DataFrame()

    frames = []
    for row in manifest.itertuples(index=False):
        action = str(getattr(row, "action", "overwrite") or "overwrite").lower()
        file_path = getattr(row, "file_path", None)
        if not file_path:
            continue

        reason = getattr(row, "reason", None)
        if action == "skip":
            if not gold_symbol_needs_rebuild(io, file_path):
                continue
            action = "overwrite"
            reason = f"{reason}|gold_rebuild_required" if reason else "gold_rebuild_required"

        output_start_date = getattr(row, "output_start_date", None)
        output_end_date = getattr(row, "output_end_date", None)

        try:
            symbol_df = io.load_asset_file(SILVER_PRICES_1D_KEY, file_path)
        except FileNotFoundError:
            continue

        symbol_df = symbol_df.copy()
        symbol_df["date"] = pd.to_datetime(symbol_df["date"], errors="coerce")
        if pd.notna(output_start_date) and pd.notna(output_end_date):
            start_date = pd.to_datetime(output_start_date)
            end_date = pd.to_datetime(output_end_date)
            symbol_df = symbol_df[
                (symbol_df["date"] >= start_date)
                & (symbol_df["date"] <= end_date)
            ].copy()
        if not symbol_df.empty:
            symbol_df["_source_action"] = action
            symbol_df["_source_reason"] = reason
            symbol_df["_source_file_path"] = file_path
            frames.append(symbol_df)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def load_prices_from_gold_manifest(io, manifest: pd.DataFrame) -> pd.DataFrame:
    if manifest is None or manifest.empty:
        return pd.DataFrame()

    frames = []
    for row in manifest.itertuples(index=False):
        action = getattr(row, "action", None)
        if action == "skip":
            continue

        file_path = getattr(row, "file_path", None)
        output_start_date = getattr(row, "output_start_date", None)
        output_end_date = getattr(row, "output_end_date", None)
        if not file_path or pd.isna(output_start_date) or pd.isna(output_end_date):
            continue

        try:
            symbol_df = io.load_asset_file(GOLD_PRICES_1D_KEY, file_path)
        except FileNotFoundError:
            continue

        symbol_df = symbol_df.copy()
        symbol_df["date"] = pd.to_datetime(symbol_df["date"], errors="coerce")
        start_date = pd.to_datetime(output_start_date)
        end_date = pd.to_datetime(output_end_date)
        symbol_df = symbol_df[
            (symbol_df["date"] >= start_date)
            & (symbol_df["date"] <= end_date)
        ].copy()
        if not symbol_df.empty:
            frames.append(symbol_df)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def load_all_gold_price_symbol_files(
    io,
    context=None,
    only_tickers: set[str] | None = None,
) -> pd.DataFrame:
    frames = []
    only_tickers = {
        str(ticker).strip().upper()
        for ticker in (only_tickers or set())
        if str(ticker).strip()
    }
    files = [
        file_path
        for file_path in io.list_asset_files(GOLD_PRICES_1D_KEY)
        if str(file_path).lower().endswith(".parquet")
        and (not only_tickers or ticker_from_symbol_file(file_path) in only_tickers)
    ]
    total_files = len(files)
    if context is not None:
        context.log.info(
            "WAREHOUSE PRICES LOAD START | "
            f"gold_symbol_files={total_files} | "
            f"ticker_filter_count={len(only_tickers) if only_tickers else 0}"
        )

    for idx, file_path in enumerate(files, start=1):
        if not str(file_path).lower().endswith(".parquet"):
            continue
        try:
            symbol_df = io.load_asset_file(GOLD_PRICES_1D_KEY, file_path)
        except FileNotFoundError:
            if context is not None:
                context.log.warning(
                    "WAREHOUSE PRICES LOAD MISSING FILE | "
                    f"file={file_path}"
                )
            continue
        if symbol_df.empty:
            if context is not None and (idx == 1 or idx % 50 == 0 or idx == total_files):
                context.log.info(
                    "WAREHOUSE PRICES LOAD PROGRESS | "
                    f"files={idx}/{total_files} | "
                    f"frames={len(frames)} | rows={sum(len(frame) for frame in frames)}"
                )
            continue
        symbol_df = symbol_df.copy()
        if "ticker" not in symbol_df.columns:
            symbol_df["ticker"] = ticker_from_symbol_file(file_path)
        symbol_df["ticker"] = symbol_df["ticker"].astype(str).str.strip().str.upper()
        if "date" in symbol_df.columns:
            symbol_df["date"] = pd.to_datetime(symbol_df["date"], errors="coerce")
        frames.append(symbol_df)
        if context is not None and (idx == 1 or idx % 50 == 0 or idx == total_files):
            context.log.info(
                "WAREHOUSE PRICES LOAD PROGRESS | "
                f"files={idx}/{total_files} | "
                f"last_file={file_path} | "
                f"frames={len(frames)} | rows={sum(len(frame) for frame in frames)}"
            )

    if not frames:
        if context is not None:
            context.log.warning(
                "WAREHOUSE PRICES LOAD EMPTY | "
                f"gold_symbol_files={total_files}"
            )
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    if {"ticker", "date"}.issubset(df.columns):
        df = (
            df.dropna(subset=["ticker", "date"])
            .drop_duplicates(subset=["ticker", "date"], keep="last")
            .sort_values(["ticker", "date"])
            .reset_index(drop=True)
        )
    if context is not None:
        context.log.info(
            "WAREHOUSE PRICES LOAD DONE | "
            f"gold_symbol_files={total_files} | "
            f"symbols={df['ticker'].nunique() if 'ticker' in df.columns else None} | "
            f"rows={len(df)}"
        )
    return df


def build_close_history(
    existing_by_ticker: dict[str, pd.DataFrame],
    current_df: pd.DataFrame,
) -> pd.DataFrame:
    frames = []
    for existing_df in existing_by_ticker.values():
        if existing_df is not None and not existing_df.empty and {"ticker", "date", "close"}.issubset(existing_df.columns):
            frames.append(existing_df[["ticker", "date", "close"]].copy())

    if not current_df.empty:
        frames.append(current_df[["ticker", "date", "close"]].copy())

    if not frames:
        return pd.DataFrame(columns=["ticker", "date", "close"])

    close_history = pd.concat(frames, ignore_index=True)
    close_history["ticker"] = close_history["ticker"].astype(str).str.strip().str.upper()
    close_history["date"] = pd.to_datetime(close_history["date"], errors="coerce").dt.normalize()
    close_history["close"] = pd.to_numeric(close_history["close"], errors="coerce")
    close_history = close_history.dropna(subset=["ticker", "date", "close"])
    return close_history.drop_duplicates(["ticker", "date"], keep="last")


def nearest_close_by_ticker(
    close_history: pd.DataFrame,
    target_date,
    max_lookback: int = 10,
) -> tuple[pd.DataFrame | None, str | None]:
    if close_history.empty:
        return None, None

    target = pd.to_datetime(target_date).normalize()
    min_date = target - pd.Timedelta(days=max_lookback)
    candidates = close_history[
        (close_history["date"] <= target)
        & (close_history["date"] >= min_date)
    ].copy()
    if candidates.empty:
        return None, None

    candidates = candidates.sort_values(["ticker", "date"]).drop_duplicates("ticker", keep="last")
    used_date = candidates["date"].max().strftime("%Y-%m-%d")
    return candidates[["ticker", "close"]], used_date

@asset(
    partitions_def=daily,
    io_manager_key="minio_io_manager",
    ins={
        "ratio_summary": AssetIn(
            ["silver", "silver_ticker_metric"],
            metadata={"load_all_partitions": True},
            partition_mapping=AllPartitionMapping(),
        ),
        "reports": AssetIn(
            ["silver", "silver_reports"],
            metadata={"load_all_partitions": True},
            partition_mapping=AllPartitionMapping(),
        ),
        "events": AssetIn(
            ["silver", "company_info", "silver_events"],
            metadata={
                "allow_unpartitioned_fallback": True,
                "load_all_partitions": True,
            },
            partition_mapping=AllPartitionMapping(),
        ),
    },
    deps=[AssetDep(SILVER_PRICES_1D_KEY)],
    required_resource_keys={"minio_io_manager"},
    group_name="gold",
    key_prefix=["gold"],
)
def gold_prices_1d(
    context,
    ratio_summary: pd.DataFrame,
    reports: pd.DataFrame,
    events: pd.DataFrame,
) -> Output[pd.DataFrame]:

    # =========================================================
    # 0. Base
    # =========================================================
    io = context.resources.minio_io_manager
    asset_key = context.asset_key
    manifest_source = "silver_partition_manifest"

    try:
        silver_manifest = io.load_partition(
            SILVER_PRICES_1D_KEY,
            context.partition_key,
        )
    except FileNotFoundError:
        context.log.warning(
            "Missing silver price manifest. "
            f"partition={context.partition_key}. "
            "Fallback to silver symbol files."
        )
        silver_manifest = manifest_from_silver_symbol_files(io)
        manifest_source = "silver_symbol_files"

    if silver_manifest is None or silver_manifest.empty:
        silver_manifest = manifest_from_silver_symbol_files(io)
        manifest_source = "silver_symbol_files"

    if silver_manifest.empty:
        context.log.warning(
            "No silver price manifest rows or silver symbol files found. "
            f"partition={context.partition_key}"
        )
        return Output(
            empty_gold_price_manifest(),
            metadata={
                "partition": context.partition_key,
                "symbols_processed": 0,
                "symbols_written": 0,
                "manifest_source": manifest_source,
                "price_change_partitions": MetadataValue.json({}),
            },
        )

    skipped_existing_manifest_rows = existing_gold_skip_manifest_rows(
        io,
        silver_manifest,
        context.partition_key,
    )

    prices = load_prices_from_silver_manifest(
        io,
        silver_manifest,
    )
    if prices.empty:
        manifest = pd.DataFrame(skipped_existing_manifest_rows)
        if manifest.empty:
            manifest = empty_gold_price_manifest()
        return Output(
            manifest,
            metadata={
                "partition": context.partition_key,
                "symbols_processed": len(silver_manifest),
                "symbols_written": 0,
                "symbols_skipped_existing": len(skipped_existing_manifest_rows),
                "manifest_source": manifest_source,
                "price_change_partitions": MetadataValue.json({}),
            },
        )

    source_columns = ["_source_action", "_source_reason", "_source_file_path"]
    source_info = prices[["ticker"] + source_columns].drop_duplicates("ticker", keep="last")
    source_info["ticker"] = source_info["ticker"].astype(str).str.strip().str.upper()

    df = prices.copy()
    df = df.drop(columns=source_columns, errors="ignore")
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["date"] = pd.to_datetime(df["date"])

    context.log.info(
        "PRICE GOLD INPUT | "
        f"partition={context.partition_key} | "
        f"source={manifest_source} | "
        f"symbols={source_info['ticker'].nunique()} | "
        f"rows={len(df)}"
    )

    # =========================================================
    # 2. Compute daily shares from Q-2 ratio summary
    # =========================================================
    # year/quarter từ date
    df["year"] = df["date"].dt.year
    df["quarter"] = df["date"].dt.quarter

    # ===== helper: lùi n quý =====
    def shift_back_quarter(year, quarter, n=1):
        q = quarter - n
        y = year.copy()
        while True:
            mask = q <= 0
            if not mask.any():
                break
            q = q.where(~mask, q + 4)
            y = y.where(~mask, y - 1)
        return y, q

    # Q-1 và Q-2
    df["share_base_year"], df["share_base_quarter"] = shift_back_quarter(
        df["year"],
        df["quarter"],
        n=2,
    )
    df["share_base_period_end"] = quarter_end_timestamp(
        df["share_base_year"],
        df["share_base_quarter"],
    )
    df = merge_share_base_from_ratio_summary(df, ratio_summary)

    df = apply_share_dilution_to_daily_metrics(df, events)
    df["number_of_shares_mkt_cap"] = pd.to_numeric(
        df["share_count"],
        errors="coerce",
    ).round(0)

    df = merge_report_metrics_for_prices(df, reports)
    valid_shares = pd.to_numeric(df["share_count"], errors="coerce") > 0
    valid_eps = valid_shares & pd.to_numeric(df["profit_ttm"], errors="coerce").notna()
    valid_bvps = valid_shares & pd.to_numeric(df["equity"], errors="coerce").notna()
    df["eps"] = np.nan
    df["bvps"] = np.nan
    df.loc[valid_eps, "eps"] = (
        pd.to_numeric(df.loc[valid_eps, "profit_ttm"], errors="coerce")
        / pd.to_numeric(df.loc[valid_eps, "share_count"], errors="coerce")
        * 1_000_000_000
    )
    df.loc[valid_bvps, "bvps"] = (
        pd.to_numeric(df.loc[valid_bvps, "equity"], errors="coerce")
        / pd.to_numeric(df.loc[valid_bvps, "share_count"], errors="coerce")
        * 1_000_000_000
    )
    df["pe"] = np.where(
        pd.to_numeric(df["eps"], errors="coerce").ne(0)
        & pd.to_numeric(df["eps"], errors="coerce").notna(),
        pd.to_numeric(df["close"], errors="coerce")
        / pd.to_numeric(df["eps"], errors="coerce")
        * 1_000,
        np.nan,
    )
    df["pb"] = np.where(
        pd.to_numeric(df["bvps"], errors="coerce").ne(0)
        & pd.to_numeric(df["bvps"], errors="coerce").notna(),
        pd.to_numeric(df["close"], errors="coerce")
        / pd.to_numeric(df["bvps"], errors="coerce")
        * 1_000,
        np.nan,
    )

    # cleanup
    df = df.drop(columns=[
        "year", "quarter",
        "share_base_year", "share_base_quarter", "share_base_period_end",
        "share_source_year", "share_source_quarter", "share_source_date_fetched",
        "profit_ttm", "equity",
    ])

    # =========================================================
    # 3. Stock market cap
    # =========================================================
    is_stock = ~df["ticker"].isin(INDEX_TICKERS)

    df.loc[is_stock, "market_cap"] = (
        df.loc[is_stock, "close"] * df.loc[is_stock, "share_count"] / 1_000_000
    )
    # =========================================================
    # 5. Cleanup + rounding
    # =========================================================
    df = df.drop(
        columns=[
            "share_count",
            'pe_index', 'pb_index',
            'cap_group', 'trading_floor',
        ],
        errors="ignore",
    )
    # =========================================================
    # 6. PRICE CHANGE (%), WITH SYMBOL HISTORY FALLBACK
    # =========================================================
    existing_gold_by_ticker = {}
    for ticker in sorted(df["ticker"].dropna().astype(str).str.upper().unique()):
        try:
            existing_df = io.load_asset_file(asset_key, symbol_file_name(ticker))
            existing_df = existing_df.copy()
            existing_df["date"] = pd.to_datetime(existing_df["date"], errors="coerce")
            existing_df = existing_df.drop(
                columns=["cap_group", "trading_floor"],
                errors="ignore",
            )
        except FileNotFoundError:
            existing_df = pd.DataFrame()
        existing_gold_by_ticker[ticker] = existing_df

    close_history = build_close_history(existing_gold_by_ticker, df)
    used_partitions = {}
    change_frames = []

    for price_date, day_df in df.groupby("date"):
        price_date_key = price_date.strftime("%Y-%m-%d")
        df_today = day_df[["ticker", "close"]].set_index("ticker")
        used_partitions[price_date_key] = {}

        for col, days in OFFSETS.items():
            target_date = (
                pd.to_datetime(price_date_key) - pd.Timedelta(days=days)
            ).strftime("%Y-%m-%d")

            df_past, used_date = nearest_close_by_ticker(
                close_history=close_history,
                target_date=target_date,
                max_lookback=10,
            )

            used_partitions[price_date_key][col] = used_date

            if df_past is None:
                df_today[col] = None
                continue

            df_past = df_past[["ticker", "close"]].set_index("ticker")
            df_today[col] = calc_pct_change(df_today, df_past)

        change_df = df_today.reset_index()[["ticker"] + list(OFFSETS.keys())]
        change_df["date"] = price_date
        change_frames.append(change_df)

    if change_frames:
        change_df = pd.concat(change_frames, ignore_index=True)
        df = df.merge(
            change_df,
            on=["date", "ticker"],
            how="left",
        )
    else:
        for col in OFFSETS:
            df[col] = None

    EXCLUDE_COLS = {"volume"}
    num_cols = df.select_dtypes(include=[np.number]).columns
    round_cols = [c for c in num_cols if c not in EXCLUDE_COLS]
    df[round_cols] = df[round_cols].round(2)

    source_by_ticker = source_info.set_index("ticker").to_dict("index")
    manifest_rows = []
    symbols_written = 0

    for ticker, output_df in df.groupby("ticker"):
        ticker = str(ticker).strip().upper()
        file_path = symbol_file_name(ticker)
        source = source_by_ticker.get(ticker, {})
        action = source.get("_source_action") or "overwrite"
        reason = source.get("_source_reason") or "silver_update"
        source_file_path = source.get("_source_file_path")
        existing_df = existing_gold_by_ticker.get(ticker, pd.DataFrame())

        output_df = output_df.sort_values("date").reset_index(drop=True)
        if action == "append" and not existing_df.empty:
            stored_df = pd.concat([existing_df, output_df], ignore_index=True)
            stored_df["date"] = pd.to_datetime(stored_df["date"], errors="coerce")
            stored_df = stored_df.drop_duplicates(
                subset=["ticker", "date"],
                keep="last",
            ).sort_values(["ticker", "date"])
        else:
            if action == "append" and existing_df.empty:
                action = "overwrite"
                reason = f"{reason}|missing_existing_gold_symbol"
            stored_df = output_df.copy()

        io.write_asset_file(asset_key, file_path, stored_df)
        symbols_written += 1
        context.log.info(
            "PRICE GOLD WRITE | "
            f"ticker={ticker} | action={action} | reason={reason} | "
            f"file={file_path} | rows_output={len(output_df)} | "
            f"rows_stored={len(stored_df)}"
        )

        manifest_rows.append(
            {
                "ticker": ticker,
                "partition_date": context.partition_key,
                "action": action,
                "reason": reason,
                "source_file_path": source_file_path,
                "output_start_date": output_df["date"].min().strftime("%Y-%m-%d"),
                "output_end_date": output_df["date"].max().strftime("%Y-%m-%d"),
                "rows_output": len(output_df),
                "rows_stored": len(stored_df),
                "history_hash": dataframe_history_hash(stored_df),
                "file_path": file_path,
            }
        )

    manifest_rows.extend(skipped_existing_manifest_rows)
    manifest = pd.DataFrame(manifest_rows)
    if manifest.empty:
        manifest = empty_gold_price_manifest()

    return Output(
        manifest,
        metadata={
            "partition": context.partition_key,
            "symbols_processed": len(silver_manifest),
            "symbols_written": symbols_written,
            "symbols_skipped_existing": len(skipped_existing_manifest_rows),
            "rows_output": len(df),
            "manifest_source": manifest_source,
            "price_change_partitions": MetadataValue.json(used_partitions),
        },
    )


@asset(
    partitions_def=daily,
    ins={
        "gold_prices_1d": AssetIn(
            key_prefix=["gold"]
        )
    },
    io_manager_key="psql_io_manager",
    required_resource_keys={"minio_io_manager"},
    key_prefix=["warehouse"],
    compute_kind="python",
    group_name="warehouse",
)
def warehouse_prices_1d (
    context,
    gold_prices_1d: pd.DataFrame,
) -> Output[pd.DataFrame]:
    df = load_all_gold_price_symbol_files(
        context.resources.minio_io_manager,
        context=context,
    )
    actions = set()
    if gold_prices_1d is not None and not gold_prices_1d.empty and "action" in gold_prices_1d.columns:
        actions = set(
            gold_prices_1d["action"]
            .dropna()
            .astype(str)
            .str.lower()
            .unique()
        )
    metadata = {
        "table": "warehouse.warehouse_prices_1d",
        "rows_loaded": len(df),
        "replace_table": True,
        "manifest_actions": sorted(actions),
        "load_mode": "replace_table_from_all_gold_symbol_files",
    }
    context.log.info(
        "WAREHOUSE PRICES WRITE PREPARED | "
        "mode=replace_table | "
        f"rows={len(df)} | "
        f"symbols={df['ticker'].nunique() if 'ticker' in df.columns else None}"
    )

    return Output(
        df,
        metadata=metadata,
    )
