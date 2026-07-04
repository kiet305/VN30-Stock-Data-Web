import pandas as pd
import numpy as np
import re

def get_stock_list():
    raise RuntimeError("normalize_overview must use bronze overview data only")

    listing = Listing(source='VCI')

    df = pd.DataFrame(listing.symbols_by_exchange())
    df = df[df["type"].str.contains("STOCK", na=False)].reset_index(drop=True)

    df = df.rename(columns={
        "symbol": "ticker",
        "organ_short_name": "name",
        "exchange": "trading_floor"
    })

    df = df[['ticker', 'name', 'trading_floor']]

    # nhóm theo vốn hóa
    vn30 = listing.symbols_by_group('VN30')
    vn100 = listing.symbols_by_group('VN100')
    df["is_vn30"] = df["ticker"].isin(vn30)
    df["is_vn100"] = df["ticker"].isin(vn100)

    # nhóm theo ngành
    df_icb = listing.symbols_by_industries()
    df = df.merge(
        df_icb[["symbol", "icb_name2", "icb_name3"]],
        left_on="ticker",
        right_on="symbol",
        how="left"
    )
    df = df.drop(columns={'symbol'})
    df = df.rename(columns={'icb_name3': 'subindustry', 'icb_name2': 'industry'})
    
    return df


def _legacy_normalize_overview(df: pd.DataFrame) -> pd.DataFrame:
    df_master = get_stock_list()
    df_silver = pd.merge(
        df,
        df_master,
        left_on="ticker",
        right_on="ticker",
        how="inner",
    )

    # ---------- Chuẩn hoá cap_group ----------
    df_silver["cap_group"] = np.nan

    df_silver.loc[df_silver["is_vn30"] == True, "cap_group"] = "VN30"
    df_silver.loc[
        (df_silver["is_vn30"] != True) & (df_silver["is_vn100"] == True),
        "cap_group",
    ] = "VN100"
    # ---------- Select final columns ----------
    df_silver = df_silver[
        [
            "ticker",
            "name",
            "trading_floor",
            "industry",
            "subindustry",
            "history",
            "company_profile",
            "issue_share",
            "cap_group",
            "date_fetched"
        ]
    ]
    return df_silver

