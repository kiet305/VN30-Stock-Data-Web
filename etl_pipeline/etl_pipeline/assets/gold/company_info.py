from dagster import asset, Output, AssetIn
import pandas as pd

from etl_pipeline.assets.partitions import company_info_partitions_def

PRICE_ADJUSTMENT_EVENT_TYPE_IDS = {1, 2, 3, 4}
GOLD_EVENT_COLUMNS = [
    "event_id",
    "ticker",
    "year",
    "record_date",
    "event_title",
    "ratio",
    "value",
    "event_type",
    "event_type_id",
    "event_list_name",
    "event_year",
    "pay_time",
    "rate_cash",
    "rate_original",
    "rate_split",
    "ratio_display",
    "value_display",
    "public_date",
    "issue_date",
    "exright_date",
    "payment_date",
    "source_url",
    "source_page",
    "date_fetched",
]


def filter_price_adjustment_events(info_type: str, info):
    if info_type != "events" or "event_type_id" not in info.columns:
        return info

    event_type_id = pd.to_numeric(info["event_type_id"], errors="coerce").astype("Int64")
    if "record_date" not in info.columns or "exright_date" not in info.columns:
        return info.iloc[0:0].copy()

    has_record_date = pd.to_datetime(info["record_date"], errors="coerce").notna()
    has_exright_date = pd.to_datetime(info["exright_date"], errors="coerce").notna()

    return info[
        event_type_id.isin(PRICE_ADJUSTMENT_EVENT_TYPE_IDS)
        & has_record_date
        & has_exright_date
    ].copy()


def select_gold_event_columns(info_type: str, info):
    if info_type != "events":
        return info

    selected = info.copy()
    for column in GOLD_EVENT_COLUMNS:
        if column not in selected.columns:
            selected[column] = None

    return selected[GOLD_EVENT_COLUMNS].copy()


def normalize_gold_overview(info_type: str, info: pd.DataFrame) -> pd.DataFrame:
    if info_type != "overview" or info is None or info.empty:
        return info

    df = info.copy()
    if "ticker" in df.columns:
        df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
        df = df[df["ticker"].ne("") & df["ticker"].ne("NAN")].copy()
        if "date_fetched" in df.columns:
            df["date_fetched"] = pd.to_datetime(df["date_fetched"], errors="coerce")
            df = df.sort_values(["ticker", "date_fetched"])
        df = df.drop_duplicates(subset=["ticker"], keep="last")

    return df.reset_index(drop=True)


def normalize_gold_officers(info_type: str, info: pd.DataFrame) -> pd.DataFrame:
    if info_type != "officers" or info is None or info.empty:
        return info

    df = info.copy()
    for column in [
        "ticker",
        "officer_name",
        "officer_position",
        "officer_own_quantity",
        "officer_own_percent",
        "update_date",
    ]:
        if column not in df.columns:
            df[column] = None

    df["ticker"] = df["ticker"].fillna("").astype(str).str.strip().str.upper()
    df["officer_name"] = df["officer_name"].fillna("").astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    df["officer_position"] = df["officer_position"].fillna("").astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    df = df[df["ticker"].ne("") & df["ticker"].ne("NAN") & df["officer_name"].ne("")].copy()

    df["_officer_name_key"] = df["officer_name"].str.casefold()
    df["_has_quantity"] = df["officer_own_quantity"].notna().astype(int)
    df["_has_percent"] = df["officer_own_percent"].notna().astype(int)
    df["_has_position"] = df["officer_position"].ne("").astype(int)
    df["_update_dt"] = pd.to_datetime(df["update_date"], errors="coerce")

    df = df.sort_values(
        [
            "ticker",
            "_officer_name_key",
            "_has_quantity",
            "_has_percent",
            "_has_position",
            "_update_dt",
        ],
        ascending=[True, True, False, False, False, False],
    )
    df = df.drop_duplicates(subset=["ticker", "_officer_name_key"], keep="first")

    return df.drop(
        columns=[
            "_officer_name_key",
            "_has_quantity",
            "_has_percent",
            "_has_position",
            "_update_dt",
        ],
        errors="ignore",
    ).reset_index(drop=True)


def gold_company_info(info_type: str):
    partitions_def = company_info_partitions_def(info_type)
    asset_kwargs = {
        "name": f"gold_{info_type}",
        "ins": {"info": AssetIn(["silver", "company_info", f"silver_{info_type}"])},
        "io_manager_key": "minio_io_manager",
        "key_prefix": ["gold", "company_info"],
        "compute_kind": "python",
        "group_name": "gold",
    }
    if partitions_def:
        asset_kwargs["partitions_def"] = partitions_def

    @asset(**asset_kwargs)
    def _asset(context, info):
        filtered_info = select_gold_event_columns(
            info_type,
            filter_price_adjustment_events(info_type, info),
        )
        filtered_info = normalize_gold_overview(info_type, filtered_info)
        filtered_info = normalize_gold_officers(info_type, filtered_info)
        metadata = {
            "info_type": info_type,
            "partition": context.partition_key if context.has_partition_key else None,
            "num_records": len(filtered_info),
            "source_records": len(info),
        }
        if info_type == "events":
            metadata["price_adjustment_event_type_ids"] = sorted(
                PRICE_ADJUSTMENT_EVENT_TYPE_IDS
            )
            metadata["required_columns"] = ["record_date", "exright_date"]
            metadata["columns"] = GOLD_EVENT_COLUMNS

        return Output(
            filtered_info,
            metadata=metadata,
        )
    return _asset

def warehouse_company_info(info_type: str):
    partitions_def = company_info_partitions_def(info_type)
    asset_kwargs = {
        "name": f"warehouse_{info_type}",
        "ins": {
            f"gold_{info_type}": AssetIn(
                key_prefix=["gold", "company_info"]
            )
        },
        "io_manager_key": "psql_io_manager",
        "key_prefix": ["warehouse", "company_info"],
        "compute_kind": "python",
        "group_name": "warehouse",
    }
    if partitions_def:
        asset_kwargs["partitions_def"] = partitions_def

    @asset(**asset_kwargs)
    def _asset(context, **kwargs):
        df = kwargs[f"gold_{info_type}"]

        metadata = {
            "table": f"warehouse.warehouse_{info_type}",
            "rows_loaded": len(df),
        }
        if info_type == "events":
            metadata["unique_key"] = ["event_id"]
            metadata["replace_table"] = True
        if info_type == "overview":
            metadata["unique_key"] = ["ticker"]
        if info_type == "shareholders":
            metadata["unique_key"] = ["ticker", "share_holder", "update_date"]
        if info_type == "officers":
            metadata["unique_key"] = ["ticker", "officer_name"]
        metadata["partition"] = context.partition_key if context.has_partition_key else None

        return Output(
            df,
            metadata=metadata,
        )

    return _asset
