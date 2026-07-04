import pandas as pd
import time
from requests.exceptions import ConnectionError
from datetime import datetime
from etl_pipeline.ops.tickers import get_stock_symbols
from vnstock import Quote

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

def vnstock_interval(interval: str) -> str:
    interval_map = {
        "1d": "1D",
        "5m": "5m",
    }
    try:
        return interval_map[interval]
    except KeyError:
        raise ValueError("interval must be one of: '1d' or '5m'")

def normalize_quote_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()
    if "time" not in df.columns and "date" in df.columns:
        df = df.rename(columns={"date": "time"})
    if "time" in df.columns:
        df = df.drop_duplicates(subset=["time"], keep="last")
    return df

def filter_quote_date_range(
    df: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    if df.empty or "time" not in df.columns:
        return df

    df = df.copy()
    quote_dates = pd.to_datetime(df["time"], errors="coerce").dt.date
    start = pd.to_datetime(start_date).date()
    end = pd.to_datetime(end_date).date()
    return df[(quote_dates >= start) & (quote_dates <= end)].copy()
        
def get_prices(
    *,
    context,
    tickers: list[str],
    limit: int | None = None,
    interval: str = '1d',
    start_date: str,
    end_date:  str
) -> pd.DataFrame:
    """
    Bronze layer financial reports
    """
    bronze_frames = []
    fetched_symbols = []
    skipped_symbols = []

    total = len(tickers)

    context.log.info(
        f"Start fetching {interval} prices for symbols={total}"
    )

    quote_interval = vnstock_interval(interval)

    for idx, ticker in enumerate(tickers, start=1):
        context.log.info(
            f"[{idx}/{total}] Fetching {interval} prices for {ticker}"
        )

        # --- chọn đúng API call ---
        fn = lambda t=ticker: Quote(symbol=t, source="kbs").history(
            start=start_date,
            end=end_date,
            interval=quote_interval,
        )

        # --- gọi API với retry ---
        df_raw = retry_call(fn, logger=context.log)

        if df_raw is None or df_raw.empty:
            context.log.warning(f"Skip {ticker}")
            skipped_symbols.append(ticker)
            continue

        context.log.info(
            f"Fetched {interval}  for {ticker} "
            f"({len(df_raw)} rows)"
        )

        fetched_symbols.append(ticker)

        # --- Bronze metadata ---
        df_raw = normalize_quote_columns(df_raw)
        df_raw = filter_quote_date_range(
            df_raw,
            start_date=start_date,
            end_date=end_date,
        )
        if df_raw.empty:
            context.log.warning(f"Skip {ticker}: no rows inside requested date range")
            skipped_symbols.append(ticker)
            continue

        df_raw["ticker"] = ticker
        df_raw["date_fetched"] = datetime.now()

        bronze_frames.append(df_raw)

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