EVENT_COLUMNS = [
    "ticker",
    "event_id",
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


def _clean_text(value):
    if pd.isna(value):
        return None
    return str(value).strip()


def _date_str(value):
    if pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _first_date(row, columns):
    for column in columns:
        if column in row:
            value = _date_str(row[column])
            if value:
                return value
    return None


def _extract_year(text, fallback_date=None):
    text = _clean_text(text) or ""
    match = re.search(r"(?:năm|Year)\s+(\d{4})", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    if fallback_date:
        return int(str(fallback_date)[:4])
    return None


def _extract_pay_time(text):
    text = _clean_text(text) or ""
    match = re.search(r"(?:lần|lan)\s+(\d+)", text, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _event_kind(row):
    title = " ".join(
        str(row.get(column) or "")
        for column in ["event_name_vi", "event_title_vi", "event_name_en", "event_title_en"]
    ).lower()
    event_code = str(row.get("event_code") or "").upper()

    if event_code == "DIV" or "tiền mặt" in title or "cash dividend" in title:
        return 1, "Trả cổ tức bằng tiền mặt"
    if "cổ tức bằng cổ phiếu" in title or "stock dividend" in title:
        return 2, "Trả cổ tức bằng cổ phiếu"
    if "thưởng cổ phiếu" in title or "bonus" in title:
        return 4, "Thưởng cổ phiếu"
    if "quyền mua" in title or "phát hành thêm" in title or "right issue" in title:
        return 3, "Phát hành thêm cổ phiếu"
    if event_code == "ISS":
        return 3, "Phát hành thêm cổ phiếu"
    return None, _clean_text(row.get("event_name_vi")) or "Sự kiện khác"


def _format_number(value):
    if pd.isna(value):
        return None
    value = float(value)
    if value.is_integer():
        return str(int(value))
    return f"{value:g}"


def _format_vnd(value):
    if pd.isna(value):
        return None
    return f"{int(round(float(value))):,}".replace(",", ".")


def _build_ratio_fields(event_type_id, value_per_share, exercise_ratio):
    exercise_ratio = pd.to_numeric(exercise_ratio, errors="coerce")
    value_per_share = pd.to_numeric(value_per_share, errors="coerce")

    if event_type_id == 1:
        ratio = float(exercise_ratio) * 100 if not pd.isna(exercise_ratio) else None
        value = float(value_per_share) if not pd.isna(value_per_share) else None
        ratio_display = f"{_format_number(ratio)}%" if ratio is not None else None
        value_display = f"{_format_vnd(value)} đ/CP" if value is not None else None
        return ratio, value, ratio_display, value_display, ratio or 0.0, 0.0, 0.0

    if not pd.isna(exercise_ratio) and float(exercise_ratio) > 0:
        ratio = float(exercise_ratio) * 100
        denominator = 100.0
        numerator = ratio
        if ratio >= 100 and float(exercise_ratio).is_integer():
            denominator = 1.0
            numerator = float(exercise_ratio)
        ratio_display = f"{_format_number(denominator)}:{_format_number(numerator)}"
        value_display = (
            f"+{_format_number(numerator)} CP/{_format_number(denominator)} CP"
        )
        return ratio, ratio, ratio_display, value_display, 0.0, denominator, numerator

    return None, None, None, None, 0.0, 0.0, 0.0


def _normalize_vnstock_events(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    dividend_df = df[df.get("category", "").astype(str).str.upper().eq("DIVIDEND")].copy()

    for _, row in dividend_df.iterrows():
        exright_date = _first_date(row, ["exright_date", "display_date1"])
        record_date = _date_str(row.get("record_date"))
        public_date = _date_str(row.get("public_date"))
        payment_date = _date_str(row.get("payout_date"))
        issue_date = _first_date(row, ["issue_date", "exright_date", "display_date1"])
        event_date = exright_date or record_date or issue_date or public_date
        if not event_date or int(event_date[:4]) < 2020:
            continue

        event_type_id, event_type = _event_kind(row)
        event_title = _clean_text(row.get("event_title_vi")) or event_type
        event_year = _extract_year(event_title, event_date)
        pay_time = _extract_pay_time(event_title)
        ratio, value, ratio_display, value_display, rate_cash, rate_original, rate_split = (
            _build_ratio_fields(
                event_type_id,
                row.get("value_per_share"),
                row.get("exercise_ratio"),
            )
        )

        rows.append(
            {
                "ticker": _clean_text(row.get("ticker")),
                "event_id": _clean_text(row.get("id")),
                "year": int(event_date[:4]),
                "record_date": record_date,
                "event_title": event_title,
                "ratio": ratio,
                "value": value,
                "event_type": event_type,
                "event_type_id": event_type_id,
                "event_list_name": event_type,
                "event_year": event_year,
                "pay_time": pay_time,
                "rate_cash": rate_cash,
                "rate_original": rate_original,
                "rate_split": rate_split,
                "ratio_display": ratio_display,
                "value_display": value_display,
                "public_date": public_date,
                "issue_date": issue_date,
                "exright_date": exright_date,
                "payment_date": payment_date,
                "source_url": "vnstock.Company.events",
                "source_page": None,
                "date_fetched": row.get("date_fetched"),
            }
        )

    if not rows:
        return pd.DataFrame(columns=EVENT_COLUMNS)

    return pd.DataFrame(rows).drop_duplicates(subset=["event_id"], keep="last")


def normalize_events(df: pd.DataFrame) -> pd.DataFrame:
    final_columns = EVENT_COLUMNS

    if {"event_title_vi", "event_code", "category"}.issubset(df.columns):
        df_silver = _normalize_vnstock_events(df)
        for column in final_columns:
            if column not in df_silver.columns:
                df_silver[column] = None
        return df_silver[final_columns]

    final_columns = [
        "ticker",
        "event_id",
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

    df_silver = df.copy()
    if "event_type" not in df_silver.columns and "event_list_name" in df_silver.columns:
        df_silver["event_type"] = df_silver["event_list_name"]
    if "event_list_name" not in df_silver.columns and "event_type" in df_silver.columns:
        df_silver["event_list_name"] = df_silver["event_type"]

    for column in final_columns:
        if column not in df_silver.columns:
            df_silver[column] = None

    return df_silver[final_columns]

def normalize_ratio_summary(df: pd.DataFrame) -> pd.DataFrame:
    df_silver = df.copy()

    if "ticker" not in df_silver.columns and "symbol" in df_silver.columns:
        df_silver["ticker"] = df_silver["symbol"]

    if "ticker" in df_silver.columns:
        df_silver["ticker"] = df_silver["ticker"].astype(str).str.strip().str.upper()

    for column in ["year", "quarter", "year_report"]:
        if column in df_silver.columns:
            df_silver[column] = pd.to_numeric(df_silver[column], errors="coerce").astype("Int64")

    if "date_fetched" in df_silver.columns:
        df_silver["date_fetched"] = pd.to_datetime(
            df_silver["date_fetched"],
            errors="coerce",
        )

    preferred_columns = [
        "ticker",
        "year",
        "quarter",
        "ratio_type",
        "ratio_ttm_id",
        "ratio_year_id",
        "organ_code",
        "year_report",
        "number_of_shares_mkt_cap",
        "market_cap",
        "dividend_yield",
        "pe",
        "pb",
        "ps",
        "price_to_cash_flow",
        "ev_to_ebitda",
        "roe",
        "roa",
        "roic",
        "owners_equity",
        "debt_per_equity",
        "debt_to_equity",
        "gross_margin",
        "ebit_margin",
        "pre_tax_profit_margin",
        "after_tax_profit_margin",
        "asset_turnover",
        "financial_leverage",
        "ebit",
        "ebitda",
        "equity",
        "date_fetched",
    ]
    remaining_columns = [
        column
        for column in df_silver.columns
        if column not in preferred_columns and column != "symbol"
    ]
    final_columns = [
        column
        for column in preferred_columns + remaining_columns
        if column in df_silver.columns
    ]

    return df_silver[final_columns].drop_duplicates(
        subset=["ticker", "year", "quarter", "ratio_type"],
        keep="last",
    )

def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for column in columns:
        if column not in out.columns:
            out[column] = None
    return out


def _normalize_quantity_million(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "quantity" not in out.columns:
        out["quantity"] = None
        return out

    quantity = pd.to_numeric(out["quantity"], errors="coerce")
    out["quantity"] = (quantity / 1_000_000).round(3)
    return out


def normalize_shareholders(df: pd.DataFrame) -> pd.DataFrame:
    columns = ["ticker", "share_holder", "quantity", "share_own_percent", "update_date"]
    df = _ensure_columns(_normalize_quantity_million(df), columns)
    return df[columns]


def normalize_officers(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "officer_own_quantity" not in df.columns and "quantity" in df.columns:
        df["officer_own_quantity"] = df["quantity"]

    columns = [
        "ticker",
        "officer_name",
        "officer_position",
        "officer_own_quantity",
        "officer_own_percent",
        "update_date",
    ]
    df = _ensure_columns(df, columns)
    return df[columns]


OVERVIEW_COLUMNS = [
    "ticker",
    "organ_code",
    "name",
    "organ_name",
    "organ_short_name",
    "trading_floor",
    "industry",
    "subindustry",
    "history",
    "company_profile",
    "issue_share",
    "market_cap",
    "current_price",
    "cap_group",
    "sector",
    "icb_code_lv2",
    "icb_code_lv4",
    "free_float",
    "free_float_percentage",
    "listing_date",
    "foreign_percentage",
    "maximum_foreign_percentage",
    "state_percentage",
    "is_bank",
    "date_fetched",
]


def _first_present(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    result = pd.Series([None] * len(df), index=df.index, dtype="object")
    for column in columns:
        if column in df.columns:
            result = result.combine_first(df[column])
    return result


def _normalize_listing(value):
    if pd.isna(value):
        return None
    listing = str(value).strip().upper()
    aliases = {
        "HSX": "HOSE",
        "HOSE": "HOSE",
        "HNX": "HNX",
        "UPCOM": "UPCOM",
    }
    return aliases.get(listing, listing or None)


def _cap_group_from_row(row) -> str | None:
    text = " ".join(
        str(row.get(column) or "")
        for column in ["tag", "com_group_code", "sector", "listing"]
    ).upper()
    if "VN30" in text:
        return "VN30"
    if "VN100" in text:
        return "VN100"
    return None


def normalize_overview(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=OVERVIEW_COLUMNS)

    df_silver = df.copy()
    df_silver["ticker"] = _first_present(df_silver, ["ticker", "symbol"])
    df_silver["ticker"] = df_silver["ticker"].astype(str).str.strip().str.upper()
    df_silver = df_silver[
        df_silver["ticker"].ne("") & df_silver["ticker"].ne("NAN")
    ].copy()

    df_silver["name"] = _first_present(
        df_silver,
        ["organ_short_name", "organ_name", "name", "ticker"],
    )
    df_silver["trading_floor"] = _first_present(
        df_silver,
        ["trading_floor", "listing", "exchange"],
    ).map(_normalize_listing)
    df_silver["industry"] = _first_present(
        df_silver,
        ["industry", "sector", "icb_name2", "icb_code_lv2"],
    )
    df_silver["subindustry"] = _first_present(
        df_silver,
        ["subindustry", "icb_name3", "icb_code_lv4"],
    )
    df_silver["history"] = _first_present(
        df_silver,
        ["history", "company_profile"],
    )
    df_silver["foreign_percentage"] = _first_present(
        df_silver,
        ["foreign_percentage", "foreigner_percentage"],
    )
    df_silver["cap_group"] = _first_present(df_silver, ["cap_group"])
    missing_cap_group = df_silver["cap_group"].isna()
    if missing_cap_group.any():
        df_silver.loc[missing_cap_group, "cap_group"] = df_silver.loc[
            missing_cap_group
        ].apply(_cap_group_from_row, axis=1)

    for column in [
        "issue_share",
        "market_cap",
        "current_price",
        "free_float",
        "free_float_percentage",
        "foreign_percentage",
        "maximum_foreign_percentage",
        "state_percentage",
    ]:
        if column in df_silver.columns:
            df_silver[column] = pd.to_numeric(df_silver[column], errors="coerce")

    for column in ["date_fetched", "listing_date"]:
        if column in df_silver.columns:
            df_silver[column] = pd.to_datetime(df_silver[column], errors="coerce")

    df_silver = df_silver.drop_duplicates(subset=["ticker"], keep="last")
    for column in OVERVIEW_COLUMNS:
        if column not in df_silver.columns:
            df_silver[column] = None

    return df_silver[OVERVIEW_COLUMNS].reset_index(drop=True)

def normalize_info(df: pd.DataFrame, info_type: str = "overview") -> pd.DataFrame:
    func_name = f"normalize_{info_type}"
    try:
        func = globals()[func_name]
    except KeyError:
        raise ValueError(f"Unsupported info_type: {info_type}")
    return func(df)
