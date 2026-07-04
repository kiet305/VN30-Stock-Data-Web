import pandas as pd
import hashlib
from etl_pipeline.ops.api.prices import get_prices, get_stock_list
from etl_pipeline.assets.partitions import (
    PRICE_1D_HISTORY_START_DATE,
    PRICE_1D_LAST_DATE,
    bronze_price_1d_refresh_partitions,
)
from etl_pipeline.ops.tickers import HOSE_INDEX_TICKERS
from dagster import asset, Output
from datetime import date, timedelta, timezone, datetime

VN_TZ = timezone(timedelta(hours=7))
daily = bronze_price_1d_refresh_partitions


def _symbols_from_prices(df: pd.DataFrame) -> set[str]:
    if df.empty or "ticker" not in df.columns:
        return set()
    return set(df["ticker"].dropna().unique())


def detect_inactive_symbols(
    *,
    io,
    asset_key,
    all_tickers: set[str],
    lookback=10,
) -> set[str]:
    existing_partitions = sorted(io.list_partitions(asset_key))
    if len(existing_partitions) < lookback:
        # chưa đủ dữ liệu → coi như tất cả active
        return set()

    recent_partitions = existing_partitions[-lookback:]

    active = set()
    for p in recent_partitions:
        df = io.load_partition(asset_key, p)
        # union các mã có ít nhất 1 phiên khớp lệnh trong 10 phiên gần nhất  
        active |= _symbols_from_prices(df)

    inactive = all_tickers - active
    return inactive

INDEX_TICKERS = HOSE_INDEX_TICKERS

FULL_LOAD_START_DATE = PRICE_1D_HISTORY_START_DATE
WAREHOUSE_SCHEMA = "warehouse"
WAREHOUSE_TABLE = "warehouse_prices_1d"
RECENT_GAP_LOOKBACK_DAYS = 30

PRICE_COLUMNS = [
    "ticker",
    "date",
    "high",
    "low",
    "open",
    "close",
    "volume",
    "date_fetched",
]

HASH_COLUMNS = ["ticker", "date", "high", "low", "open", "close", "volume"]


def symbol_file_name(ticker: str) -> str:
    symbol = str(ticker).strip().upper().replace("/", "_").replace("\\", "_")
    return f"{symbol}.parquet"


