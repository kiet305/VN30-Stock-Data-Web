import pandas as pd
from dagster import AllPartitionMapping, AssetDep, AssetKey, Output, asset

from etl_pipeline.assets.bronze.reports import report_partitions
from etl_pipeline.assets.bronze.ticker_metric import filter_partition
from etl_pipeline.ops.normalize.company_info import normalize_info
from etl_pipeline.ops.tickers import get_stock_symbols

BRONZE_TICKER_METRIC_KEY = AssetKey(["bronze", "bronze_ticker_metric"])


@asset(
    partitions_def=report_partitions,
    io_manager_key="minio_io_manager",
    deps=[
        AssetDep(
            BRONZE_TICKER_METRIC_KEY,
            partition_mapping=AllPartitionMapping(),
        )
    ],
    required_resource_keys={"minio_io_manager"},
    key_prefix=["silver"],
    compute_kind="python",
    group_name="silver",
)
def silver_ticker_metric(context) -> Output[pd.DataFrame]:
    ticker_metric = context.resources.minio_io_manager.load_partition(
        BRONZE_TICKER_METRIC_KEY,
        context.partition_key,
    )
    df = normalize_info(ticker_metric, info_type="ratio_summary")
    df = filter_partition(df, context.partition_key)

    if "ticker" in df.columns:
        hose_tickers = set(get_stock_symbols())
        df = df[df["ticker"].isin(hose_tickers)].copy()

    return Output(
        df,
        metadata={
            "source": "bronze_ticker_metric",
            "partition": context.partition_key,
            "num_records": len(df),
        },
    )
