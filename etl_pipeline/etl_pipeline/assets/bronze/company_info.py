from dagster import asset, Output
from etl_pipeline.ops.api.company_info import get_company_information, get_stock_list
from etl_pipeline.assets.partitions import company_info_partitions_def

def bronze_company_info(info_type: str):
    partitions_def = company_info_partitions_def(info_type)
    asset_kwargs = {
        "name": f"bronze_{info_type}",
        "io_manager_key": "minio_io_manager",
        "key_prefix": ["bronze", "company_info"],
        "compute_kind": "python",
        "group_name": "bronze",
    }
    if partitions_def:
        asset_kwargs["partitions_def"] = partitions_def

    @asset(**asset_kwargs)
    def _asset(context):
        """
        Crawl Company's Overview Information
        """
        records = get_company_information(
            context,
            tickers=get_stock_list(),
            type=info_type,
        )

        return Output(
            records,
            metadata={
                "info_type": info_type,
                "source": (
                    f"vnstock.Company.{info_type}"
                    if info_type in {"events", "ratio_summary"}
                    else "vnstock"
                ),
                "partition": context.partition_key if context.has_partition_key else None,
                "num_records": len(records),
            },
        )

    return _asset
