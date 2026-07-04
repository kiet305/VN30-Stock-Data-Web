import pandas as pd
from dagster import AssetKey, Output, asset
from etl_pipeline.ops.normalize.reports import normalize_reports
from etl_pipeline.ops.tickers import get_stock_symbols
from etl_pipeline.assets.bronze.reports import report_partitions

@asset(
    partitions_def=report_partitions,
    io_manager_key="minio_io_manager",
    required_resource_keys={"minio_io_manager"},
    group_name="silver",
    key_prefix=["silver"],
)
def silver_reports(context) -> Output[pd.DataFrame]:
    io = context.resources.minio_io_manager
    partition_key = context.partition_key

    bs = io.load_partition(
        AssetKey(["bronze", "reports", "bronze_balance_sheet"]),
        partition_key,
    )
    is_ = io.load_partition(
        AssetKey(["bronze", "reports", "bronze_income_statement"]),
        partition_key,
    )
    cf = io.load_partition(
        AssetKey(["bronze", "reports", "bronze_cash_flow"]),
        partition_key,
    )

    df = pd.concat(
        [
            normalize_reports(bs, "bs"),
            normalize_reports(is_, "is"),
            normalize_reports(cf, "cf"),
        ],
        ignore_index=True,
    )
    hose_tickers = set(get_stock_symbols())
    df = df[df["ticker"].isin(hose_tickers)].copy()

    return Output(
        df,
        metadata={"num_records": len(df)},
    )
