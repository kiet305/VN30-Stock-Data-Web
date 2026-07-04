from datetime import datetime, timedelta, timezone
import json

import numpy as np
import pandas as pd
from dagster import AssetKey, Field, Output, asset
from sqlalchemy import text

from etl_pipeline.ops.crawling.vietcap import crawl_vietcap_news
from etl_pipeline.ops.crawling.vietstock import crawl_vietstock_news
from etl_pipeline.ops.normalize.vietcap import normalize_vietcap_news
from etl_pipeline.ops.normalize.vietstock import normalize_vietstock_news
from etl_pipeline.ops.tickers import get_stock_symbols
from etl_pipeline.resources.psql_io_manager import connect_psql


VN_TZ = timezone(timedelta(hours=7))

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

BRONZE_VIETCAP_COLUMNS = [
    "url_raw",
    "url_norm",
    "title_raw",
    "date_posted_raw",
    "date_posted",
    "card_text_raw",
    "crawl_date",
    "crawl_ts",
    "content_html_raw",
    "content_text_raw",
    "is_success",
    "error_message",
]

BRONZE_VIETSTOCK_COLUMNS = [
    "url_raw",
    "url_norm",
    "content_html_raw",
    "content_text_raw",
    "title_raw",
    "date_posted_raw",
    "date_posted",
    "crawl_time",
    "is_success",
]


def _parse_config_date(value: str | None, *, default: datetime | None = None) -> datetime:
    if not value:
        if default is None:
            raise ValueError("Missing required date")
        return default

    dt = pd.to_datetime(value, errors="raise")
    if isinstance(dt, pd.Timestamp):
        parsed = dt.to_pydatetime()
    else:
        parsed = dt

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=VN_TZ)
    return parsed.astimezone(VN_TZ)


def _date_keys(start_dt: datetime, end_dt: datetime) -> list[str]:
    start_day = start_dt.astimezone(VN_TZ).date()
    end_day = end_dt.astimezone(VN_TZ).date()
    days = pd.date_range(start_day, end_day, freq="D")
    return [day.strftime("%Y-%m-%d") for day in days]


