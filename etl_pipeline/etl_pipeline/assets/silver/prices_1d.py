import pandas as pd
from dagster import AssetKey, Output, asset

from etl_pipeline.assets.bronze.prices import (
    PRICE_COLUMNS,
    price_history_hash,
    symbol_file_name,
)
from etl_pipeline.assets.partitions import price_1d_daily


daily = price_1d_daily
BRONZE_PRICES_1D_KEY = AssetKey(["bronze", "prices", "bronze_prices_1d"])
SILVER_EVENTS_KEY = AssetKey(["silver", "company_info", "silver_events"])
PRICE_ADJUSTMENT_EVENT_TYPE_IDS = {1, 3, 4}


def empty_price_manifest() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "partition_date",
            "action",
            "reason",
            "previous_source_max_date",
            "source_min_date",
            "source_max_date",
            "output_start_date",
            "output_end_date",
            "rows_output",
            "rows_stored",
            "history_hash",
            "file_path",
            "overwrite_events",
        ]
    )


def ticker_from_symbol_file(file_path: str) -> str:
    return file_path.replace("\\", "/").split("/")[-1].replace(".parquet", "").upper()


def manifest_from_bronze_symbol_files(io) -> pd.DataFrame:
    files = [
        file_path
        for file_path in io.list_asset_files(BRONZE_PRICES_1D_KEY)
        if file_path.lower().endswith(".parquet")
    ]
    return pd.DataFrame(
        [
            {
                "ticker": ticker_from_symbol_file(file_path),
                "file_path": file_path,
            }
            for file_path in files
        ],
        columns=["ticker", "file_path"],
    )


def normalize_silver_prices(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)

    df = df.copy()
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

    for column in PRICE_COLUMNS:
        if column not in df.columns:
            df[column] = None

    df = df[df["ticker"].ne("") & df["date"].notna()].copy()
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    return df[PRICE_COLUMNS].sort_values(["ticker", "date"]).reset_index(drop=True)


def load_silver_events(io) -> pd.DataFrame:
    frames = []
    for partition_key in io.list_partitions(SILVER_EVENTS_KEY):
        try:
            frames.append(io.load_partition(SILVER_EVENTS_KEY, partition_key))
        except FileNotFoundError:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def crossed_exright_events(
    *,
    events: pd.DataFrame,
    ticker: str,
    previous_max_date,
    bronze_max_date,
) -> pd.DataFrame:
    columns = ["event_type_id", "exright_date", "event_title"]
    required = {"ticker", "event_type_id", "exright_date"}
    if events.empty or previous_max_date is None or not required.issubset(events.columns):
        return pd.DataFrame(columns=columns)

    df = events.copy()
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["event_type_id"] = pd.to_numeric(df["event_type_id"], errors="coerce").astype("Int64")
    df["exright_date"] = pd.to_datetime(df["exright_date"], errors="coerce").dt.date
    if "event_title" not in df.columns:
        df["event_title"] = None

    df = df[
        (df["ticker"] == ticker)
        & df["event_type_id"].isin(PRICE_ADJUSTMENT_EVENT_TYPE_IDS)
        & df["exright_date"].notna()
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)

    crossed = df[
        (df["exright_date"] > previous_max_date)
        & (df["exright_date"] <= bronze_max_date)
    ].copy()
    return crossed[columns].sort_values("exright_date")


def format_exright_events(events: pd.DataFrame) -> str:
    if events.empty:
        return ""

    parts = []
    for row in events.itertuples(index=False):
        exright_date = row.exright_date.strftime("%Y-%m-%d")
        title = row.event_title if pd.notna(row.event_title) else "no title"
        parts.append(f"{exright_date} - {title}")
    return "; ".join(parts)


def unchanged_existing_history(
    *,
    existing_df: pd.DataFrame,
    bronze_df: pd.DataFrame,
    previous_max_date,
) -> bool:
    if existing_df.empty or previous_max_date is None:
        return False

    bronze_overlap = bronze_df[bronze_df["date"] <= previous_max_date].copy()
    return price_history_hash(bronze_overlap) == price_history_hash(existing_df)