def price_history_hash(df: pd.DataFrame) -> str:
    if df.empty:
        return ""

    hash_df = df.copy()
    for col in HASH_COLUMNS:
        if col not in hash_df.columns:
            hash_df[col] = None

    hash_df = hash_df[HASH_COLUMNS].copy()
    hash_df["date"] = pd.to_datetime(hash_df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    hash_df = hash_df.sort_values(["ticker", "date"]).reset_index(drop=True)
    row_hashes = pd.util.hash_pandas_object(hash_df, index=False).values.tobytes()
    return hashlib.sha256(row_hashes).hexdigest()


def build_symbol_manifest_rows(
    *,
    io,
    asset_key,
    df: pd.DataFrame,
    partition_key: str,
    updated_at: str,
) -> list[dict]:
    rows = []
    if df.empty:
        return rows

    df = df.copy()
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df[df["ticker"].ne("") & df["date"].notna()].copy()

    for ticker, symbol_df in df.groupby("ticker"):
        symbol_df = symbol_df.sort_values("date").reset_index(drop=True)
        file_name = symbol_file_name(ticker)
        io.write_asset_file(asset_key, file_name, symbol_df)

        rows.append(
            {
                "ticker": ticker,
                "partition_date": partition_key,
                "updated_at": updated_at,
                "source_min_date": symbol_df["date"].min().strftime("%Y-%m-%d"),
                "source_max_date": symbol_df["date"].max().strftime("%Y-%m-%d"),
                "rows": len(symbol_df),
                "history_hash": price_history_hash(symbol_df),
                "file_path": file_name,
            }
        )

    return rows

def build_tickers(*, all_tickers: set[str], inactive: set[str] | None = None) -> list[str]:
    inactive = inactive or set()

    # cổ phiếu thường (active)
    stocks = sorted(
        t for t in all_tickers
        if t not in INDEX_TICKERS and t not in inactive
    )

    # chỉ số (luôn ở cuối)
    indices = sorted(
        t for t in all_tickers
        if t in INDEX_TICKERS
    )

    return stocks + indices


def today_vn() -> date:
    return datetime.now(VN_TZ).date()


def empty_prices_df() -> pd.DataFrame:
    return pd.DataFrame(columns=PRICE_COLUMNS)


def is_weekday(d: date) -> bool:
    return d.weekday() < 5


def business_dates_between(start_date: date, end_date: date) -> list[date]:
    if start_date > end_date:
        return []

    days = pd.date_range(start=start_date, end=end_date, freq="D")
    return [day.date() for day in days if is_weekday(day.date())]


def missing_business_dates(
    *,
    existing_partitions: set[str],
    start_date: date,
    end_date: date,
) -> list[date]:
    return [
        d for d in business_dates_between(start_date, end_date)
        if d.strftime("%Y-%m-%d") not in existing_partitions
    ]


def normalize_price_dates(df: pd.DataFrame, *, start_date: date, end_date: date) -> pd.DataFrame:
    if df.empty:
        return empty_prices_df()

    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    df = df[
        (df["time"].dt.date >= start_date)
        & (df["time"].dt.date <= end_date)
    ]
    df = df.rename(columns={"time": "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.date

    for col in PRICE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[PRICE_COLUMNS]


def write_daily_price_partitions(
    *,
    io,
    asset_key,
    df: pd.DataFrame,
    dates: list[date],
    skip_partition_key: str | None = None,
) -> int:
    rows_written = 0
    if df.empty:
        df_by_date = {}
    else:
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df_by_date = {d: df_d for d, df_d in df.groupby("date")}

    for d in dates:
        partition_key = d.strftime("%Y-%m-%d")
        if partition_key == skip_partition_key:
            continue

        df_part = df_by_date.get(d, empty_prices_df())
        io.write_partition(asset_key, partition_key, df_part)
        rows_written += len(df_part)

    return rows_written

@asset(
    key_prefix=["bronze", "prices"],
    partitions_def=daily,
    io_manager_key="minio_io_manager",
    group_name="bronze",
    required_resource_keys={"minio_io_manager", "psql_io_manager"},
)
def _legacy_bronze_prices_1d(context):
    dates = context.partition_key

    io = context.resources.minio_io_manager
    asset_key = context.asset_key
    existing_partitions = io.list_partitions(asset_key)

    all_tickers = set(get_stock_list())
    all_tickers |= INDEX_TICKERS

    # Full load mode (lần chạy đầu tiên)
    if not existing_partitions:
        context.log.info("FULL LOAD MODE")

        df = get_prices(
            context=context,
            interval='1d',
            tickers=build_tickers(all_tickers=all_tickers),
            start_date=PRICE_1D_HISTORY_START_DATE.isoformat(),
            end_date=PRICE_1D_LAST_DATE.isoformat(),
        )

        df["time"] = pd.to_datetime(df["time"])
        df = df[df["time"] >= pd.Timestamp(PRICE_1D_HISTORY_START_DATE)]
        df = df.rename(columns={
            'time': 'date'
        })

        # ghi toàn bộ lịch sử thành parquet partitions
        for t, df_part in df.groupby("date"):
            p = t.strftime("%Y-%m-%d")
            io.write_partition(asset_key, p, df_part)

        # partition hiện tại không cần ghi thêm
        context.log.info("Full load done, skip partition materialization")
        context.log.info(
            "Full load done, skip partition materialization\n"
            f"Tickers={len(all_tickers)}\n"
            f"Rows={len(df)}\n"
            f"Partitions_written="
            f"{df[['date']].drop_duplicates().shape[0]}"
        )

        return

    # Incremental mode
    context.log.info("INCREMENTAL MODE")
    d = datetime.strptime(dates, "%Y-%m-%d").date()
    if d.weekday() >= 5:
        context.log.info(f"No data for weekends: {dates}")
        return

    inactive = detect_inactive_symbols(
        io=io,
        asset_key=asset_key,
        all_tickers=all_tickers,
        lookback=10,
    )

    context.log.info(f"Tickers inactive: {len(inactive)}")
    context.log.info(f"Partition_key: {context.partition_key}")

    try:
        df_existing = io.load_partition(asset_key, context.partition_key)
        context.log.info(f"Data updated for {dates}. Stop materializing")
        return
    except FileNotFoundError:
        df_existing = pd.DataFrame()
        tickers = build_tickers(
            all_tickers=all_tickers,
            inactive=inactive,
        )

    context.log.info(f"Tickers to be crawled: {len(tickers)}")
                     
    df = get_prices(
        context=context,
        interval='1d',
        tickers=tickers,
        start_date=dates,
        end_date=dates,
    )
    df["time"] = df["time"].dt.strftime("%Y-%m-%d")

    df_part = df[
        (df["time"] == dates)
    ]
    df_part = df_part.rename(columns={
        'time': 'date',
    })

    return Output(
        df_part,
        metadata={
            "mode": "incremental",
            "date": dates,
            "tickers_crawled": len(tickers),
            "rows": len(df_part),
            "api_called": True,
        },
    )


@asset(
    key_prefix=["bronze", "prices"],
    partitions_def=daily,
    io_manager_key="minio_io_manager",
    group_name="bronze",
    required_resource_keys={"minio_io_manager", "psql_io_manager"},
)
def bronze_prices_1d(context):
    io = context.resources.minio_io_manager
    asset_key = context.asset_key

    target_date = datetime.strptime(context.partition_key, "%Y-%m-%d").date()
    end_date = min(target_date, today_vn(), PRICE_1D_LAST_DATE)

    all_tickers = set(get_stock_list())
    all_tickers |= INDEX_TICKERS
    tickers = build_tickers(all_tickers=all_tickers)

    context.log.info("FULL HISTORY REFRESH MODE")
    context.log.info(f"Partition_key: {context.partition_key}")
    context.log.info(f"Tickers to be crawled: {len(tickers)}")

    df = get_prices(
        context=context,
        interval="1d",
        tickers=tickers,
        start_date=FULL_LOAD_START_DATE.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
    )
    df = normalize_price_dates(df, start_date=FULL_LOAD_START_DATE, end_date=end_date)
    updated_at = datetime.now(VN_TZ).isoformat()
    manifest_rows = build_symbol_manifest_rows(
        io=io,
        asset_key=asset_key,
        df=df,
        partition_key=context.partition_key,
        updated_at=updated_at,
    )
    manifest = pd.DataFrame(
        manifest_rows,
        columns=[
            "ticker",
            "partition_date",
            "updated_at",
            "source_min_date",
            "source_max_date",
            "rows",
            "history_hash",
            "file_path",
        ],
    )

    return Output(
        manifest,
        metadata={
            "mode": "full_history_refresh",
            "partition": context.partition_key,
            "scan_end_date": end_date.strftime("%Y-%m-%d"),
            "fetch_start_date": FULL_LOAD_START_DATE.strftime("%Y-%m-%d"),
            "fetch_end_date": end_date.strftime("%Y-%m-%d"),
            "tickers_crawled": len(tickers),
            "symbols_written": len(manifest),
            "rows": len(df),
            "api_called": True,
        },
    )