def _empty_df(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return _empty_df(columns)

    df = df.copy()
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df[columns]


def _date_series(df: pd.DataFrame, column: str = "date_posted") -> pd.Series:
    values = pd.to_datetime(df[column], errors="coerce", utc=True)
    return values.dt.tz_convert("Asia/Ho_Chi_Minh").dt.tz_localize(None).dt.date


def _date_span(df: pd.DataFrame) -> tuple[str | None, str | None]:
    if df.empty or "date_posted" not in df.columns:
        return None, None

    dates = _date_series(df).dropna()
    if dates.empty:
        return None, None

    return min(dates).isoformat(), max(dates).isoformat()


def _normalize_tickers(x):
    if isinstance(x, list):
        return [t.strip().upper() for t in x if t] or [None]
    if isinstance(x, str):
        tickers = [t.strip().upper() for t in x.split(",") if t.strip()]
        return tickers or [None]
    return [None]


def _build_silver_news(vietcap_raw: pd.DataFrame, vietstock_raw: pd.DataFrame) -> pd.DataFrame:
    frames = []

    if not vietcap_raw.empty:
        frames.append(normalize_vietcap_news(vietcap_raw))

    if not vietstock_raw.empty:
        vietstock = normalize_vietstock_news(vietstock_raw)
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
        return _empty_df(NEWS_COLUMNS)

    df = pd.concat(frames, ignore_index=True)
    if "ticker" not in df.columns:
        return _empty_df(NEWS_COLUMNS)

    hose_tickers = set(get_stock_symbols())
    df = df[df["ticker"].isin(hose_tickers)].copy()
    if df.empty:
        return _empty_df(NEWS_COLUMNS)

    df["date_posted"] = _date_series(df)

    for col in NEWS_COLUMNS:
        if col not in df.columns:
            df[col] = None

    return df[NEWS_COLUMNS]


def _write_daily_partitions(io, asset_key: AssetKey, df: pd.DataFrame, date_keys: list[str], columns: list[str]) -> int:
    rows_written = 0
    if df.empty or "date_posted" not in df.columns:
        for partition_key in date_keys:
            io.write_partition(asset_key, partition_key, _empty_df(columns))
        return rows_written

    work = df.copy()
    work["_partition_date"] = _date_series(work)

    for partition_key in date_keys:
        partition_date = pd.to_datetime(partition_key).date()
        part = work[work["_partition_date"] == partition_date].drop(columns=["_partition_date"]).copy()
        part = _ensure_columns(part, columns)
        rows_written += len(part)
        io.write_partition(asset_key, partition_key, part)

    return rows_written


def _serialize_tags(value):
    if isinstance(value, np.ndarray):
        return json.dumps(value.tolist(), ensure_ascii=False)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return value


def _upsert_warehouse_news(psql, df: pd.DataFrame) -> int:
    if df.empty:
        return 0

    obj = df.copy()
    obj = _ensure_columns(obj, NEWS_COLUMNS)
    obj["tags"] = obj["tags"].apply(_serialize_tags)
    obj = obj.drop_duplicates(subset=["url"], keep="last")

    with connect_psql(psql._config, "warehouse") as engine:
        with engine.begin() as conn:
            temp_table = "__tmp_warehouse_news"
            conn.execute(text(f"DROP TABLE IF EXISTS warehouse.{temp_table}"))

            obj.to_sql(
                temp_table,
                con=conn,
                schema="warehouse",
                if_exists="replace",
                index=False,
            )

            exists = conn.execute(
                text("SELECT to_regclass(:qualified_table)"),
                {"qualified_table": "warehouse.warehouse_news"},
            ).scalar()
            if not exists:
                obj.head(0).to_sql(
                    "warehouse_news",
                    con=conn,
                    schema="warehouse",
                    if_exists="replace",
                    index=False,
                )

            conn.execute(
                text(
                    """
                    DELETE FROM warehouse.warehouse_news t
                    USING warehouse.__tmp_warehouse_news s
                    WHERE t.url = s.url
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO warehouse.warehouse_news (
                        url,
                        title,
                        date_posted,
                        ticker,
                        section,
                        tags,
                        summary,
                        source,
                        sentiment
                    )
                    SELECT
                        url,
                        title,
                        date_posted,
                        ticker,
                        section,
                        tags,
                        summary,
                        source,
                        sentiment
                    FROM warehouse.__tmp_warehouse_news
                    """
                )
            )
            conn.execute(text(f"DROP TABLE IF EXISTS warehouse.{temp_table}"))

    return len(obj)


@asset(
    config_schema={
        "start_date": Field(str, description="Ngày cũ nhất cần crawl, ví dụ 2026-06-01."),
        "end_date": Field(str, default_value="", description="Ngày mới nhất cần giữ lại. Bỏ trống để dùng thời điểm hiện tại."),
        "write_warehouse": Field(bool, default_value=True, description="Upsert warehouse.warehouse_news sau khi ghi partitions."),
        "vietcap_max_rounds": Field(int, default_value=1200, description="Số vòng scroll tối đa cho Vietcap bulk crawl."),
        "vietcap_idle_rounds_to_stop": Field(int, default_value=60, description="Số vòng không thêm URL trước khi dừng Vietcap."),
        "vietstock_max_pages": Field(int, default_value=1200, description="Số trang tối đa cho Vietstock bulk crawl."),
    },
    required_resource_keys={"minio_io_manager", "psql_io_manager"},
    io_manager_key="minio_io_manager",
    compute_kind="python",
    group_name="maintenance",
)
def bulk_news_refresh(context) -> Output[pd.DataFrame]:
    config = context.op_config
    now = datetime.now(VN_TZ)
    start_dt = _parse_config_date(config["start_date"])
    end_dt = _parse_config_date(config.get("end_date"), default=now)
    end_dt = min(end_dt, now)

    if start_dt > end_dt:
        raise ValueError(f"start_date must be <= end_date, got {start_dt.isoformat()} > {end_dt.isoformat()}")

    date_keys = _date_keys(start_dt, end_dt)
    context.log.info(
        "[BULK NEWS] Crawl once per source | start=%s | end=%s | partitions=%s -> %s",
        start_dt.isoformat(),
        end_dt.isoformat(),
        date_keys[0],
        date_keys[-1],
    )

    vietcap_raw = crawl_vietcap_news(
        start_date=start_dt,
        end_date=end_dt,
        max_rounds=config["vietcap_max_rounds"],
        idle_rounds_to_stop=config["vietcap_idle_rounds_to_stop"],
    )
    vietcap_raw = _ensure_columns(vietcap_raw, BRONZE_VIETCAP_COLUMNS)
    vietcap_min_date, vietcap_max_date = _date_span(vietcap_raw)
    context.log.info(
        "[BULK NEWS] Vietcap raw rows=%s | date_span=%s -> %s",
        len(vietcap_raw),
        vietcap_min_date,
        vietcap_max_date,
    )

    vietstock_raw = crawl_vietstock_news(
        start_date=start_dt,
        end_date=end_dt,
        max_pages=config["vietstock_max_pages"],
    )
    vietstock_raw = _ensure_columns(vietstock_raw, BRONZE_VIETSTOCK_COLUMNS)
    vietstock_min_date, vietstock_max_date = _date_span(vietstock_raw)
    context.log.info(
        "[BULK NEWS] Vietstock raw rows=%s | date_span=%s -> %s",
        len(vietstock_raw),
        vietstock_min_date,
        vietstock_max_date,
    )

    silver = _build_silver_news(vietcap_raw, vietstock_raw)
    if not silver.empty:
        start_day = start_dt.date()
        end_day = end_dt.date()
        silver = silver[(silver["date_posted"] >= start_day) & (silver["date_posted"] <= end_day)].copy()
    gold = silver.copy()
    gold_min_date, gold_max_date = _date_span(gold)
    context.log.info(
        "[BULK NEWS] Silver/Gold rows=%s | date_span=%s -> %s",
        len(gold),
        gold_min_date,
        gold_max_date,
    )

    io = context.resources.minio_io_manager
    bronze_vietcap_rows = _write_daily_partitions(
        io,
        AssetKey(["bronze", "bronze_vietcap_news"]),
        vietcap_raw,
        date_keys,
        BRONZE_VIETCAP_COLUMNS,
    )
    bronze_vietstock_rows = _write_daily_partitions(
        io,
        AssetKey(["bronze", "bronze_vietstock_news"]),
        vietstock_raw,
        date_keys,
        BRONZE_VIETSTOCK_COLUMNS,
    )
    silver_rows = _write_daily_partitions(
        io,
        AssetKey(["silver", "silver_news"]),
        silver,
        date_keys,
        NEWS_COLUMNS,
    )
    gold_rows = _write_daily_partitions(
        io,
        AssetKey(["gold", "gold_news"]),
        gold,
        date_keys,
        NEWS_COLUMNS,
    )

    warehouse_rows = 0
    if config.get("write_warehouse", True):
        warehouse_rows = _upsert_warehouse_news(context.resources.psql_io_manager, gold)

    summary = pd.DataFrame(
        [
            {
                "start_date": start_dt.date().isoformat(),
                "end_date": end_dt.date().isoformat(),
                "partitions_written": len(date_keys),
                "bronze_vietcap_rows": bronze_vietcap_rows,
                "bronze_vietstock_rows": bronze_vietstock_rows,
                "silver_rows": silver_rows,
                "gold_rows": gold_rows,
                "warehouse_rows": warehouse_rows,
                "vietcap_min_date": vietcap_min_date,
                "vietcap_max_date": vietcap_max_date,
                "vietstock_min_date": vietstock_min_date,
                "vietstock_max_date": vietstock_max_date,
                "gold_min_date": gold_min_date,
                "gold_max_date": gold_max_date,
            }
        ]
    )

    return Output(
        summary,
        metadata={
            "start_date": start_dt.date().isoformat(),
            "end_date": end_dt.date().isoformat(),
            "partitions_written": len(date_keys),
            "bronze_vietcap_rows": bronze_vietcap_rows,
            "bronze_vietstock_rows": bronze_vietstock_rows,
            "silver_rows": silver_rows,
            "gold_rows": gold_rows,
            "warehouse_rows": warehouse_rows,
            "vietcap_min_date": vietcap_min_date,
            "vietcap_max_date": vietcap_max_date,
            "vietstock_min_date": vietstock_min_date,
            "vietstock_max_date": vietstock_max_date,
            "gold_min_date": gold_min_date,
            "gold_max_date": gold_max_date,
        },
    )
