from dagster import asset, Output, AssetIn
from etl_pipeline.ops.normalize.company_info import normalize_info
from etl_pipeline.assets.partitions import company_info_partitions_def

def silver_company_info(info_type: str):
    partitions_def = company_info_partitions_def(info_type)
    asset_kwargs = {
        "name": f"silver_{info_type}",
        "ins": {"info": AssetIn(["bronze", "company_info", f"bronze_{info_type}"])},
        "io_manager_key": "minio_io_manager",
        "key_prefix": ["silver", "company_info"],
        "compute_kind": "python",
        "group_name": "silver",
    }
    if partitions_def:
        asset_kwargs["partitions_def"] = partitions_def

    @asset(**asset_kwargs)
    def _asset(context, info):
        info_df = normalize_info(info, info_type=info_type)
        return Output(
            info_df,
            metadata={
                "info_type": info_type,
                "partition": context.partition_key if context.has_partition_key else None,
                "num_records": len(info_df),
            },
        )
    return _asset
