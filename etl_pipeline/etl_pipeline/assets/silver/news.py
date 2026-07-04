import pandas as pd
from dagster import AssetIn, DailyPartitionsDefinition, Output, asset
from etl_pipeline.ops.normalize.vietcap import normalize_vietcap_news
from etl_pipeline.ops.normalize.vietstock import normalize_vietstock_news
from etl_pipeline.ops.tickers import get_stock_symbols


daily = DailyPartitionsDefinition(
    start_date="2025-12-01",
    timezone="Asia/Ho_Chi_Minh",
    end_offset=1,
)

NEWS_COLUMNS = [
    "url",
    "title",
    "date_posted",
    "ticker",
    "section",
    "tags",
    "summary",
    "source",
    "sentiment",
]


def _empty_news_df() -> pd.DataFrame:
    return pd.DataFrame(columns=NEWS_COLUMNS)


def _normalize_tickers(x):
    if isinstance(x, list):
        return [t.strip().upper() for t in x if t] or [None]
    if isinstance(x, str):
        tickers = [t.strip().upper() for t in x.split(",") if t.strip()]
        return tickers or [None]
    return [None]


@asset(
    partitions_def=daily,
    io_manager_key="minio_io_manager",
    ins={
        "bronze_vietstock_news": AssetIn(key_prefix=["bronze"]),
        "bronze_vietcap_news": AssetIn(key_prefix=["bronze"]),
    },
    compute_kind="Pandas",
    key_prefix=["silver"],
    group_name="silver",
)
def silver_news(
    context,
    bronze_vietstock_news: pd.DataFrame,
    bronze_vietcap_news: pd.DataFrame,
):
    frames = []

    if not bronze_vietcap_news.empty:
        frames.append(normalize_vietcap_news(bronze_vietcap_news))

    if not bronze_vietstock_news.empty:
        vietstock = normalize_vietstock_news(bronze_vietstock_news)
        vietstock = vietstock[
            [
                "url",
                "title",
                "date_posted",
                "tickers",
                "section",
                "tags",
                "summary",
            ]
        ]
        vietstock["source"] = "Vietstock"
        vietstock["tickers"] = vietstock["tickers"].apply(_normalize_tickers)
        vietstock = (
            vietstock
            .explode("tickers")
            .rename(columns={"tickers": "ticker"})
            .reset_index(drop=True)
        )
        frames.append(vietstock)

    if not frames:
        return Output(_empty_news_df(), metadata={"num_records": 0})

    df = pd.concat(frames, ignore_index=True)

    if "ticker" not in df.columns:
        return Output(_empty_news_df(), metadata={"num_records": 0})

    hose_tickers = set(get_stock_symbols())
    df = df[df["ticker"].isin(hose_tickers)].copy()

    partition_date = pd.to_datetime(context.partition_key).date()
    df["date_posted"] = (
        pd.to_datetime(df["date_posted"], errors="coerce", utc=True)
        .dt.tz_convert("Asia/Ho_Chi_Minh")
        .dt.tz_localize(None)
        .dt.date
    )
    df = df[df["date_posted"] == partition_date].copy()

    for col in NEWS_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df[NEWS_COLUMNS]
    return Output(df, metadata={"num_records": len(df)})
