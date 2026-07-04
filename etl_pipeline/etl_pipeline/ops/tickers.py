import pandas as pd
from vnstock import Listing


DEFAULT_EXCHANGE = "HOSE"
HOSE_INDEX_TICKERS = {"VNINDEX", "VN30", "VN100"}
EXCHANGE_ALIASES = {
    "HOSE": "HSX",
}


def _listing() -> Listing:
    return Listing(source="VCI")


def _as_symbol_set(value) -> set[str]:
    if isinstance(value, pd.DataFrame):
        if "symbol" in value.columns:
            return set(value["symbol"].dropna().astype(str))
        return set()

    return set(pd.Series(value).dropna().astype(str))


def get_stock_universe(exchange: str = DEFAULT_EXCHANGE) -> pd.DataFrame:
    listing = _listing()
    df = pd.DataFrame(listing.symbols_by_exchange())

    exchange = EXCHANGE_ALIASES.get(exchange.upper(), exchange.upper())
    df = df[
        df["type"].astype(str).str.upper().str.contains("STOCK", na=False)
        & (df["exchange"].astype(str).str.upper() == exchange)
    ].copy()

    return df.reset_index(drop=True)


def get_stock_symbols(exchange: str = DEFAULT_EXCHANGE) -> list[str]:
    df = get_stock_universe(exchange=exchange)
    return sorted(df["symbol"].dropna().astype(str).unique().tolist())


def get_vn30_symbols() -> list[str]:
    listing = _listing()
    symbols = _as_symbol_set(listing.symbols_by_group("VN30"))
    return sorted(symbol.strip().upper() for symbol in symbols if symbol.strip())


def get_stock_master(exchange: str = DEFAULT_EXCHANGE) -> pd.DataFrame:
    listing = _listing()
    df = get_stock_universe(exchange=exchange)

    df = df.rename(
        columns={
            "symbol": "ticker",
            "organ_short_name": "name",
            "exchange": "trading_floor",
        }
    )

    if "name" not in df.columns:
        df["name"] = df["ticker"]

    df = df[["ticker", "name", "trading_floor"]]

    vn30 = _as_symbol_set(listing.symbols_by_group("VN30"))
    vn100 = _as_symbol_set(listing.symbols_by_group("VN100"))
    df["is_vn30"] = df["ticker"].isin(vn30)
    df["is_vn100"] = df["ticker"].isin(vn100)
    df["is_hnx30"] = False

    df_icb = pd.DataFrame(listing.symbols_by_industries())
    if not df_icb.empty and "symbol" in df_icb.columns:
        if "icb_name2" not in df_icb.columns:
            df_icb["icb_name2"] = None
        if "icb_name3" not in df_icb.columns:
            df_icb["icb_name3"] = None

        df = df.merge(
            df_icb[["symbol", "icb_name2", "icb_name3"]],
            left_on="ticker",
            right_on="symbol",
            how="left",
        )
        df = df.drop(columns={"symbol"})
    else:
        df["icb_name2"] = None
        df["icb_name3"] = None

    return df.rename(
        columns={
            "icb_name3": "subindustry",
            "icb_name2": "industry",
        }
    )
