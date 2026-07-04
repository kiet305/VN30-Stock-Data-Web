import pandas as pd
import time
import re
from requests.exceptions import ConnectionError
from datetime import datetime
from vnstock import Finance
from etl_pipeline.ops.tickers import get_stock_symbols

def get_stock_list():
    return get_stock_symbols()

def retry_call(fn, logger, max_retries=10, rate_limit_sleep=20):
    for attempt in range(1, max_retries + 1):
        try:
            return fn()

        except SystemExit:
            if attempt < max_retries:
                logger.warning(
                    f"Rate limit hit. Retry {attempt}/{max_retries} "
                    f"after {rate_limit_sleep}s"
                )
                time.sleep(rate_limit_sleep)
            else:
                logger.error("Rate limit hit. Max retries reached.")
                return None

        except ConnectionError:
            logger.warning("Connection error (502/504). Skip symbol")
            return None

        except Exception as e:
            logger.error(f"Unexpected error. Skip symbol: {e}")
            return None


PERIOD_COLUMN_RE = re.compile(r"^(?P<year>\d{4})-Q(?P<quarter>[1-4])$")

REPORT_METHODS = {
    "is": "income_statement",
    "bs": "balance_sheet",
    "cf": "cash_flow",
}


def _period_columns(df: pd.DataFrame) -> list[str]:
    return [col for col in df.columns if PERIOD_COLUMN_RE.match(str(col))]


def _to_bronze_long(
    df_raw: pd.DataFrame,
    *,
    ticker: str,
    report_type: str,
    fetched_at: datetime,
) -> pd.DataFrame:
    """Convert VCI get_all output to one row per item and quarter."""
    df_raw = df_raw.copy().reset_index(drop=True)

    period_cols = _period_columns(df_raw)
    if not period_cols:
        df_raw["ticker"] = ticker
        df_raw["report_type"] = report_type
        df_raw["source"] = "VCI"
        df_raw["date_fetched"] = fetched_at
        return df_raw

    id_cols = [
        col for col in ["item", "item_en", "item_id"]
        if col in df_raw.columns
    ]

    out = df_raw.melt(
        id_vars=id_cols,
        value_vars=period_cols,
        var_name="_period_label",
        value_name="value_raw",
    )

    parsed_period = out["_period_label"].astype(str).str.extract(PERIOD_COLUMN_RE)
    out["year"] = parsed_period["year"].astype(int)
    out["quarter"] = parsed_period["quarter"].astype(int)
    out["ticker"] = ticker
    out["report_type"] = report_type
    out["source"] = "VCI"
    out["date_fetched"] = fetched_at

    ordered_cols = [
        "ticker", "year", "quarter", "report_type", "source",
        "date_fetched", "item_id", "item", "item_en",
        "value_raw",
    ]
    return out[[col for col in ordered_cols if col in out.columns]]

def get_report(
    *,
    context,
    tickers: list[str],
    report_type: str = "is",
    limit: int | None = None,
) -> pd.DataFrame:
    """
    Bronze layer financial reports
    """

    REPORT_TYPE = {
        "is": "INCOME STATEMENT",
        "bs": "BALANCE SHEET",
        "cf": "CASH FLOW",
    }

    bronze_frames = []
    fetched_symbols = []
    skipped_symbols = []

    total = len(tickers)
    report_name = REPORT_TYPE.get(report_type, report_type.upper())

    context.log.info(
        f"Start crawling {report_name} | symbols={total}"
    )

    for idx, ticker in enumerate(tickers, start=1):
        context.log.info(
            f"[{idx}/{total}] Fetching {report_name} for {ticker}"
        )

        # --- chọn đúng API call ---
        if report_type not in REPORT_METHODS:
            raise ValueError(
                "report_type must be one of: 'is', 'bs', 'cf'"
            )

        def fn(t=ticker):
            finance_vci = Finance(
                source="VCI",
                symbol=t,
                period="quarter",
                get_all=True,
                show_log=False,
            )
            method = getattr(finance_vci, REPORT_METHODS[report_type])
            return method(period="quarter")

        # --- gọi API với retry ---
        df_raw = retry_call(fn, logger=context.log)

        if df_raw is None or df_raw.empty:
            context.log.warning(f"Skip {ticker}")
            skipped_symbols.append(ticker)
            continue

        context.log.info(
            f"Fetched {report_type.upper()} for {ticker} "
            f"({len(df_raw)} rows)"
        )

        fetched_symbols.append(ticker)

        bronze_frames.append(
            _to_bronze_long(
                df_raw,
                ticker=ticker,
                report_type=report_type,
                fetched_at=datetime.now(),
            )
        )

        # --- optional limit ---
        if limit and len(fetched_symbols) >= limit:
            context.log.warning(f"Reached limit = {limit}")
            break

    # --- summary ---
    context.log.info("INGEST SUMMARY")
    context.log.info(f"Success ({len(fetched_symbols)}): {fetched_symbols}")
    context.log.info(f"Skipped ({len(skipped_symbols)}): {skipped_symbols}")

    if not bronze_frames:
        context.log.warning("No data fetched")
        return pd.DataFrame()

    return pd.concat(bronze_frames, ignore_index=True)
