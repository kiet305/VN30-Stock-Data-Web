import pandas as pd
from dagster import Output, asset

from etl_pipeline.assets.bronze.reports import bronze_report_refresh_partitions, quarters
from etl_pipeline.ops.api.company_info import get_company_information, get_stock_list


def partition_to_year_quarter(partition_key: str) -> tuple[int, int]:
    year, quarter = partition_key.split("-Q", 1)
    return int(year), int(quarter)


def filter_partition(df: pd.DataFrame, partition_key: str) -> pd.DataFrame:
    if df.empty or "year" not in df.columns or "quarter" not in df.columns:
        return df

    year, quarter = partition_to_year_quarter(partition_key)
    years = pd.to_numeric(df["year"], errors="coerce")
    quarters = pd.to_numeric(df["quarter"], errors="coerce")
    return df[(years == year) & (quarters == quarter)].copy()


def write_ticker_metric_partitions(
    *,
    io,
    asset_key,
    df: pd.DataFrame,
) -> tuple[int, int]:
    if df.empty or "year" not in df.columns or "quarter" not in df.columns:
        return 0, 0

    valid_partitions = set(quarters)
    years = pd.to_numeric(df["year"], errors="coerce")
    quarter_values = pd.to_numeric(df["quarter"], errors="coerce")
    df = df[years.notna() & quarter_values.notna()].copy()
    if df.empty:
        return 0, 0

    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype(int)
    df["quarter"] = pd.to_numeric(df["quarter"], errors="coerce").astype(int)

    partitions_written = 0
    rows_written = 0
    for (year, quarter), df_part in df.groupby(["year", "quarter"]):
        partition_key = f"{int(year)}-Q{int(quarter)}"
        if partition_key not in valid_partitions:
            continue

        io.write_partition(asset_key, partition_key, df_part)
        partitions_written += 1
        rows_written += len(df_part)

    return partitions_written, rows_written


@asset(
    partitions_def=bronze_report_refresh_partitions,
    io_manager_key="minio_io_manager",
    key_prefix=["bronze"],
    compute_kind="python",
    group_name="bronze",
)
def bronze_ticker_metric(context) -> Output[pd.DataFrame]:
    io = context.resources.minio_io_manager
    asset_key = context.asset_key

    records = get_company_information(
        context,
        tickers=get_stock_list(),
        type="ratio_summary",
    )
    partitions_written, rows_written = write_ticker_metric_partitions(
        io=io,
        asset_key=asset_key,
        df=records,
    )
    partition_df = filter_partition(records, context.partition_key)

    return Output(
        partition_df,
        metadata={
            "source": "vnstock.Company.ratio_summary",
            "partition": context.partition_key,
            "source_records": len(records),
            "num_records": len(partition_df),
            "partitions_written": partitions_written,
            "rows_written": rows_written,
        },
    )