@asset(
    partitions_def=daily,
    io_manager_key="minio_io_manager",
    required_resource_keys={"minio_io_manager"},
    group_name="silver",
    key_prefix=["silver"],
)
def silver_prices_1d(context) -> Output[pd.DataFrame]:
    io = context.resources.minio_io_manager
    asset_key = context.asset_key
    manifest_source = "bronze_partition_manifest"

    try:
        bronze_manifest = io.load_partition(
            BRONZE_PRICES_1D_KEY,
            context.partition_key,
        )
    except FileNotFoundError:
        context.log.warning(
            "Missing bronze price manifest. "
            f"partition={context.partition_key}. "
            "Fallback to bronze symbol files."
        )
        bronze_manifest = manifest_from_bronze_symbol_files(io)
        manifest_source = "bronze_symbol_files"

    if bronze_manifest is None or bronze_manifest.empty:
        bronze_manifest = manifest_from_bronze_symbol_files(io)
        manifest_source = "bronze_symbol_files"

    if bronze_manifest.empty:
        context.log.warning(
            "No bronze price manifest rows or bronze symbol files found. "
            f"partition={context.partition_key}"
        )
        return Output(
            empty_price_manifest(),
            metadata={
                "partition": context.partition_key,
                "symbols_processed": 0,
                "symbols_written": 0,
                "manifest_source": manifest_source,
            },
        )

    context.log.info(
        "PRICE SILVER INPUT | "
        f"partition={context.partition_key} | "
        f"source={manifest_source} | "
        f"symbols={len(bronze_manifest)}"
    )

    events = load_silver_events(io)
    manifest_rows = []
    symbols_written = 0
    rows_output = 0

    for row in bronze_manifest.itertuples(index=False):
        ticker = str(row.ticker).strip().upper()
        file_path = getattr(row, "file_path", symbol_file_name(ticker))
        bronze_df = normalize_silver_prices(
            io.load_asset_file(BRONZE_PRICES_1D_KEY, file_path)
        )
        if bronze_df.empty:
            continue

        bronze_min_date = bronze_df["date"].min()
        bronze_max_date = bronze_df["date"].max()
        silver_file_path = symbol_file_name(ticker)

        try:
            existing_df = normalize_silver_prices(
                io.load_asset_file(asset_key, silver_file_path)
            )
        except FileNotFoundError:
            existing_df = pd.DataFrame(columns=PRICE_COLUMNS)

        previous_max_date = None
        if not existing_df.empty:
            previous_max_date = existing_df["date"].max()

        exright_events = crossed_exright_events(
            events=events,
            ticker=ticker,
            previous_max_date=previous_max_date,
            bronze_max_date=bronze_max_date,
        )
        exright_event_details = format_exright_events(exright_events)

        if existing_df.empty:
            action = "overwrite"
            reason = "first_load"
            stored_df = bronze_df
            output_df = bronze_df
        elif not exright_events.empty:
            action = "overwrite"
            reason = "crossed_exright_date"
            stored_df = bronze_df
            output_df = bronze_df
        elif not unchanged_existing_history(
            existing_df=existing_df,
            bronze_df=bronze_df,
            previous_max_date=previous_max_date,
        ):
            action = "overwrite"
            reason = "history_changed"
            stored_df = bronze_df
            output_df = bronze_df
        elif bronze_max_date > previous_max_date:
            action = "append"
            reason = "new_dates"
            output_df = bronze_df[bronze_df["date"] > previous_max_date].copy()
            stored_df = pd.concat([existing_df, output_df], ignore_index=True)
            stored_df = stored_df.drop_duplicates(
                subset=["ticker", "date"],
                keep="last",
            ).sort_values(["ticker", "date"])
        else:
            action = "skip"
            reason = "up_to_date"
            stored_df = existing_df
            output_df = pd.DataFrame(columns=PRICE_COLUMNS)

        if action != "skip":
            if reason == "crossed_exright_date":
                log_message = (
                    "PRICE SILVER OVERWRITE | "
                    f"ticker={ticker} | reason={reason} | "
                    f"previous_max_date={previous_max_date.strftime('%Y-%m-%d')} | "
                    f"bronze_max_date={bronze_max_date.strftime('%Y-%m-%d')} | "
                    f"events=[{exright_event_details}]"
                )
            elif action == "overwrite":
                log_message = (
                    "PRICE SILVER OVERWRITE | "
                    f"ticker={ticker} | reason={reason} | "
                    f"previous_max_date="
                    f"{previous_max_date.strftime('%Y-%m-%d') if previous_max_date is not None else None} | "
                    f"bronze_max_date={bronze_max_date.strftime('%Y-%m-%d')}"
                )
            else:
                log_message = (
                    "PRICE SILVER APPEND | "
                    f"ticker={ticker} | reason={reason} | "
                    f"previous_max_date={previous_max_date.strftime('%Y-%m-%d')} | "
                    f"bronze_max_date={bronze_max_date.strftime('%Y-%m-%d')} | "
                    f"rows_appended={len(output_df)}"
                )
            context.log.info(log_message)
            io.write_asset_file(asset_key, silver_file_path, stored_df)
            symbols_written += 1

        rows_output += len(output_df)
        manifest_rows.append(
            {
                "ticker": ticker,
                "partition_date": context.partition_key,
                "action": action,
                "reason": reason,
                "previous_source_max_date": (
                    previous_max_date.strftime("%Y-%m-%d")
                    if previous_max_date is not None
                    else None
                ),
                "source_min_date": bronze_min_date.strftime("%Y-%m-%d"),
                "source_max_date": bronze_max_date.strftime("%Y-%m-%d"),
                "output_start_date": (
                    output_df["date"].min().strftime("%Y-%m-%d")
                    if not output_df.empty
                    else None
                ),
                "output_end_date": (
                    output_df["date"].max().strftime("%Y-%m-%d")
                    if not output_df.empty
                    else None
                ),
                "rows_output": len(output_df),
                "rows_stored": len(stored_df),
                "history_hash": price_history_hash(stored_df),
                "file_path": silver_file_path,
                "overwrite_events": exright_event_details if action == "overwrite" else None,
            }
        )

    manifest = pd.DataFrame(manifest_rows)
    if manifest.empty:
        manifest = empty_price_manifest()

    overwrite_manifest = manifest[manifest["action"] == "overwrite"].copy()
    if overwrite_manifest.empty:
        context.log.info(
            "PRICE SILVER OVERWRITE SUMMARY | "
            f"partition={context.partition_key} | count=0"
        )
    else:
        summary_parts = []
        for row in overwrite_manifest.itertuples(index=False):
            detail = getattr(row, "overwrite_events", None)
            if detail:
                summary_parts.append(f"{row.ticker}({row.reason}: {detail})")
            else:
                summary_parts.append(f"{row.ticker}({row.reason})")
        context.log.info(
            "PRICE SILVER OVERWRITE SUMMARY | "
            f"partition={context.partition_key} | "
            f"count={len(overwrite_manifest)} | "
            f"tickers=[{'; '.join(summary_parts)}]"
        )

    return Output(
        manifest,
        metadata={
            "partition": context.partition_key,
            "symbols_processed": len(bronze_manifest),
            "symbols_written": symbols_written,
            "manifest_source": manifest_source,
            "rows_output": rows_output,
            "overwrites": int((manifest["action"] == "overwrite").sum())
            if not manifest.empty
            else 0,
            "appends": int((manifest["action"] == "append").sum())
            if not manifest.empty
            else 0,
            "skips": int((manifest["action"] == "skip").sum())
            if not manifest.empty
            else 0,
        },
    )
