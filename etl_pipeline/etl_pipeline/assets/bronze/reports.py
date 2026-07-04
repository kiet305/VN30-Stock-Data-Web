import pandas as pd
from etl_pipeline.ops.api.reports import get_report, get_stock_list
from etl_pipeline.assets.partitions import PIPELINE_ANCHOR_DATE
from dagster import asset, StaticPartitionsDefinition, Output
from datetime import date


def previous_completed_quarter(as_of: date) -> tuple[int, int]:
    end_year = as_of.year
    end_quarter = (as_of.month - 1) // 3
    if end_quarter == 0:
        end_quarter = 4
        end_year -= 1
    return end_year, end_quarter


def get_quarters(
    start: str = "2020-Q1",
    current: str | None = None,
    as_of: date | None = None,
):
    if current is None:
        end_year, end_quarter = previous_completed_quarter(
            as_of or PIPELINE_ANCHOR_DATE
        )
    else:
        end_year, end_quarter = map(int, current.split("-Q"))

    year, quarter = map(int, start.split("-Q"))
    quarters = []
    while (year, quarter) <= (end_year, end_quarter):
        quarters.append(f"{year}-Q{quarter}")
        quarter += 1
        if quarter == 5:
            quarter = 1
            year += 1

    return quarters

quarters = get_quarters()
report_partitions = StaticPartitionsDefinition(quarters)
bronze_report_refresh_partitions = StaticPartitionsDefinition([quarters[-1]])
REPORT_REFRESH_QUARTERS = 8


def _symbols_from_report(df: pd.DataFrame) -> set[str]:
    if df.empty or "ticker" not in df.columns:
        return set()
    return set(df["ticker"].dropna().unique())

def detect_inactive_symbols(
    *,
    io,
    asset_key,
    all_tickers: set[str],
    lookback=4,
) -> set[str]:
    existing_partitions = sorted(io.list_partitions(asset_key))
    if len(existing_partitions) < lookback:
        # chưa đủ dữ liệu → coi như tất cả active
        return set()

    recent_partitions = existing_partitions[-lookback:]

    active = set()
    for p in recent_partitions:
        df = io.load_partition(asset_key, p)
        # union các mã có ít nhất 1 bctc trong 4 quý gần nhất  
        active |= _symbols_from_report(df)

    inactive = all_tickers - active
    return inactive

REPORT_NAME_MAP = {
    "is": "income_statement",
    "bs": "balance_sheet",
    "cf": "cash_flow",
}


def _first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str:
    for col in candidates:
        if col in df.columns:
            return col
    raise KeyError(f"Missing expected columns: {candidates}")


def _year_column(df: pd.DataFrame) -> str:
    return _first_existing_column(df, ["year"])


def _quarter_column(df: pd.DataFrame) -> str:
    return _first_existing_column(df, ["quarter"])

def _recent_report_partitions(n: int = REPORT_REFRESH_QUARTERS) -> list[str]:
    return quarters[-n:]


def _write_report_partitions(
    *,
    io,
    asset_key,
    df: pd.DataFrame,
) -> tuple[int, int]:
    year_col = _year_column(df)
    quarter_col = _quarter_column(df)

    partitions_written = 0
    rows_written = 0
    valid_partitions = set(quarters)

    for (y, q), df_part in df.groupby([year_col, quarter_col]):
        partition_key = f"{int(y)}-Q{int(q)}"
        if partition_key not in valid_partitions:
            continue

        io.write_partition(asset_key, partition_key, df_part)
        partitions_written += 1
        rows_written += len(df_part)

    return partitions_written, rows_written


def bronze_reports(report_type: str):
    asset_suffix = REPORT_NAME_MAP[report_type]
    asset_name = f"bronze_{asset_suffix}"

    @asset(
        name=asset_name,
        key_prefix=["bronze", "reports"],
        partitions_def=bronze_report_refresh_partitions,
        io_manager_key="minio_io_manager",
        group_name="bronze",
    )
    def _asset(context):
        io = context.resources.minio_io_manager
        asset_key = context.asset_key

        existing_partitions = set(io.list_partitions(asset_key))
        refresh_partitions = _recent_report_partitions()

        all_tickers = set(get_stock_list())
        if not all_tickers:
            raise ValueError(
                "Stock universe is empty. Check Listing exchange mapping "
                "or vnstock Listing API response."
            )

        mode = "full_load" if not existing_partitions else "rolling_refresh"
        context.log.info(f"{mode.upper()} MODE")
        context.log.info(
            "Report refresh window: "
            f"{refresh_partitions[0]} -> {refresh_partitions[-1]}"
        )
        if context.partition_key != refresh_partitions[-1]:
            context.log.warning(
                "bronze_reports is a rolling refresh asset. "
                f"Triggered partition={context.partition_key}, "
                f"latest_refresh_partition={refresh_partitions[-1]}"
            )

        inactive = detect_inactive_symbols(
            io=io,
            asset_key=asset_key,
            all_tickers=all_tickers,
            lookback=4,
        )
        tickers = sorted(all_tickers - inactive)

        context.log.info(f"Tickers inactive: {len(inactive)}")
        context.log.info(f"Tickers to be crawled: {len(tickers)}")

        if not tickers:
            context.log.info("No symbols to crawl")
            return Output(
                None,
                metadata={
                    "mode": mode,
                    "partition": context.partition_key,
                    "refresh_partitions": refresh_partitions,
                    "tickers_crawled": 0,
                    "partitions_written": 0,
                    "rows": 0,
                    "api_called": False,
                },
            )

        df = get_report(
            context=context,
            report_type=report_type,
            tickers=tickers,
        )

        if df.empty:
            context.log.warning("No report data fetched")
            return Output(
                None,
                metadata={
                    "mode": mode,
                    "partition": context.partition_key,
                    "refresh_partitions": refresh_partitions,
                    "tickers_crawled": len(tickers),
                    "partitions_written": 0,
                    "rows": 0,
                    "api_called": True,
                },
            )

        year_col = _year_column(df)
        quarter_col = _quarter_column(df)
        period_labels = (
            df[year_col].astype(int).astype(str)
            + "-Q"
            + df[quarter_col].astype(int).astype(str)
        )
        df = df[period_labels.isin(refresh_partitions)].copy()

        partitions_written, rows_written = _write_report_partitions(
            io=io,
            asset_key=asset_key,
            df=df,
        )

        return Output(
            None,
            metadata={
                "mode": mode,
                "partition": context.partition_key,
                "refresh_partitions": refresh_partitions,
                "tickers_crawled": len(tickers),
                "partitions_written": partitions_written,
                "rows": len(df),
                "rows_written": rows_written,
                "api_called": True,
            },
        )

    return _asset
