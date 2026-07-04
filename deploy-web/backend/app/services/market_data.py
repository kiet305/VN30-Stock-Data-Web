from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from math import isfinite
import unicodedata

from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.schemas import (
    Candle,
    ChartAnnotation,
    DividendEvent,
    FinancialDashboard,
    FinancialMetricSeries,
    FinancialPoint,
    FinancialSeries,
    FinancialStatement,
    FinancialStatementPeriod,
    FinancialStatementRow,
    IndustryComparison,
    SectorConstituent,
    SectorOverviewItem,
    SectorOverviewResponse,
    StockInfo,
    StockOfficer,
    StockShareholder,
    StockValuation,
    ValuationBacktestPoint,
    ValuationBacktestResponse,
    ValuationRankingItem,
    ValuationRankingResponse,
)


settings = get_settings()
columns = settings.columns

FINANCIAL_SERIES_DEFINITIONS = [
    ("revenue", "Doanh thu", "tỷ đồng", "IS", ("total_operating_income", "revenue")),
    ("profit", "Lợi nhuận sau thuế", "tỷ đồng", "IS", ("net_profit_loss_after_tax", "profit")),
    ("profit_margin", "Biên lợi nhuận ròng", "%", "CALC", ("profit_margin",)),
    (
        "cf_operating",
        "Dòng tiền kinh doanh",
        "tỷ đồng",
        "CF",
        ("cashflow_operating", "net_cash_from_operating_activities", "cf_operating"),
    ),
    (
        "cf_investment",
        "Dòng tiền đầu tư",
        "tỷ đồng",
        "CF",
        ("cashflow_investing", "net_cash_from_investing_activities", "cf_investment"),
    ),
    (
        "cf_finance",
        "Dòng tiền tài chính",
        "tỷ đồng",
        "CF",
        ("cashflow_financing", "net_cash_from_financing_activities", "cf_finance"),
    ),
    (
        "net_cf",
        "Lưu chuyển tiền thuần",
        "tỷ đồng",
        "CF",
        ("net_cashflow", "net_increase_decrease_in_cash_and_cash_equivalents", "net_cf"),
    ),
    ("total_assets", "Tổng tài sản", "tỷ đồng", "BS", ("total_assets",)),
    ("liabilities", "Nợ phải trả", "tỷ đồng", "BS", ("total_liabilities", "liabilities")),
    ("equity", "Vốn chủ sở hữu", "tỷ đồng", "BS", ("owners_equity", "equity")),
]

FINANCIAL_CRITERIA = sorted(
    {
        criteria
        for _, _, _, report_type, criteria_list in FINANCIAL_SERIES_DEFINITIONS
        for criteria in criteria_list
        if report_type != "CALC"
    }
)

FINANCIAL_STATEMENT_LABELS = {
    "BS": "Cân đối kế toán",
    "IS": "Báo cáo thu nhập",
    "CF": "Lưu chuyển tiền tệ",
    "RATIO": "Chỉ số tài chính",
}

FINANCIAL_STATEMENT_ORDER = {"BS": 0, "IS": 1, "CF": 2, "RATIO": 3}

FINANCIAL_METRIC_DEFINITIONS = [
    ("eps", "EPS", "đ/CP"),
    ("bvps", "BVPS", "đ/CP"),
    ("roe", "ROE", "%"),
    ("roa", "ROA", "%"),
    ("roic", "ROIC", "%"),
    ("gross_margin", "Biên lợi nhuận gộp", "%"),
    ("ebit_margin", "Biên EBIT", "%"),
    ("pre_tax_profit_margin", "Biên lợi nhuận trước thuế", "%"),
    ("after_tax_profit_margin", "Biên lợi nhuận sau thuế", "%"),
    ("debt_per_equity", "Nợ / vốn chủ sở hữu", "x"),
    ("debt_to_equity", "Nợ / vốn chủ sở hữu", "x"),
    ("financial_leverage", "Đòn bẩy tài chính", "x"),
    ("asset_turnover", "Vòng quay tài sản", "x"),
    ("dividend_yield", "Tỷ suất cổ tức", "%"),
    ("net_interest_margin", "NIM", "%"),
    ("average_yield_on_earning_assets", "Yield tài sản sinh lãi", "%"),
    ("average_cost_of_financing", "Chi phí vốn bình quân", "%"),
    ("cost_to_income", "Cost to income", "%"),
]

MARKET_FINANCIAL_METRIC_DEFINITIONS = [
    ("pe", "P/E", "x"),
    ("pb", "P/B", "x"),
]

VALUATION_METHOD = "Blend 55% multiples (72,7% P/E-P/B + 27,3% EV/EBITDA ước tính; hiệu dụng 40%/15%) + 45% DCF chuẩn hoá từ CFO-CapEx trong BCTC"
BANK_VALUATION_METHOD = "Ngân hàng: 65% P/B điều chỉnh ROE ngành + 35% P/E ngành, loại DCF và EV/EBITDA"
DEFAULT_DCF_WEIGHT = 0.45
DEFAULT_MULTIPLE_WEIGHT = 0.55
DEFAULT_PE_PB_MULTIPLE_WEIGHT = 0.40 / DEFAULT_MULTIPLE_WEIGHT
DEFAULT_EV_EBITDA_MULTIPLE_WEIGHT = 0.15 / DEFAULT_MULTIPLE_WEIGHT
BANK_TICKERS = {
    "ACB",
    "BID",
    "CTG",
    "EIB",
    "HDB",
    "LPB",
    "MBB",
    "OCB",
    "SHB",
    "SSB",
    "STB",
    "TCB",
    "TPB",
    "VCB",
    "VIB",
    "VPB",
}


def _qualified_table(table_name: str) -> str:
    schema = settings._validate_identifier(settings.postgres_schema)
    table = settings._validate_identifier(table_name)
    return f"{schema}.{table}"


def _warehouse_columns(table_name: str) -> set[str]:
    query = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = :schema
          AND table_name = :table
        """
    )

    with engine.connect() as conn:
        return {
            str(row["column_name"])
            for row in conn.execute(
                query,
                {
                    "schema": settings.postgres_schema,
                    "table": table_name,
                },
            ).mappings()
        }


def _optional_column(table_columns: set[str], column_name: str, sql_type: str) -> str:
    if column_name not in table_columns:
        return f"NULL::{sql_type}"

    column = settings._validate_identifier(column_name)
    return f"events.{column}::{sql_type}"


def _optional_date_column(table_columns: set[str], column_name: str) -> str:
    if column_name not in table_columns:
        return "NULL::date"

    column = settings._validate_identifier(column_name)
    return f"NULLIF(events.{column}::text, '')::date"


def _optional_table_column(
    table_columns: set[str],
    table_alias: str,
    column_name: str,
    sql_type: str,
) -> str:
    if column_name not in table_columns:
        return f"NULL::{sql_type}"

    column = settings._validate_identifier(column_name)
    return f"{table_alias}.{column}::{sql_type}"


def _optional_table_date_column(table_columns: set[str], table_alias: str, column_name: str) -> str:
    if column_name not in table_columns:
        return "NULL::date"

    column = settings._validate_identifier(column_name)
    return f"NULLIF({table_alias}.{column}::text, '')::date"


def _first_existing_column(table_columns: set[str], candidates: tuple[str, ...]) -> str | None:
    return next((column for column in candidates if column in table_columns), None)


def _optional_first_table_column(
    table_columns: set[str],
    table_alias: str,
    candidates: tuple[str, ...],
    sql_type: str,
) -> str:
    column_name = _first_existing_column(table_columns, candidates)
    if column_name is None:
        return f"NULL::{sql_type}"

    column = settings._validate_identifier(column_name)
    return f"{table_alias}.{column}::{sql_type}"


def get_tickers() -> list[str]:
    query = text(
        f"""
        SELECT DISTINCT {columns["ticker"]} AS ticker
        FROM {settings.qualified_table}
        WHERE {columns["ticker"]} IS NOT NULL
        ORDER BY {columns["ticker"]}
        """
    )
    with engine.connect() as conn:
        return [row[0] for row in conn.execute(query).fetchall()]


def get_candles(
    ticker: str,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 200,
) -> list[Candle]:
    ticker_column = columns["ticker"]
    date_column = columns["date"]
    open_column = columns["open"]
    high_column = columns["high"]
    low_column = columns["low"]
    close_column = columns["close"]
    volume_column = columns["volume"]

    filters = [f"{ticker_column} = :ticker"]
    params: dict[str, object] = {"ticker": ticker.upper()}

    if start_date is not None:
        filters.append(f"{date_column} >= :start_date")
        params["start_date"] = start_date

    if end_date is not None:
        filters.append(f"{date_column} <= :end_date")
        params["end_date"] = end_date

    has_date_range = start_date is not None or end_date is not None
    limit_clause = "" if has_date_range else "LIMIT :limit"
    if not has_date_range:
        params["limit"] = limit

    completeness_score = " + ".join(
        [
            f"({open_column} IS NOT NULL)::int",
            f"({high_column} IS NOT NULL)::int",
            f"({low_column} IS NOT NULL)::int",
            f"({close_column} IS NOT NULL)::int",
            f"({volume_column} IS NOT NULL)::int",
        ]
    )

    query = text(
        f"""
        SELECT ticker, date, open, high, low, close, volume
        FROM (
            SELECT DISTINCT ON ({date_column})
                {ticker_column} AS ticker,
                {date_column} AS date,
                {open_column} AS open,
                {high_column} AS high,
                {low_column} AS low,
                {close_column} AS close,
                {volume_column} AS volume
            FROM {settings.qualified_table}
            WHERE {' AND '.join(filters)}
            ORDER BY {date_column} DESC, ({completeness_score}) DESC
        ) AS deduped
        ORDER BY date DESC
        {limit_clause}
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().all()

    candles = [Candle(**row) for row in rows]
    candles.reverse()
    return candles


def _to_float(value: object) -> float | None:
    if value is None:
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return number if isfinite(number) else None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _normalize_text(value: object) -> str:
    if value is None:
        return ""

    text_value = str(value).casefold()
    normalized = unicodedata.normalize("NFD", text_value)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _repair_mojibake(value: object) -> str | None:
    if value is None:
        return None

    text_value = str(value)
    mojibake_markers = ("Ã", "Â", "Ä", "Æ", "áº", "á»")
    if not any(marker in text_value for marker in mojibake_markers):
        return text_value

    try:
        repaired = text_value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return text_value

    if sum(repaired.count(marker) for marker in mojibake_markers) < sum(
        text_value.count(marker) for marker in mojibake_markers
    ):
        return repaired

    return text_value


def _is_bank(ticker: str, industry: object, subindustry: object) -> bool:
    if ticker.upper() in BANK_TICKERS:
        return True

    normalized_text = f"{_normalize_text(industry)} {_normalize_text(subindustry)}"
    raw_text = f"{industry or ''} {subindustry or ''}".casefold()
    return "ngan hang" in normalized_text or "ngân hàng" in raw_text or "ngã¢n hã ng" in raw_text or "ngã¢n" in raw_text


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous <= 0:
        return None

    return current / previous - 1


def _compound_growth(growth: float | None, years: float) -> float | None:
    if growth is None:
        return None

    growth = _clamp(growth, -0.8, 1.5)
    return (1 + growth) ** years - 1


def _sum_values(
    values_by_period: dict[tuple[int, int, str, str], float | None],
    periods: list[tuple[int, int]],
    report_type: str,
    criteria: str,
) -> float | None:
    values: list[float] = []
    for year, quarter in periods:
        value = values_by_period.get((year, quarter, report_type, criteria))
        if value is None:
            return None
        values.append(value)

    return sum(values)


def _period_growth(
    values_by_period: dict[tuple[int, int, str, str], float | None],
    periods: list[tuple[int, int]],
    report_type: str,
    criteria: str,
    trailing_periods: int,
) -> float | None:
    if len(periods) < trailing_periods:
        return None

    recent_periods = periods[-trailing_periods:]
    previous_year_periods = [(year - 1, quarter) for year, quarter in recent_periods]
    recent_value = _sum_values(values_by_period, recent_periods, report_type, criteria)
    previous_value = _sum_values(values_by_period, previous_year_periods, report_type, criteria)
    growth = _growth(recent_value, previous_value)
    if growth is not None:
        return growth

    if len(periods) < trailing_periods * 2:
        return None

    previous_periods = periods[-trailing_periods * 2 : -trailing_periods]
    previous_value = _sum_values(values_by_period, previous_periods, report_type, criteria)
    return _growth(recent_value, previous_value)


def _latest_value(
    values_by_period: dict[tuple[int, int, str, str], float | None],
    periods: list[tuple[int, int]],
    report_type: str,
    criteria: str,
) -> float | None:
    for year, quarter in reversed(periods):
        value = values_by_period.get((year, quarter, report_type, criteria))
        if value is not None:
            return value

    return None


def _weighted_average(values: list[tuple[float | None, float]]) -> float | None:
    usable_values = [(value, weight) for value, weight in values if value is not None and weight > 0]
    total_weight = sum(weight for _, weight in usable_values)
    if total_weight == 0:
        return None

    return sum((value or 0) * weight for value, weight in usable_values) / total_weight


def _upside(target_price: float | None, current_price: float | None) -> float | None:
    if target_price is None or current_price is None or current_price <= 0:
        return None

    return (target_price / current_price - 1) * 100


def _premium(value: float | None, benchmark: float | None) -> float | None:
    if value is None or benchmark is None or benchmark == 0:
        return None

    return (value / benchmark - 1) * 100


def _trailing_ebitda_proxy(
    values_by_period: dict[tuple[int, int, str, str], float | None],
    periods: list[tuple[int, int]],
) -> float | None:
    revenue = _trailing_sum(values_by_period, periods, "IS", "revenue")
    cogs = _trailing_sum(values_by_period, periods, "IS", "cogs")
    sales_expenses = _trailing_sum(values_by_period, periods, "IS", "sales_expenses") or 0
    admin_expenses = _trailing_sum(values_by_period, periods, "IS", "admin_expenses") or 0
    if revenue is not None and cogs is not None:
        operating_profit = revenue + cogs + sales_expenses + admin_expenses
        if operating_profit > 0:
            return operating_profit

    trailing_profit = _trailing_sum(values_by_period, periods, "IS", "profit")
    return trailing_profit if trailing_profit is not None and trailing_profit > 0 else None


def _enterprise_value(
    market_cap: float | None,
    liabilities: float | None,
    cash: float | None,
) -> tuple[float | None, float | None]:
    if market_cap is None or market_cap <= 0 or liabilities is None:
        return None, None

    net_debt = liabilities - (cash or 0)
    return market_cap + net_debt, net_debt


def _ev_ebitda_target_price(
    trailing_ebitda: float | None,
    growth: float | None,
    benchmark: float | None,
    net_debt: float | None,
    issue_share: float | None,
) -> float | None:
    if (
        trailing_ebitda is None
        or trailing_ebitda <= 0
        or benchmark is None
        or benchmark <= 0
        or issue_share is None
        or issue_share <= 0
    ):
        return None

    target_ebitda = trailing_ebitda * (1 + (growth or 0))
    equity_value = target_ebitda * benchmark - (net_debt or 0)
    if equity_value <= 0:
        return None

    return equity_value * 1_000_000 / issue_share


def _bank_multiple_target_price(
    eps: float | None,
    bvps: float | None,
    pe: float | None,
    pb: float | None,
    industry_pe: float | None,
    industry_pb: float | None,
    roe: float | None,
    industry_roe: float | None,
    earnings_growth: float | None,
    book_growth: float | None,
) -> float | None:
    pe_benchmark = industry_pe if industry_pe is not None and industry_pe > 0 else pe
    pb_benchmark = industry_pb if industry_pb is not None and industry_pb > 0 else pb

    if pe_benchmark is not None:
        pe_benchmark = _clamp(pe_benchmark, 4, 18)
    if pb_benchmark is not None:
        roe_adjustment = 1.0
        if roe is not None and industry_roe is not None and industry_roe > 0:
            roe_adjustment = _clamp(roe / industry_roe, 0.75, 1.2)
        pb_benchmark = _clamp(pb_benchmark * roe_adjustment, 0.4, 3.0)

    pe_target = (
        eps * (1 + (earnings_growth or 0)) * pe_benchmark / 1000
        if eps is not None and eps > 0 and pe_benchmark is not None
        else None
    )
    pb_target = (
        bvps * (1 + (book_growth or 0)) * pb_benchmark / 1000
        if bvps is not None and bvps > 0 and pb_benchmark is not None
        else None
    )

    return _weighted_average([(pb_target, 0.65), (pe_target, 0.35)])


def _trailing_sum(
    values_by_period: dict[tuple[int, int, str, str], float | None],
    periods: list[tuple[int, int]],
    report_type: str,
    criteria: str,
    limit: int = 4,
) -> float | None:
    return _sum_values(values_by_period, periods[-limit:], report_type, criteria) if len(periods) >= limit else None


def _trailing_first_sum(
    values_by_period: dict[tuple[int, int, str, str], float | None],
    periods: list[tuple[int, int]],
    report_type: str,
    criteria_list: tuple[str, ...],
    limit: int = 4,
) -> float | None:
    for criteria in criteria_list:
        value = _trailing_sum(values_by_period, periods, report_type, criteria, limit)
        if value is not None:
            return value
    return None


def _dcf_target_price(
    values_by_period: dict[tuple[int, int, str, str], float | None],
    periods: list[tuple[int, int]],
    issue_share: float | None,
    growth_12m: float | None,
    equity: float | None,
    liabilities: float | None,
) -> tuple[float | None, float | None, float | None, float | None]:
    if issue_share is None or issue_share <= 0 or len(periods) < 4:
        return None, None, None, None

    trailing_profit = _trailing_sum(values_by_period, periods, "IS", "profit")
    trailing_revenue = _trailing_sum(values_by_period, periods, "IS", "revenue")
    trailing_cfo = _trailing_first_sum(
        values_by_period,
        periods,
        "CF",
        ("cashflow_operating", "net_cash_from_operating_activities", "cf_operating"),
    )
    trailing_capex = _trailing_sum(values_by_period, periods, "CF", "fixed_assets_purchases")

    raw_fcf = None
    if trailing_cfo is not None and trailing_capex is not None:
        raw_fcf = trailing_cfo + trailing_capex

    fallback_fcf = None
    if trailing_profit is not None and trailing_profit > 0:
        fallback_fcf = trailing_profit * 0.65
    elif trailing_revenue is not None and trailing_revenue > 0:
        fallback_fcf = trailing_revenue * 0.06

    if raw_fcf is not None and raw_fcf > 0:
        normalized_fcf = raw_fcf
    else:
        normalized_fcf = fallback_fcf

    if normalized_fcf is None or normalized_fcf <= 0:
        return None, None, None, None

    leverage = 0.0
    if equity is not None and liabilities is not None and equity > 0:
        leverage = _clamp(liabilities / equity, 0, 2)

    discount_rate = _clamp(0.105 + leverage * 0.018, 0.095, 0.16)
    projection_growth = _clamp(growth_12m if growth_12m is not None else 0.06, -0.03, 0.18)
    terminal_growth = _clamp(projection_growth * 0.25, 0.01, 0.04)

    present_value = 0.0
    for year in range(1, 6):
        fade = (5 - year) / 4
        year_growth = terminal_growth + (projection_growth - terminal_growth) * fade
        cash_flow = normalized_fcf * ((1 + year_growth) ** year)
        present_value += cash_flow / ((1 + discount_rate) ** year)

    year_five_growth = terminal_growth + (projection_growth - terminal_growth) * 0
    terminal_cash_flow = normalized_fcf * ((1 + year_five_growth) ** 5) * (1 + terminal_growth)
    terminal_value = terminal_cash_flow / max(discount_rate - terminal_growth, 0.01)
    present_value += terminal_value / ((1 + discount_rate) ** 5)

    target_price = present_value * 1_000_000 / issue_share
    return target_price, discount_rate, terminal_growth, normalized_fcf


def get_stock_valuation(ticker: str) -> StockValuation | None:
    ticker = ticker.upper()
    price_table = settings.qualified_table
    metric_table = _qualified_table("warehouse_ticker_metric")
    reports_table = _qualified_table("warehouse_reports")
    overview_table = _qualified_table("warehouse_overview")

    query = text(
        f"""
        WITH latest_price AS (
            SELECT
                {columns["close"]}::double precision AS close,
                market_cap::double precision AS market_cap,
                CASE WHEN pe::text ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN pe::double precision ELSE NULL END AS pe,
                CASE WHEN pb::text ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN pb::double precision ELSE NULL END AS pb
            FROM {price_table}
            WHERE {columns["ticker"]} = :ticker
              AND {columns["close"]} IS NOT NULL
            ORDER BY {columns["date"]} DESC
            LIMIT 1
        ),
        latest_metric AS (
            SELECT
                eps::double precision AS eps,
                bvps::double precision AS bvps,
                roe::double precision AS roe,
                roa::double precision AS roa,
                ros::double precision AS ros,
                industry,
                roe_industry::double precision AS roe_industry,
                roa_industry::double precision AS roa_industry,
                ros_industry::double precision AS ros_industry
            FROM {metric_table}
            WHERE ticker = :ticker
            ORDER BY year DESC NULLS LAST, quarter DESC NULLS LAST
            LIMIT 1
        ),
        latest_overview AS (
            SELECT industry, subindustry, issue_share
            FROM {overview_table} AS overview
            WHERE ticker = :ticker
            ORDER BY date_fetched DESC NULLS LAST
            LIMIT 1
        ),
        latest_overview_by_ticker AS (
            SELECT DISTINCT ON (ticker)
                ticker,
                industry
            FROM {overview_table} AS overview
            WHERE industry IS NOT NULL
            ORDER BY ticker, date_fetched DESC NULLS LAST
        ),
        latest_price_by_ticker AS (
            SELECT DISTINCT ON ({columns["ticker"]})
                {columns["ticker"]} AS ticker,
                market_cap::double precision AS market_cap,
                CASE WHEN pe::text ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN pe::double precision ELSE NULL END AS pe,
                CASE WHEN pb::text ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN pb::double precision ELSE NULL END AS pb
            FROM {price_table}
            WHERE {columns["ticker"]} IS NOT NULL
              AND {columns["ticker"]} NOT LIKE '%INDEX'
            ORDER BY {columns["ticker"]}, {columns["date"]} DESC
        ),
        industry_metrics AS (
            SELECT
                AVG(price.pe) FILTER (WHERE price.pe > 0 AND price.pe < 80) AS industry_pe,
                AVG(price.pb) FILTER (WHERE price.pb > 0 AND price.pb < 20) AS industry_pb,
                COUNT(*) FILTER (WHERE price.pe > 0 OR price.pb > 0) AS peer_count
            FROM latest_price_by_ticker AS price
            INNER JOIN latest_overview_by_ticker AS overview
                ON overview.ticker = price.ticker
            WHERE overview.industry = COALESCE((SELECT industry FROM latest_overview), (SELECT industry FROM latest_metric))
              AND price.ticker <> :ticker
        ),
        peer_periods AS (
            SELECT
                distinct_periods.ticker,
                distinct_periods.year,
                distinct_periods.quarter,
                ROW_NUMBER() OVER (
                    PARTITION BY distinct_periods.ticker
                    ORDER BY distinct_periods.year DESC, distinct_periods.quarter DESC
                ) AS period_rank
            FROM (
                SELECT DISTINCT ticker, year, quarter
                FROM {reports_table}
                WHERE ticker IS NOT NULL
            ) AS distinct_periods
            INNER JOIN latest_overview_by_ticker AS overview
                ON overview.ticker = distinct_periods.ticker
            WHERE overview.industry = COALESCE((SELECT industry FROM latest_overview), (SELECT industry FROM latest_metric))
              AND distinct_periods.ticker <> :ticker
        ),
        peer_income AS (
            SELECT
                reports.ticker,
                SUM(reports.value::double precision) FILTER (WHERE reports.criteria = 'revenue') AS revenue,
                SUM(reports.value::double precision) FILTER (WHERE reports.criteria IN ('cost_of_goods_sold', 'cogs')) AS cogs,
                SUM(reports.value::double precision) FILTER (WHERE reports.criteria IN ('selling_expenses', 'sales_expenses')) AS sales_expenses,
                SUM(reports.value::double precision) FILTER (WHERE reports.criteria IN ('general_admin_expenses', 'admin_expenses')) AS admin_expenses,
                SUM(reports.value::double precision) FILTER (WHERE reports.criteria = 'profit') AS profit
            FROM {reports_table} AS reports
            INNER JOIN peer_periods
                ON peer_periods.ticker = reports.ticker
               AND peer_periods.year = reports.year
               AND peer_periods.quarter = reports.quarter
               AND peer_periods.period_rank <= 4
            WHERE reports.report_type = 'IS'
              AND reports.criteria IN ('revenue', 'cost_of_goods_sold', 'cogs', 'selling_expenses', 'sales_expenses', 'general_admin_expenses', 'admin_expenses', 'profit')
            GROUP BY reports.ticker
        ),
        peer_latest_balance AS (
            SELECT
                ticker,
                MAX(value) FILTER (WHERE criteria = 'liabilities') AS liabilities
            FROM (
                SELECT DISTINCT ON (ticker, criteria)
                    ticker,
                    criteria,
                    value::double precision AS value
                FROM {reports_table}
                WHERE report_type = 'BS'
                  AND criteria = 'liabilities'
                  AND ticker IN (SELECT DISTINCT ticker FROM peer_periods)
                ORDER BY ticker, criteria, year DESC, quarter DESC
            ) AS latest_balance
            GROUP BY ticker
        ),
        peer_latest_cash AS (
            SELECT DISTINCT ON (ticker)
                ticker,
                value::double precision AS cash
            FROM {reports_table}
            WHERE report_type = 'CF'
              AND criteria IN ('cash_ending', 'cash_and_cash_equivalents', 'cash')
              AND ticker IN (SELECT DISTINCT ticker FROM peer_periods)
            ORDER BY ticker, year DESC, quarter DESC
        ),
        industry_ev_ebitda_metrics AS (
            SELECT
                AVG(peer.ev_ebitda) FILTER (WHERE peer.ev_ebitda > 0 AND peer.ev_ebitda < 50) AS industry_ev_ebitda
            FROM (
                SELECT
                    price.ticker,
                    (price.market_cap + balance.liabilities - COALESCE(cash.cash, 0))
                    / NULLIF(
                        CASE
                            WHEN income.revenue IS NOT NULL AND income.cogs IS NOT NULL THEN
                                income.revenue
                                + income.cogs
                                + COALESCE(income.sales_expenses, 0)
                                + COALESCE(income.admin_expenses, 0)
                            ELSE income.profit
                        END,
                        0
                    ) AS ev_ebitda
                FROM latest_price_by_ticker AS price
                INNER JOIN latest_overview_by_ticker AS overview
                    ON overview.ticker = price.ticker
                INNER JOIN peer_income AS income
                    ON income.ticker = price.ticker
                INNER JOIN peer_latest_balance AS balance
                    ON balance.ticker = price.ticker
                LEFT JOIN peer_latest_cash AS cash
                    ON cash.ticker = price.ticker
                WHERE overview.industry = COALESCE((SELECT industry FROM latest_overview), (SELECT industry FROM latest_metric))
                  AND price.ticker <> :ticker
                  AND price.market_cap > 0
                  AND balance.liabilities IS NOT NULL
            ) AS peer
        ),
        selected_periods AS (
            SELECT DISTINCT year, quarter
            FROM {reports_table}
            WHERE ticker = :ticker
            ORDER BY year DESC, quarter DESC
            LIMIT 8
        )
        SELECT
            'market' AS source,
            NULL::int AS year,
            NULL::int AS quarter,
            NULL::text AS report_type,
            NULL::text AS criteria,
            latest_price.close,
            latest_price.market_cap,
            latest_price.pe,
            latest_price.pb,
            latest_metric.eps,
            latest_metric.bvps,
            latest_metric.roe,
            latest_metric.roa,
            latest_metric.ros,
            latest_metric.roe_industry,
            latest_metric.roa_industry,
            latest_metric.ros_industry,
            COALESCE(latest_overview.industry, latest_metric.industry) AS industry,
            latest_overview.subindustry,
            latest_overview.issue_share,
            industry_metrics.industry_pe,
            industry_metrics.industry_pb,
            industry_metrics.peer_count,
            industry_ev_ebitda_metrics.industry_ev_ebitda,
            NULL::double precision AS value
        FROM latest_price
        LEFT JOIN latest_metric ON TRUE
        LEFT JOIN latest_overview ON TRUE
        LEFT JOIN industry_metrics ON TRUE
        LEFT JOIN industry_ev_ebitda_metrics ON TRUE
        UNION ALL
        SELECT
            'report' AS source,
            reports.year,
            reports.quarter,
            reports.report_type,
            reports.criteria,
            NULL::double precision AS close,
            NULL::double precision AS market_cap,
            NULL::double precision AS pe,
            NULL::double precision AS pb,
            NULL::double precision AS eps,
            NULL::double precision AS bvps,
            NULL::double precision AS roe,
            NULL::double precision AS roa,
            NULL::double precision AS ros,
            NULL::double precision AS roe_industry,
            NULL::double precision AS roa_industry,
            NULL::double precision AS ros_industry,
            NULL::text AS industry,
            NULL::text AS subindustry,
            NULL::bigint AS issue_share,
            NULL::double precision AS industry_pe,
            NULL::double precision AS industry_pb,
            NULL::bigint AS peer_count,
            NULL::double precision AS industry_ev_ebitda,
            reports.value::double precision AS value
        FROM {reports_table} AS reports
        INNER JOIN selected_periods
            ON selected_periods.year = reports.year
           AND selected_periods.quarter = reports.quarter
        WHERE reports.ticker = :ticker
          AND (
              (reports.report_type = 'IS' AND reports.criteria IN ('profit', 'revenue', 'cost_of_goods_sold', 'cogs', 'selling_expenses', 'sales_expenses', 'general_admin_expenses', 'admin_expenses'))
              OR (reports.report_type = 'BS' AND reports.criteria IN ('equity', 'liabilities', 'cash_and_cash_equivalents', 'cash'))
              OR (reports.report_type = 'CF' AND reports.criteria IN ('cashflow_operating', 'cashflow_investing', 'cashflow_financing', 'net_cashflow', 'cf_operating', 'cf_investment', 'cf_finance', 'net_cf', 'cash_ending', 'cash'))
          )
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(query, {"ticker": ticker}).mappings().all()

    if not rows:
        return None

    market_row = next((row for row in rows if row["source"] == "market"), None)
    report_rows = [row for row in rows if row["source"] == "report"]
    if market_row is None or not report_rows:
        return None

    periods = sorted({(int(row["year"]), int(row["quarter"])) for row in report_rows})
    values_by_period = {
        (int(row["year"]), int(row["quarter"]), str(row["report_type"]), str(row["criteria"])): _to_float(row["value"])
        for row in report_rows
    }

    current_price = _to_float(market_row["close"])
    market_cap = _to_float(market_row["market_cap"])
    eps = _to_float(market_row["eps"])
    bvps = _to_float(market_row["bvps"])
    pe = _to_float(market_row["pe"])
    pb = _to_float(market_row["pb"])
    issue_share = _to_float(market_row["issue_share"])
    industry_pe = _to_float(market_row["industry_pe"])
    industry_pb = _to_float(market_row["industry_pb"])
    peer_count = int(market_row["peer_count"] or 0)
    industry_ev_ebitda = _to_float(market_row["industry_ev_ebitda"])
    roe = _to_float(market_row["roe"])
    roa = _to_float(market_row["roa"])
    ros = _to_float(market_row["ros"])
    roe_industry = _to_float(market_row["roe_industry"])
    roa_industry = _to_float(market_row["roa_industry"])
    ros_industry = _to_float(market_row["ros_industry"])
    is_bank = _is_bank(ticker, market_row["industry"], market_row["subindustry"])

    profit_growth_6m = _period_growth(values_by_period, periods, "IS", "profit", trailing_periods=2)
    profit_growth_12m = _period_growth(values_by_period, periods, "IS", "profit", trailing_periods=4)
    revenue_growth_6m = _period_growth(values_by_period, periods, "IS", "revenue", trailing_periods=2)
    revenue_growth_12m = _period_growth(values_by_period, periods, "IS", "revenue", trailing_periods=4)
    equity_growth_12m = _period_growth(values_by_period, periods, "BS", "equity", trailing_periods=4)

    growth_6m = profit_growth_6m if profit_growth_6m is not None else revenue_growth_6m
    growth_12m = profit_growth_12m if profit_growth_12m is not None else revenue_growth_12m
    equity_growth_12m = 0.0 if equity_growth_12m is None else equity_growth_12m

    earnings_growth_6m = _compound_growth(growth_6m, 0.5)
    earnings_growth_12m = _compound_growth(growth_12m, 1.0)
    book_growth_6m = _compound_growth(equity_growth_12m, 0.5)
    book_growth_12m = _compound_growth(equity_growth_12m, 1.0)
    latest_equity = _latest_value(values_by_period, periods, "BS", "equity")
    latest_liabilities = _latest_value(values_by_period, periods, "BS", "liabilities")
    latest_cash = _latest_value(values_by_period, periods, "BS", "cash")
    if latest_cash is None:
        latest_cash = _latest_value(values_by_period, periods, "CF", "cash")
    trailing_ebitda = _trailing_ebitda_proxy(values_by_period, periods)
    enterprise_value, net_debt = _enterprise_value(market_cap, latest_liabilities, latest_cash)
    ev_ebitda = (
        enterprise_value / trailing_ebitda
        if enterprise_value is not None and enterprise_value > 0 and trailing_ebitda is not None and trailing_ebitda > 0
        else None
    )
    ev_ebitda_benchmark = industry_ev_ebitda if industry_ev_ebitda is not None else ev_ebitda

    pe = _clamp(pe, 3, 35) if pe is not None and pe > 0 else None
    pb = _clamp(pb, 0.2, 6) if pb is not None and pb > 0 else None
    eps_target_6m = (eps * (1 + (earnings_growth_6m or 0)) * pe / 1000) if eps and eps > 0 and pe else None
    eps_target_12m = (eps * (1 + (earnings_growth_12m or 0)) * pe / 1000) if eps and eps > 0 and pe else None
    bvps_target_6m = (bvps * (1 + (book_growth_6m or 0)) * pb / 1000) if bvps and bvps > 0 and pb else None
    bvps_target_12m = (bvps * (1 + (book_growth_12m or 0)) * pb / 1000) if bvps and bvps > 0 and pb else None

    pe_pb_target_price_6m = _weighted_average([(eps_target_6m, 0.7), (bvps_target_6m, 0.3)])
    pe_pb_target_price_12m = _weighted_average([(eps_target_12m, 0.7), (bvps_target_12m, 0.3)])
    ev_ebitda_target_price_6m = _ev_ebitda_target_price(
        trailing_ebitda=trailing_ebitda,
        growth=earnings_growth_6m,
        benchmark=ev_ebitda_benchmark,
        net_debt=net_debt,
        issue_share=issue_share,
    )
    ev_ebitda_target_price_12m = _ev_ebitda_target_price(
        trailing_ebitda=trailing_ebitda,
        growth=earnings_growth_12m,
        benchmark=ev_ebitda_benchmark,
        net_debt=net_debt,
        issue_share=issue_share,
    )
    multiple_target_price_6m = _weighted_average(
        [
            (pe_pb_target_price_6m, DEFAULT_PE_PB_MULTIPLE_WEIGHT),
            (ev_ebitda_target_price_6m, DEFAULT_EV_EBITDA_MULTIPLE_WEIGHT),
        ]
    )
    multiple_target_price_12m = _weighted_average(
        [
            (pe_pb_target_price_12m, DEFAULT_PE_PB_MULTIPLE_WEIGHT),
            (ev_ebitda_target_price_12m, DEFAULT_EV_EBITDA_MULTIPLE_WEIGHT),
        ]
    )
    dcf_target_price, discount_rate, terminal_growth, normalized_fcf = _dcf_target_price(
        values_by_period=values_by_period,
        periods=periods,
        issue_share=issue_share,
        growth_12m=growth_12m,
        equity=latest_equity,
        liabilities=latest_liabilities,
    )
    dcf_target_price_6m = None
    if dcf_target_price is not None and current_price is not None:
        dcf_target_price_6m = current_price + (dcf_target_price - current_price) * 0.5

    dcf_weight = DEFAULT_DCF_WEIGHT if dcf_target_price is not None else 0.0
    multiple_weight = DEFAULT_MULTIPLE_WEIGHT if dcf_target_price is not None else 1.0
    target_price_6m = _weighted_average(
        [(multiple_target_price_6m, multiple_weight), (dcf_target_price_6m, dcf_weight)]
    )
    target_price_12m = _weighted_average(
        [(multiple_target_price_12m, multiple_weight), (dcf_target_price, dcf_weight)]
    )
    method = VALUATION_METHOD

    if is_bank:
        pe_pb_target_price_6m = _bank_multiple_target_price(
            eps=eps,
            bvps=bvps,
            pe=pe,
            pb=pb,
            industry_pe=industry_pe,
            industry_pb=industry_pb,
            roe=roe,
            industry_roe=roe_industry,
            earnings_growth=earnings_growth_6m,
            book_growth=book_growth_6m,
        )
        pe_pb_target_price_12m = _bank_multiple_target_price(
            eps=eps,
            bvps=bvps,
            pe=pe,
            pb=pb,
            industry_pe=industry_pe,
            industry_pb=industry_pb,
            roe=roe,
            industry_roe=roe_industry,
            earnings_growth=earnings_growth_12m,
            book_growth=book_growth_12m,
        )
        multiple_target_price_6m = pe_pb_target_price_6m
        multiple_target_price_12m = pe_pb_target_price_12m
        ev_ebitda_target_price_6m = None
        ev_ebitda_target_price_12m = None
        enterprise_value = None
        net_debt = None
        trailing_ebitda = None
        ev_ebitda = None
        industry_ev_ebitda = None
        dcf_target_price = None
        dcf_target_price_6m = None
        dcf_weight = 0.0
        multiple_weight = 1.0
        discount_rate = None
        terminal_growth = None
        normalized_fcf = None
        target_price_6m = multiple_target_price_6m
        target_price_12m = multiple_target_price_12m
        method = BANK_VALUATION_METHOD

    industry_comparison = IndustryComparison(
        industry=market_row["industry"],
        subindustry=market_row["subindustry"],
        peer_count=peer_count,
        pe=pe,
        industry_pe=industry_pe,
        pe_premium=_premium(pe, industry_pe),
        pb=pb,
        industry_pb=industry_pb,
        pb_premium=_premium(pb, industry_pb),
        roe=roe,
        industry_roe=roe_industry,
        roa=roa,
        industry_roa=roa_industry,
        ros=ros,
        industry_ros=ros_industry,
    )

    latest_year, latest_quarter = periods[-1]
    return StockValuation(
        ticker=ticker,
        latest_period=f"Q{latest_quarter}/{latest_year}",
        current_price=current_price,
        multiple_target_price_6m=multiple_target_price_6m,
        multiple_target_price_12m=multiple_target_price_12m,
        pe_pb_target_price_6m=pe_pb_target_price_6m,
        pe_pb_target_price_12m=pe_pb_target_price_12m,
        ev_ebitda_target_price_6m=ev_ebitda_target_price_6m,
        ev_ebitda_target_price_12m=ev_ebitda_target_price_12m,
        enterprise_value=enterprise_value,
        net_debt=net_debt,
        trailing_ebitda=trailing_ebitda,
        ev_ebitda=ev_ebitda,
        industry_ev_ebitda=industry_ev_ebitda,
        ev_ebitda_premium=_premium(ev_ebitda, industry_ev_ebitda),
        dcf_target_price=dcf_target_price,
        dcf_target_price_6m=dcf_target_price_6m,
        dcf_upside=_upside(dcf_target_price, current_price),
        dcf_weight=dcf_weight,
        multiple_weight=multiple_weight,
        discount_rate=discount_rate,
        terminal_growth=terminal_growth,
        normalized_fcf=normalized_fcf,
        target_price_6m=target_price_6m,
        target_price_12m=target_price_12m,
        upside_6m=_upside(target_price_6m, current_price),
        upside_12m=_upside(target_price_12m, current_price),
        profit_growth_6m=profit_growth_6m,
        profit_growth_12m=profit_growth_12m,
        equity_growth_12m=equity_growth_12m,
        industry_comparison=industry_comparison,
        method=method,
    )


def _backtest_return(value: float | None, base_price: float | None) -> float | None:
    return _upside(value, base_price)


def get_valuation_backtest(ticker: str, limit: int = 10) -> ValuationBacktestResponse:
    ticker = ticker.upper()
    price_table = settings.qualified_table
    metric_table = _qualified_table("warehouse_ticker_metric")
    reports_table = _qualified_table("warehouse_reports")
    overview_table = _qualified_table("warehouse_overview")
    period_limit = max(limit + 4, 8)

    report_query = text(
        f"""
        WITH selected_periods AS (
            SELECT DISTINCT year, quarter
            FROM {reports_table}
            WHERE ticker = :ticker
              AND year IS NOT NULL
              AND quarter IS NOT NULL
            ORDER BY year DESC, quarter DESC
            LIMIT :period_limit
        )
        SELECT
            reports.year,
            reports.quarter,
            reports.report_type,
            reports.criteria,
            reports.value::double precision AS value
        FROM {reports_table} AS reports
        INNER JOIN selected_periods
            ON selected_periods.year = reports.year
           AND selected_periods.quarter = reports.quarter
        WHERE reports.ticker = :ticker
          AND (
              (reports.report_type = 'IS' AND reports.criteria IN ('profit', 'revenue', 'cost_of_goods_sold', 'cogs', 'selling_expenses', 'sales_expenses', 'general_admin_expenses', 'admin_expenses'))
              OR (reports.report_type = 'BS' AND reports.criteria IN ('equity', 'liabilities', 'cash_and_cash_equivalents', 'cash'))
              OR (reports.report_type = 'CF' AND reports.criteria IN ('cashflow_operating', 'cashflow_investing', 'cashflow_financing', 'net_cashflow', 'cf_operating', 'cf_investment', 'cf_finance', 'net_cf', 'cash_ending', 'cash'))
          )
        """
    )

    point_query = text(
        f"""
        WITH selected_periods AS (
            SELECT DISTINCT
                year,
                quarter,
                (MAKE_DATE(year::int, (quarter::int * 3), 1) + INTERVAL '1 month - 1 day')::date AS period_end
            FROM {reports_table}
            WHERE ticker = :ticker
              AND year IS NOT NULL
              AND quarter IS NOT NULL
            ORDER BY year DESC, quarter DESC
            LIMIT :period_limit
        ),
        latest_overview AS (
            SELECT industry, subindustry, issue_share
            FROM {overview_table} AS overview
            WHERE ticker = :ticker
            ORDER BY date_fetched DESC NULLS LAST
            LIMIT 1
        )
        SELECT
            periods.year,
            periods.quarter,
            periods.period_end,
            base_price.{columns["date"]} AS base_date,
            base_price.{columns["close"]}::double precision AS base_price,
            base_price.market_cap::double precision AS base_market_cap,
            CASE WHEN base_price.pe::text ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN base_price.pe::double precision ELSE NULL END AS base_pe,
            CASE WHEN base_price.pb::text ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN base_price.pb::double precision ELSE NULL END AS base_pb,
            price_6m.{columns["date"]} AS actual_date_6m,
            price_6m.{columns["close"]}::double precision AS actual_price_6m,
            price_12m.{columns["date"]} AS actual_date_12m,
            price_12m.{columns["close"]}::double precision AS actual_price_12m,
            metric.eps::double precision AS eps,
            metric.bvps::double precision AS bvps,
            metric.roe::double precision AS roe,
            overview.industry,
            overview.subindustry,
            overview.issue_share
        FROM selected_periods AS periods
        LEFT JOIN latest_overview AS overview ON TRUE
        LEFT JOIN LATERAL (
            SELECT *
            FROM {price_table}
            WHERE {columns["ticker"]} = :ticker
              AND {columns["close"]} IS NOT NULL
              AND {columns["date"]} <= periods.period_end
            ORDER BY {columns["date"]} DESC
            LIMIT 1
        ) AS base_price ON TRUE
        LEFT JOIN LATERAL (
            SELECT *
            FROM {price_table}
            WHERE {columns["ticker"]} = :ticker
              AND {columns["close"]} IS NOT NULL
              AND {columns["date"]} >= periods.period_end + INTERVAL '6 months' - INTERVAL '10 days'
              AND {columns["date"]} <= periods.period_end + INTERVAL '6 months' + INTERVAL '10 days'
            ORDER BY ABS(EXTRACT(EPOCH FROM ({columns["date"]}::timestamp - (periods.period_end + INTERVAL '6 months')::timestamp)))
            LIMIT 1
        ) AS price_6m ON TRUE
        LEFT JOIN LATERAL (
            SELECT *
            FROM {price_table}
            WHERE {columns["ticker"]} = :ticker
              AND {columns["close"]} IS NOT NULL
              AND {columns["date"]} >= periods.period_end + INTERVAL '12 months' - INTERVAL '10 days'
              AND {columns["date"]} <= periods.period_end + INTERVAL '12 months' + INTERVAL '10 days'
            ORDER BY ABS(EXTRACT(EPOCH FROM ({columns["date"]}::timestamp - (periods.period_end + INTERVAL '12 months')::timestamp)))
            LIMIT 1
        ) AS price_12m ON TRUE
        LEFT JOIN LATERAL (
            SELECT *
            FROM {metric_table}
            WHERE ticker = :ticker
              AND (
                year < periods.year
                OR (year = periods.year AND quarter <= periods.quarter)
              )
            ORDER BY year DESC NULLS LAST, quarter DESC NULLS LAST
            LIMIT 1
        ) AS metric ON TRUE
        ORDER BY periods.year, periods.quarter
        """
    )

    with engine.connect() as conn:
        report_rows = conn.execute(report_query, {"ticker": ticker, "period_limit": period_limit}).mappings().all()
        point_rows = conn.execute(point_query, {"ticker": ticker, "period_limit": period_limit}).mappings().all()

    periods = sorted({(int(row["year"]), int(row["quarter"])) for row in report_rows})
    values_by_period = {
        (int(row["year"]), int(row["quarter"]), str(row["report_type"]), str(row["criteria"])): _to_float(row["value"])
        for row in report_rows
    }
    rows_by_period = {(int(row["year"]), int(row["quarter"])): row for row in point_rows}
    eval_periods = periods[-limit:]
    points: list[ValuationBacktestPoint] = []

    for year, quarter in eval_periods:
        row = rows_by_period.get((year, quarter))
        if row is None:
            continue

        history_periods = [period for period in periods if period <= (year, quarter)]
        base_price = _to_float(row["base_price"])
        market_cap = _to_float(row["base_market_cap"])
        eps = _to_float(row["eps"])
        bvps = _to_float(row["bvps"])
        pe = _to_float(row["base_pe"])
        pb = _to_float(row["base_pb"])
        issue_share = _to_float(row["issue_share"])
        is_bank = _is_bank(ticker, row["industry"], row["subindustry"])

        profit_growth_6m = _period_growth(values_by_period, history_periods, "IS", "profit", trailing_periods=2)
        profit_growth_12m = _period_growth(values_by_period, history_periods, "IS", "profit", trailing_periods=4)
        revenue_growth_6m = _period_growth(values_by_period, history_periods, "IS", "revenue", trailing_periods=2)
        revenue_growth_12m = _period_growth(values_by_period, history_periods, "IS", "revenue", trailing_periods=4)
        equity_growth_12m = _period_growth(values_by_period, history_periods, "BS", "equity", trailing_periods=4)
        growth_6m = profit_growth_6m if profit_growth_6m is not None else revenue_growth_6m
        growth_12m = profit_growth_12m if profit_growth_12m is not None else revenue_growth_12m
        equity_growth_12m = 0.0 if equity_growth_12m is None else equity_growth_12m
        earnings_growth_6m = _compound_growth(growth_6m, 0.5)
        earnings_growth_12m = _compound_growth(growth_12m, 1.0)
        book_growth_6m = _compound_growth(equity_growth_12m, 0.5)
        book_growth_12m = _compound_growth(equity_growth_12m, 1.0)

        latest_equity = _latest_value(values_by_period, history_periods, "BS", "equity")
        latest_liabilities = _latest_value(values_by_period, history_periods, "BS", "liabilities")
        latest_cash = _latest_value(values_by_period, history_periods, "BS", "cash")
        if latest_cash is None:
            latest_cash = _latest_value(values_by_period, history_periods, "CF", "cash")
        trailing_ebitda = _trailing_ebitda_proxy(values_by_period, history_periods)
        enterprise_value, net_debt = _enterprise_value(market_cap, latest_liabilities, latest_cash)
        ev_ebitda = (
            enterprise_value / trailing_ebitda
            if enterprise_value is not None and enterprise_value > 0 and trailing_ebitda is not None and trailing_ebitda > 0
            else None
        )

        pe = _clamp(pe, 3, 35) if pe is not None and pe > 0 else None
        pb = _clamp(pb, 0.2, 6) if pb is not None and pb > 0 else None
        eps_target_6m = (eps * (1 + (earnings_growth_6m or 0)) * pe / 1000) if eps and eps > 0 and pe else None
        eps_target_12m = (eps * (1 + (earnings_growth_12m or 0)) * pe / 1000) if eps and eps > 0 and pe else None
        bvps_target_6m = (bvps * (1 + (book_growth_6m or 0)) * pb / 1000) if bvps and bvps > 0 and pb else None
        bvps_target_12m = (bvps * (1 + (book_growth_12m or 0)) * pb / 1000) if bvps and bvps > 0 and pb else None
        pe_pb_target_price_6m = _weighted_average([(eps_target_6m, 0.7), (bvps_target_6m, 0.3)])
        pe_pb_target_price_12m = _weighted_average([(eps_target_12m, 0.7), (bvps_target_12m, 0.3)])
        ev_ebitda_target_price_6m = None if is_bank else _ev_ebitda_target_price(
            trailing_ebitda=trailing_ebitda,
            growth=earnings_growth_6m,
            benchmark=ev_ebitda,
            net_debt=net_debt,
            issue_share=issue_share,
        )
        ev_ebitda_target_price_12m = None if is_bank else _ev_ebitda_target_price(
            trailing_ebitda=trailing_ebitda,
            growth=earnings_growth_12m,
            benchmark=ev_ebitda,
            net_debt=net_debt,
            issue_share=issue_share,
        )
        multiple_target_price_6m = pe_pb_target_price_6m if is_bank else _weighted_average(
            [
                (pe_pb_target_price_6m, DEFAULT_PE_PB_MULTIPLE_WEIGHT),
                (ev_ebitda_target_price_6m, DEFAULT_EV_EBITDA_MULTIPLE_WEIGHT),
            ]
        )
        multiple_target_price_12m = pe_pb_target_price_12m if is_bank else _weighted_average(
            [
                (pe_pb_target_price_12m, DEFAULT_PE_PB_MULTIPLE_WEIGHT),
                (ev_ebitda_target_price_12m, DEFAULT_EV_EBITDA_MULTIPLE_WEIGHT),
            ]
        )
        dcf_target_price, _, _, _ = (None, None, None, None) if is_bank else _dcf_target_price(
            values_by_period=values_by_period,
            periods=history_periods,
            issue_share=issue_share,
            growth_12m=growth_12m,
            equity=latest_equity,
            liabilities=latest_liabilities,
        )
        dcf_target_price_6m = (
            base_price + (dcf_target_price - base_price) * 0.5
            if dcf_target_price is not None and base_price is not None
            else None
        )
        dcf_weight = DEFAULT_DCF_WEIGHT if dcf_target_price is not None else 0.0
        multiple_weight = DEFAULT_MULTIPLE_WEIGHT if dcf_target_price is not None else 1.0
        target_price_6m = _weighted_average([(multiple_target_price_6m, multiple_weight), (dcf_target_price_6m, dcf_weight)])
        target_price_12m = _weighted_average([(multiple_target_price_12m, multiple_weight), (dcf_target_price, dcf_weight)])
        actual_price_6m = _to_float(row["actual_price_6m"])
        actual_price_12m = _to_float(row["actual_price_12m"])
        target_return_6m = _backtest_return(target_price_6m, base_price)
        target_return_12m = _backtest_return(target_price_12m, base_price)
        actual_return_6m = _backtest_return(actual_price_6m, base_price)
        actual_return_12m = _backtest_return(actual_price_12m, base_price)

        points.append(
            ValuationBacktestPoint(
                ticker=ticker,
                period=f"Q{quarter}/{year}",
                period_end=row["period_end"],
                base_date=row["base_date"],
                base_price=base_price,
                target_price_6m=target_price_6m,
                target_price_12m=target_price_12m,
                actual_date_6m=row["actual_date_6m"],
                actual_price_6m=actual_price_6m,
                actual_date_12m=row["actual_date_12m"],
                actual_price_12m=actual_price_12m,
                target_return_6m=target_return_6m,
                actual_return_6m=actual_return_6m,
                target_error_6m=(
                    actual_return_6m - target_return_6m
                    if actual_return_6m is not None and target_return_6m is not None
                    else None
                ),
                target_return_12m=target_return_12m,
                actual_return_12m=actual_return_12m,
                target_error_12m=(
                    actual_return_12m - target_return_12m
                    if actual_return_12m is not None and target_return_12m is not None
                    else None
                ),
            )
        )

    return ValuationBacktestResponse(ticker=ticker, total=len(points), points=points)


def _valuation_to_ranking_item(valuation: StockValuation) -> ValuationRankingItem | None:
    if valuation.upside_12m is None or valuation.current_price is None:
        return None

    return ValuationRankingItem(
        ticker=valuation.ticker,
        latest_period=valuation.latest_period,
        current_price=valuation.current_price,
        target_price_6m=valuation.target_price_6m,
        target_price_12m=valuation.target_price_12m,
        upside_6m=valuation.upside_6m,
        upside_12m=valuation.upside_12m,
        multiple_target_price_12m=valuation.multiple_target_price_12m,
        dcf_target_price=valuation.dcf_target_price,
        ev_ebitda=valuation.ev_ebitda,
        industry_ev_ebitda=valuation.industry_ev_ebitda,
        dcf_upside=valuation.dcf_upside,
        method=valuation.method,
    )


def get_valuation_rankings(tickers: list[str] | None = None, limit: int = 10) -> ValuationRankingResponse:
    if tickers:
        universe = sorted({ticker.strip().upper() for ticker in tickers if ticker.strip()})
    else:
        universe = [ticker for ticker in get_tickers() if not ticker.upper().endswith("INDEX")]

    items: list[ValuationRankingItem] = []

    def load_item(ticker: str) -> ValuationRankingItem | None:
        try:
            valuation = get_stock_valuation(ticker)
        except Exception:
            return None
        if valuation is None:
            return None

        return _valuation_to_ranking_item(valuation)

    max_workers = min(10, max(len(universe), 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(load_item, ticker) for ticker in universe]
        for future in as_completed(futures):
            item = future.result()
            if item is not None:
                items.append(item)

    items_by_ticker = {item.ticker: item for item in items}
    all_items = [
        items_by_ticker.get(ticker)
        or ValuationRankingItem(
            ticker=ticker,
            method="Chưa đủ dữ liệu định giá",
        )
        for ticker in universe
    ]
    promising = sorted(items, key=lambda item: item.upside_12m or 0, reverse=True)[:limit]
    risky = sorted(items, key=lambda item: item.upside_12m or 0)[:limit]

    return ValuationRankingResponse(
        universe_size=len(universe),
        covered_count=len(items),
        items=all_items,
        promising=promising,
        risky=risky,
    )


def _numeric_column_sql(column_name: str) -> str:
    return (
        f"CASE WHEN {column_name}::text ~ '^-?[0-9]+(\\.[0-9]+)?$' "
        f"THEN {column_name}::double precision ELSE NULL END"
    )


def _filtered_average(values: list[float | None], minimum: float, maximum: float) -> float | None:
    clean_values = [value for value in values if value is not None and minimum < value < maximum]
    if not clean_values:
        return None

    return sum(clean_values) / len(clean_values)


def _weighted_change(rows: list[dict[str, object]], key: str) -> float | None:
    weighted_total = 0.0
    weight_sum = 0.0
    fallback_values: list[float] = []

    for row in rows:
        value = _to_float(row.get(key))
        if value is None:
            continue

        market_cap = _to_float(row.get("market_cap"))
        if market_cap is not None and market_cap > 0:
            weighted_total += value * market_cap
            weight_sum += market_cap
        else:
            fallback_values.append(value)

    if weight_sum > 0:
        return weighted_total / weight_sum

    if fallback_values:
        return sum(fallback_values) / len(fallback_values)

    return None


def get_sector_overview(top_limit: int = 5) -> SectorOverviewResponse:
    price_table = settings.qualified_table
    overview_table = _qualified_table("warehouse_overview")

    query = text(
        f"""
        WITH latest_overview_by_ticker AS (
            SELECT DISTINCT ON (ticker)
                ticker,
                name,
                trading_floor,
                industry,
                subindustry
            FROM {overview_table}
            WHERE ticker IS NOT NULL
              AND COALESCE(UPPER(TRIM(trading_floor)), '') <> 'DELISTED'
              AND industry IS NOT NULL
              AND TRIM(industry) <> ''
            ORDER BY ticker, date_fetched DESC NULLS LAST
        ),
        latest_price_by_ticker AS (
            SELECT DISTINCT ON ({columns["ticker"]})
                {columns["ticker"]} AS ticker,
                {columns["date"]}::date AS date,
                {columns["close"]}::double precision AS close,
                {_numeric_column_sql("market_cap")} AS market_cap,
                {_numeric_column_sql("pe")} AS pe,
                {_numeric_column_sql("pb")} AS pb,
                {_numeric_column_sql("chg_1d")} AS change_1d,
                {_numeric_column_sql("chg_1w")} AS change_1w,
                {_numeric_column_sql("chg_1m")} AS change_1m,
                {_numeric_column_sql("chg_3m")} AS change_3m,
                {_numeric_column_sql("chg_6m")} AS change_6m,
                {_numeric_column_sql("chg_1y")} AS change_1y,
                {_numeric_column_sql("chg_3y")} AS change_3y
            FROM {price_table}
            WHERE {columns["ticker"]} IS NOT NULL
              AND {columns["ticker"]} NOT IN ('VNINDEX', 'VN30', 'VN100', 'HNX30', 'UPCOMINDEX')
              AND {columns["close"]} IS NOT NULL
            ORDER BY {columns["ticker"]}, {columns["date"]} DESC NULLS LAST
        )
        SELECT
            price.ticker,
            price.date,
            overview.name,
            overview.industry,
            overview.subindustry,
            price.close,
            price.market_cap,
            price.pe,
            price.pb,
            price.change_1d,
            price.change_1w,
            price.change_1m,
            price.change_3m,
            price.change_6m,
            price.change_1y,
            price.change_3y
        FROM latest_price_by_ticker AS price
        INNER JOIN latest_overview_by_ticker AS overview
            ON overview.ticker = price.ticker
        """
    )

    with engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(query).mappings().all()]

    if not rows:
        return SectorOverviewResponse(as_of=None, sector_count=0, total_market_cap=0, items=[])

    sector_rows: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        industry = (_repair_mojibake(row["industry"]) or "").strip()
        if not industry:
            continue

        sector_rows.setdefault(industry, []).append(row)

    period_keys = [
        "change_1d",
        "change_1w",
        "change_1m",
        "change_3m",
        "change_6m",
        "change_1y",
        "change_3y",
    ]

    total_market_cap = sum(
        market_cap
        for market_cap in (_to_float(row.get("market_cap")) for row in rows)
        if market_cap is not None and market_cap > 0
    )
    as_of = max((row["date"] for row in rows if row.get("date") is not None), default=None)
    items: list[SectorOverviewItem] = []

    for industry, grouped_rows in sector_rows.items():
        sector_market_cap = sum(
            market_cap
            for market_cap in (_to_float(row.get("market_cap")) for row in grouped_rows)
            if market_cap is not None and market_cap > 0
        )
        advancers = sum(1 for row in grouped_rows if (_to_float(row.get("change_1d")) or 0) > 0)
        decliners = sum(1 for row in grouped_rows if (_to_float(row.get("change_1d")) or 0) < 0)
        unchanged = max(len(grouped_rows) - advancers - decliners, 0)

        top_constituents: list[SectorConstituent] = []
        for row in sorted(grouped_rows, key=lambda item: _to_float(item.get("market_cap")) or 0, reverse=True)[
            :top_limit
        ]:
            market_cap = _to_float(row.get("market_cap"))
            weight = (market_cap / sector_market_cap * 100) if market_cap is not None and sector_market_cap > 0 else None
            top_constituents.append(
                SectorConstituent(
                    ticker=str(row["ticker"]),
                    name=_repair_mojibake(row.get("name")),
                    subindustry=_repair_mojibake(row.get("subindustry")),
                    market_cap=market_cap,
                    close=_to_float(row.get("close")),
                    pe=_to_float(row.get("pe")),
                    pb=_to_float(row.get("pb")),
                    weight=weight,
                    change_1d=_to_float(row.get("change_1d")),
                    change_1w=_to_float(row.get("change_1w")),
                    change_1m=_to_float(row.get("change_1m")),
                    change_3m=_to_float(row.get("change_3m")),
                    change_6m=_to_float(row.get("change_6m")),
                    change_1y=_to_float(row.get("change_1y")),
                    change_3y=_to_float(row.get("change_3y")),
                )
            )

        item_payload = {
            "industry": industry,
            "ticker_count": len(grouped_rows),
            "total_market_cap": sector_market_cap,
            "average_pe": _filtered_average([_to_float(row.get("pe")) for row in grouped_rows], 0, 80),
            "average_pb": _filtered_average([_to_float(row.get("pb")) for row in grouped_rows], 0, 20),
            "advancers": advancers,
            "decliners": decliners,
            "unchanged": unchanged,
            "top_constituents": top_constituents,
        }
        for period_key in period_keys:
            item_payload[f"weighted_{period_key}"] = _weighted_change(grouped_rows, period_key)

        items.append(SectorOverviewItem(**item_payload))

    items.sort(key=lambda item: item.total_market_cap or 0, reverse=True)

    return SectorOverviewResponse(
        as_of=as_of,
        sector_count=len(items),
        total_market_cap=total_market_cap,
        items=items,
    )


def get_stock_info(ticker: str) -> StockInfo | None:
    ticker = ticker.upper()
    price_table = settings.qualified_table
    overview_table = _qualified_table("warehouse_overview")
    metric_table = _qualified_table("warehouse_ticker_metric")
    overview_columns = _warehouse_columns("warehouse_overview")
    overview_name_expr = _optional_first_table_column(overview_columns, "overview", ("organ_name", "name"), "text")
    overview_company_profile_expr = _optional_first_table_column(
        overview_columns,
        "overview",
        ("company_profile", "profile", "history", "description"),
        "text",
    )
    overview_exchange_expr = (
        _optional_table_column(overview_columns, "overview", "trading_floor", "text")
        if "trading_floor" in overview_columns
        else _optional_table_column(overview_columns, "overview", "exchange", "text")
    )
    overview_issue_share_expr = _optional_table_column(overview_columns, "overview", "issue_share", "bigint")
    overview_free_float_expr = _optional_first_table_column(
        overview_columns,
        "overview",
        ("free_float_percentage", "free_float_percent", "free_float"),
        "double precision",
    )
    overview_foreign_expr = _optional_first_table_column(
        overview_columns,
        "overview",
        ("foreign_percentage", "foreign_percent", "foreign_ownership_percentage", "foreign_ownership"),
        "double precision",
    )

    query = text(
        f"""
        WITH latest_price AS (
            SELECT
                {columns["ticker"]} AS ticker,
                {columns["date"]}::date AS date,
                {columns["open"]} AS open,
                {columns["high"]} AS high,
                {columns["low"]} AS low,
                {columns["close"]} AS close,
                {columns["volume"]} AS volume,
                market_cap,
                pe,
                pb,
                chg_1d,
                chg_1w,
                chg_1m,
                chg_3m,
                chg_6m,
                chg_1y
            FROM {price_table}
            WHERE {columns["ticker"]} = :ticker
            ORDER BY {columns["date"]} DESC
            LIMIT 1
        ),
        previous_price AS (
            SELECT {columns["close"]} AS reference
            FROM {price_table}
            WHERE {columns["ticker"]} = :ticker
              AND {columns["date"]} < (SELECT date FROM latest_price)
            ORDER BY {columns["date"]} DESC
            LIMIT 1
        ),
        average_volume AS (
            SELECT AVG(volume) AS average_volume_10d
            FROM (
                SELECT {columns["volume"]} AS volume
                FROM {price_table}
                WHERE {columns["ticker"]} = :ticker
                  AND {columns["volume"]} IS NOT NULL
                ORDER BY {columns["date"]} DESC
                LIMIT 10
            ) AS recent_volume
        ),
        price_three_days_ago AS (
            SELECT {columns["close"]} AS close
            FROM {price_table}
            WHERE {columns["ticker"]} = :ticker
              AND {columns["date"]} < (SELECT date FROM latest_price)
              AND {columns["close"]} IS NOT NULL
            ORDER BY {columns["date"]} DESC
            OFFSET 2
            LIMIT 1
        ),
        latest_overview AS (
            SELECT
                {overview_name_expr} AS name,
                {overview_company_profile_expr} AS company_profile,
                {overview_exchange_expr} AS exchange,
                {overview_issue_share_expr} AS issue_share,
                {overview_free_float_expr} AS free_float_percentage,
                {overview_foreign_expr} AS foreign_percentage
            FROM {overview_table} AS overview
            WHERE overview.ticker = :ticker
            ORDER BY date_fetched DESC NULLS LAST
            LIMIT 1
        ),
        latest_metric AS (
            SELECT eps, bvps
            FROM {metric_table}
            WHERE ticker = :ticker
            ORDER BY year DESC NULLS LAST, quarter DESC NULLS LAST
            LIMIT 1
        ),
        stock_close AS (
            SELECT date, close
            FROM (
                SELECT DISTINCT ON ({columns["date"]})
                    {columns["date"]}::date AS date,
                    {columns["close"]}::double precision AS close
                FROM {price_table}
                WHERE {columns["ticker"]} = :ticker
                  AND {columns["date"]} <= (SELECT date FROM latest_price)
                  AND {columns["close"]} IS NOT NULL
                  AND {columns["close"]} > 0
                ORDER BY {columns["date"]} DESC, {columns["close"]} DESC
            ) AS deduped
            ORDER BY date DESC
            LIMIT 253
        ),
        index_close AS (
            SELECT date, close
            FROM (
                SELECT DISTINCT ON ({columns["date"]})
                    {columns["date"]}::date AS date,
                    {columns["close"]}::double precision AS close
                FROM {price_table}
                WHERE {columns["ticker"]} = 'VNINDEX'
                  AND {columns["date"]} <= (SELECT date FROM latest_price)
                  AND {columns["close"]} IS NOT NULL
                  AND {columns["close"]} > 0
                ORDER BY {columns["date"]} DESC, {columns["close"]} DESC
            ) AS deduped
            ORDER BY date DESC
            LIMIT 253
        ),
        stock_returns AS (
            SELECT
                date,
                close / LAG(close) OVER (ORDER BY date) - 1 AS stock_return
            FROM stock_close
        ),
        index_returns AS (
            SELECT
                date,
                close / LAG(close) OVER (ORDER BY date) - 1 AS index_return
            FROM index_close
        ),
        beta_calc AS (
            SELECT
                CASE
                    WHEN COUNT(*) < 30 OR VAR_SAMP(index_return) IS NULL OR VAR_SAMP(index_return) = 0 THEN NULL
                    ELSE COVAR_SAMP(stock_return, index_return) / VAR_SAMP(index_return)
                END AS beta
            FROM stock_returns
            INNER JOIN index_returns USING (date)
            WHERE stock_return IS NOT NULL
              AND index_return IS NOT NULL
        )
        SELECT
            latest_price.ticker,
            latest_price.date,
            previous_price.reference,
            latest_price.open,
            latest_price.high,
            latest_price.low,
            latest_price.close,
            latest_price.volume,
            average_volume.average_volume_10d,
            latest_price.chg_1d AS change_1d,
            CASE
                WHEN price_three_days_ago.close IS NULL OR price_three_days_ago.close = 0 THEN NULL
                ELSE ((latest_price.close - price_three_days_ago.close) / price_three_days_ago.close) * 100
            END AS change_3d,
            latest_price.chg_1w AS change_1w,
            latest_price.chg_1m AS change_1m,
            latest_price.chg_3m AS change_3m,
            latest_price.chg_6m AS change_6m,
            latest_price.chg_1y AS change_1y,
            beta_calc.beta,
            latest_price.market_cap,
            latest_price.pe,
            latest_price.pb,
            latest_metric.eps,
            latest_metric.bvps,
            latest_overview.issue_share,
            latest_overview.name AS overview_name,
            latest_overview.company_profile AS overview_company_profile,
            latest_overview.exchange AS overview_exchange,
            latest_overview.free_float_percentage AS overview_free_float_percentage,
            latest_overview.foreign_percentage AS overview_foreign_percentage
        FROM latest_price
        LEFT JOIN previous_price ON TRUE
        LEFT JOIN average_volume ON TRUE
        LEFT JOIN price_three_days_ago ON TRUE
        LEFT JOIN latest_overview ON TRUE
        LEFT JOIN latest_metric ON TRUE
        LEFT JOIN beta_calc ON TRUE
        """
    )

    with engine.connect() as conn:
        row = conn.execute(query, {"ticker": ticker}).mappings().first()

    if not row:
        return None

    payload = dict(row)
    payload["overview"] = {
        "name": payload.pop("overview_name", None),
        "company_profile": payload.pop("overview_company_profile", None),
        "exchange": payload.pop("overview_exchange", None),
        "issue_share": payload.get("issue_share"),
        "free_float_percentage": payload.pop("overview_free_float_percentage", None),
        "foreign_percentage": payload.pop("overview_foreign_percentage", None),
    }
    payload["shareholders"] = _get_stock_shareholders(ticker=ticker)
    payload["officers"] = _get_stock_officers(ticker=ticker)
    payload["valuation"] = get_stock_valuation(ticker=ticker)
    return StockInfo(**payload)


def _get_stock_shareholders(ticker: str) -> list[StockShareholder]:
    table_name = "warehouse_shareholders"
    shareholder_columns = _warehouse_columns(table_name)
    ticker_column = _first_existing_column(shareholder_columns, ("ticker", "symbol", "stock_code"))
    name_column = _first_existing_column(shareholder_columns, ("share_holder", "shareholder", "holder_name", "name"))
    if ticker_column is None or name_column is None:
        return []

    table = _qualified_table(table_name)
    ticker_expr = f"shareholder.{settings._validate_identifier(ticker_column)}"
    name_expr = _optional_first_table_column(
        shareholder_columns,
        "shareholder",
        ("share_holder", "shareholder", "holder_name", "name"),
        "text",
    )
    ownership_expr = _optional_first_table_column(
        shareholder_columns,
        "shareholder",
        ("share_own_percent", "ownership_percentage", "ownership", "own_percent", "ratio"),
        "double precision",
    )
    ownership_quantity_expr = _optional_first_table_column(
        shareholder_columns,
        "shareholder",
        ("quantity", "share_quantity", "ownership_quantity", "own_quantity"),
        "double precision",
    )
    update_expr = _optional_first_table_column(
        shareholder_columns,
        "shareholder",
        ("update_date", "date_fetched", "updated_at"),
        "text",
    )

    query = text(
        f"""
        SELECT
            {name_expr} AS name,
            {ownership_expr} AS ownership_percentage,
            {ownership_quantity_expr} AS ownership_quantity
        FROM {table} AS shareholder
        WHERE {ticker_expr} = :ticker
          AND COALESCE({ownership_expr}, 0) >= 0.001
        ORDER BY {update_expr} DESC NULLS LAST, ownership_percentage DESC NULLS LAST
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(query, {"ticker": ticker}).mappings().all()

    deduped_rows: dict[str, dict] = {}
    for row in rows:
        payload = dict(row)
        key = _normalize_text(payload.get("name"))
        if not key:
            continue

        current = deduped_rows.get(key)
        payload_percent = payload.get("ownership_percentage") or 0
        current_percent = current.get("ownership_percentage") or 0 if current else 0
        if current is None or (
            current.get("ownership_quantity") is None
            and payload.get("ownership_quantity") is not None
        ) or payload_percent > current_percent:
            deduped_rows[key] = payload

    return [StockShareholder(**row) for row in deduped_rows.values()]


def _get_stock_officers(ticker: str) -> list[StockOfficer]:
    for table_name in ("warehouse_officers", "warehouse_officires"):
        officer_columns = _warehouse_columns(table_name)
        ticker_column = _first_existing_column(officer_columns, ("ticker", "symbol", "stock_code"))
        name_column = _first_existing_column(
            officer_columns,
            ("officer_name", "name", "full_name", "person_name"),
        )
        position_column = _first_existing_column(
            officer_columns,
            ("position", "title", "role", "officer_position"),
        )
        if ticker_column is None or (name_column is None and position_column is None):
            continue

        table = _qualified_table(table_name)
        ticker_expr = f"officer.{settings._validate_identifier(ticker_column)}"
        name_expr = _optional_first_table_column(
            officer_columns,
            "officer",
            ("officer_name", "name", "full_name", "person_name"),
            "text",
        )
        position_expr = _optional_first_table_column(
            officer_columns,
            "officer",
            ("position", "title", "role", "officer_position"),
            "text",
        )
        ownership_expr = _optional_first_table_column(
            officer_columns,
            "officer",
            ("officer_own_percent", "ownership_percentage", "ownership", "own_percent", "ratio"),
            "double precision",
        )
        ownership_quantity_expr = _optional_first_table_column(
            officer_columns,
            "officer",
            ("officer_own_quantity", "quantity", "ownership_quantity", "own_quantity"),
            "double precision",
        )
        order_column = _first_existing_column(
            officer_columns,
            ("display_order", "position_order", "updated_at", "date_fetched"),
        )
        order_clause = (
            f"ORDER BY officer.{settings._validate_identifier(order_column)} DESC NULLS LAST"
            if order_column is not None and order_column not in {"display_order", "position_order"}
            else f"ORDER BY officer.{settings._validate_identifier(order_column)} NULLS LAST"
            if order_column is not None
            else "ORDER BY name NULLS LAST"
        )

        query = text(
            f"""
            SELECT
                {name_expr} AS name,
                {position_expr} AS position,
                {ownership_expr} AS ownership_percentage,
                {ownership_quantity_expr} AS ownership_quantity
            FROM {table} AS officer
            WHERE {ticker_expr} = :ticker
            {order_clause}
            """
        )

        with engine.connect() as conn:
            rows = conn.execute(query, {"ticker": ticker}).mappings().all()

        deduped_rows: dict[str, dict] = {}
        for row in rows:
            payload = dict(row)
            key = _normalize_text(payload.get("name"))
            if not key:
                continue

            current = deduped_rows.get(key)
            current_score = (
                (4 if current and current.get("ownership_quantity") is not None else 0)
                + (2 if current and current.get("ownership_percentage") is not None else 0)
                + (1 if current and current.get("position") else 0)
            )
            payload_score = (
                (4 if payload.get("ownership_quantity") is not None else 0)
                + (2 if payload.get("ownership_percentage") is not None else 0)
                + (1 if payload.get("position") else 0)
            )
            if current is None or payload_score >= current_score:
                deduped_rows[key] = payload

        officers = [StockOfficer(**row) for row in deduped_rows.values()]
        if officers:
            return officers

    return []


def _first_financial_value(
    values_by_period: dict[tuple[int, int, str, str], float | None],
    year: int,
    quarter: int,
    report_type: str,
    criteria_list: tuple[str, ...],
) -> float | None:
    for criteria in criteria_list:
        value = values_by_period.get((year, quarter, report_type, criteria))
        if value is not None:
            return value
    return None


def _statement_period_key(year: int, quarter: int, period_label: str | None = None) -> str:
    return period_label or f"{year}-Q{quarter}"


def _report_column_expression(report_columns: set[str], column: str, fallback: str) -> str:
    return f"reports.{column}" if column in report_columns else fallback


def _build_financial_statements(detail_rows) -> list[FinancialStatement]:
    if not detail_rows:
        return []

    statement_rows_by_type: dict[str, dict[str, dict]] = {}
    periods_by_type: dict[str, dict[str, FinancialStatementPeriod]] = {}

    for row in detail_rows:
        report_type = str(row["report_type"])
        year = int(row["year"])
        quarter = int(row["quarter"])
        period_key = _statement_period_key(year, quarter, row.get("period_label"))
        periods_by_type.setdefault(report_type, {})[period_key] = FinancialStatementPeriod(
            key=period_key,
            label=f"Q{quarter}/{year}",
            year=year,
            quarter=quarter,
        )

        item_id = str(row.get("item_id") or row.get("criteria") or "")
        line_key = str(row.get("line_item_key") or item_id)
        item = statement_rows_by_type.setdefault(report_type, {}).setdefault(
            line_key,
            {
                "key": line_key,
                "item_id": item_id,
                "name_vi": str(row.get("item_name_vi") or row.get("criteria") or item_id),
                "name_en": row.get("item_name_en"),
                "criteria": str(row.get("criteria") or item_id),
                "section": row.get("section"),
                "display_order": int(row.get("display_order") or 1000),
                "parent_key": row.get("parent_item_id"),
                "level": int(row.get("level") or 0),
                "is_total": bool(row.get("is_total")),
                "unit": row.get("unit") or "Tỷ đồng",
                "values": {},
            },
        )
        item["values"][period_key] = float(row["value"]) if row.get("value") is not None else None

    statements: list[FinancialStatement] = []
    for report_type, row_map in sorted(
        statement_rows_by_type.items(),
        key=lambda item: FINANCIAL_STATEMENT_ORDER.get(item[0], 99),
    ):
        periods = sorted(
            periods_by_type.get(report_type, {}).values(),
            key=lambda period: (period.year, period.quarter),
            reverse=True,
        )
        rows = [
            FinancialStatementRow(**payload)
            for payload in sorted(
                row_map.values(),
                key=lambda payload: (
                    int(payload["display_order"]),
                    int(payload["level"]),
                    str(payload["name_vi"]),
                ),
            )
        ]
        statements.append(
            FinancialStatement(
                type=report_type,
                label=FINANCIAL_STATEMENT_LABELS.get(report_type, report_type),
                periods=periods,
                rows=rows,
            )
        )

    return statements


def _build_financial_metric_series(ticker: str, period_limit: int) -> list[FinancialMetricSeries]:
    metric_table_name = "warehouse_ticker_metric"
    metric_columns = _warehouse_columns(metric_table_name)
    required_columns = {"ticker", "year", "quarter"}
    if not required_columns.issubset(metric_columns):
        return _build_market_financial_metric_series(ticker, period_limit)

    available_metrics = [
        (key, label, unit)
        for key, label, unit in FINANCIAL_METRIC_DEFINITIONS
        if key in metric_columns
    ]
    if not available_metrics:
        return _build_market_financial_metric_series(ticker, period_limit)

    metric_table = _qualified_table(metric_table_name)
    selected_metric_sql = ",\n                ".join(
        f"{settings._validate_identifier(key)}::double precision AS {settings._validate_identifier(key)}"
        for key, _, _ in available_metrics
    )
    query = text(
        f"""
        SELECT
            year::integer AS year,
            quarter::integer AS quarter,
            {selected_metric_sql}
        FROM {metric_table}
        WHERE ticker = :ticker
          AND year IS NOT NULL
          AND quarter IS NOT NULL
        ORDER BY year DESC, quarter DESC
        LIMIT :period_limit
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(
            query,
            {"ticker": ticker, "period_limit": period_limit},
        ).mappings().all()

    ordered_rows = sorted(rows, key=lambda row: (int(row["year"]), int(row["quarter"])))
    series: list[FinancialMetricSeries] = []
    for key, label, unit in available_metrics:
        points = [
            FinancialPoint(
                period=f"Q{int(row['quarter'])}/{int(row['year'])}",
                year=int(row["year"]),
                quarter=int(row["quarter"]),
                value=_to_float(row.get(key)),
            )
            for row in ordered_rows
        ]
        if any(point.value is not None for point in points):
            series.append(
                FinancialMetricSeries(
                    key=key,
                    label=label,
                    unit=unit,
                    points=points,
                )
            )

    series.extend(_build_market_financial_metric_series(ticker, period_limit))
    return series


def _build_market_financial_metric_series(ticker: str, period_limit: int) -> list[FinancialMetricSeries]:
    price_columns = _warehouse_columns(settings.postgres_table)
    required_columns = {settings.postgres_ticker_column, settings.postgres_date_column}
    metric_columns = {key for key, _, _ in MARKET_FINANCIAL_METRIC_DEFINITIONS}

    if not required_columns.issubset(price_columns) or not metric_columns.intersection(price_columns):
        return []

    price_table = settings.qualified_table
    date_column = f"price.{columns['date']}"
    ticker_column = f"price.{columns['ticker']}"
    selected_metric_sql = ",\n            ".join(
        (
            f"{_numeric_column_sql(f'price.{settings._validate_identifier(key)}')} AS {settings._validate_identifier(key)}"
            if key in price_columns
            else f"NULL::double precision AS {settings._validate_identifier(key)}"
        )
        for key, _, _ in MARKET_FINANCIAL_METRIC_DEFINITIONS
    )
    has_value_sql = " OR ".join(
        f"{_numeric_column_sql(f'price.{settings._validate_identifier(key)}')} IS NOT NULL"
        for key, _, _ in MARKET_FINANCIAL_METRIC_DEFINITIONS
        if key in price_columns
    )

    query = text(
        f"""
        WITH ranked_prices AS (
            SELECT
                EXTRACT(YEAR FROM {date_column})::integer AS year,
                EXTRACT(QUARTER FROM {date_column})::integer AS quarter,
                {selected_metric_sql},
                ROW_NUMBER() OVER (
                    PARTITION BY EXTRACT(YEAR FROM {date_column})::integer, EXTRACT(QUARTER FROM {date_column})::integer
                    ORDER BY ({has_value_sql}) DESC, {date_column} DESC
                ) AS period_rank
            FROM {price_table} AS price
            WHERE {ticker_column} = :ticker
              AND {date_column} IS NOT NULL
        )
        SELECT year, quarter, pe, pb
        FROM ranked_prices
        WHERE period_rank = 1
        ORDER BY year DESC, quarter DESC
        LIMIT :period_limit
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(
            query,
            {"ticker": ticker, "period_limit": period_limit},
        ).mappings().all()

    ordered_rows = sorted(rows, key=lambda row: (int(row["year"]), int(row["quarter"])))
    series: list[FinancialMetricSeries] = []
    for key, label, unit in MARKET_FINANCIAL_METRIC_DEFINITIONS:
        if key not in price_columns:
            continue

        points = [
            FinancialPoint(
                period=f"Q{int(row['quarter'])}/{int(row['year'])}",
                year=int(row["year"]),
                quarter=int(row["quarter"]),
                value=_to_float(row.get(key)),
            )
            for row in ordered_rows
        ]
        if any(point.value is not None for point in points):
            series.append(
                FinancialMetricSeries(
                    key=key,
                    label=label,
                    unit=unit,
                    points=points,
                )
            )

    return series


def get_financial_dashboard(ticker: str, period_limit: int = 80) -> FinancialDashboard | None:
    ticker = ticker.upper()
    reports_table = _qualified_table("warehouse_reports")
    criteria_sql = ", ".join(f"'{criteria}'" for criteria in FINANCIAL_CRITERIA)

    query = text(
        f"""
        WITH selected_periods AS (
            SELECT DISTINCT year, quarter
            FROM {reports_table}
            WHERE ticker = :ticker
            ORDER BY year DESC, quarter DESC
            LIMIT :period_limit
        )
        SELECT
            reports.year,
            reports.quarter,
            reports.report_type,
            reports.criteria,
            reports.value
        FROM {reports_table} AS reports
        INNER JOIN selected_periods
            ON selected_periods.year = reports.year
           AND selected_periods.quarter = reports.quarter
        WHERE reports.ticker = :ticker
          AND reports.criteria IN ({criteria_sql})
        ORDER BY reports.year, reports.quarter, reports.report_type, reports.criteria
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(query, {"ticker": ticker, "period_limit": period_limit}).mappings().all()
        report_columns = {
            str(row["column_name"])
            for row in conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = :schema
                      AND table_name = 'warehouse_reports'
                    """
                ),
                {"schema": settings.postgres_schema},
            ).mappings()
        }
        detail_query = text(
            f"""
            WITH selected_periods AS (
                SELECT DISTINCT year, quarter
                FROM {reports_table}
                WHERE ticker = :ticker
                ORDER BY year DESC, quarter DESC
                LIMIT :period_limit
            )
            SELECT
                reports.year,
                reports.quarter,
                reports.report_type,
                reports.criteria,
                reports.value,
                {_report_column_expression(report_columns, "period_label", "CONCAT(reports.year, '-Q', reports.quarter)")} AS period_label,
                {_report_column_expression(report_columns, "item_id", "reports.criteria")} AS item_id,
                {_report_column_expression(report_columns, "line_item_key", "reports.criteria")} AS line_item_key,
                {_report_column_expression(report_columns, "item_name_vi", "reports.criteria")} AS item_name_vi,
                {_report_column_expression(report_columns, "item_name_en", "NULL::text")} AS item_name_en,
                {_report_column_expression(report_columns, "section", "reports.report_type")} AS section,
                {_report_column_expression(report_columns, "display_order", "1000")} AS display_order,
                {_report_column_expression(report_columns, "parent_item_id", "NULL::text")} AS parent_item_id,
                {_report_column_expression(report_columns, "level", "0")} AS level,
                {_report_column_expression(report_columns, "is_total", "false")} AS is_total,
                {_report_column_expression(report_columns, "unit", "'Tỷ đồng'")} AS unit
            FROM {reports_table} AS reports
            INNER JOIN selected_periods
                ON selected_periods.year = reports.year
               AND selected_periods.quarter = reports.quarter
            WHERE reports.ticker = :ticker
            ORDER BY reports.report_type, display_order, level, item_name_vi, reports.year DESC, reports.quarter DESC
            """
        )
        detail_rows = conn.execute(detail_query, {"ticker": ticker, "period_limit": period_limit}).mappings().all()

    if not rows and not detail_rows:
        return None

    periods = sorted({(int(row["year"]), int(row["quarter"])) for row in rows or detail_rows})
    values_by_period = {
        (int(row["year"]), int(row["quarter"]), str(row["report_type"]), str(row["criteria"])): float(row["value"])
        if row["value"] is not None
        else None
        for row in rows
    }

    def make_point(year: int, quarter: int, value: float | None) -> FinancialPoint:
        return FinancialPoint(period=f"Q{quarter}/{year}", year=year, quarter=quarter, value=value)

    series: list[FinancialSeries] = []
    for key, label, unit, report_type, criteria_list in FINANCIAL_SERIES_DEFINITIONS:
        points: list[FinancialPoint] = []
        for year, quarter in periods:
            if key == "profit_margin":
                revenue = _first_financial_value(
                    values_by_period,
                    year,
                    quarter,
                    "IS",
                    ("total_operating_income", "revenue"),
                )
                profit = _first_financial_value(
                    values_by_period,
                    year,
                    quarter,
                    "IS",
                    ("net_profit_loss_after_tax", "profit"),
                )
                value = None if revenue in (None, 0) or profit is None else (profit / revenue) * 100
            else:
                value = _first_financial_value(values_by_period, year, quarter, report_type, criteria_list)

            points.append(make_point(year, quarter, value))

        series.append(FinancialSeries(key=key, label=label, unit=unit, points=points))

    latest_year, latest_quarter = periods[-1]
    return FinancialDashboard(
        ticker=ticker,
        latest_period=f"Q{latest_quarter}/{latest_year}",
        series=series,
        metric_series=_build_financial_metric_series(ticker, period_limit),
        statements=_build_financial_statements(detail_rows),
    )


def get_dividend_events(
    ticker: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    upcoming_only: bool = False,
    limit: int = 80,
) -> list[DividendEvent]:
    events_table_name = "warehouse_events"
    events_table = _qualified_table(events_table_name)
    event_columns = _warehouse_columns(events_table_name)

    params: dict[str, object] = {"limit": limit}
    filters = [
        "event_date IS NOT NULL",
        "("
        "event_type_id IN (1, 2, 3, 4, 5) "
        "OR event_type ILIKE '%cổ tức%' "
        "OR title ILIKE '%cổ tức%' "
        "OR event_type ILIKE '%thưởng cổ phiếu%' "
        "OR title ILIKE '%thưởng cổ phiếu%' "
        "OR event_type ILIKE '%phát hành thêm%' "
        "OR title ILIKE '%phát hành thêm%'"
        ")",
    ]

    if ticker:
        filters.append("ticker = :ticker")
        params["ticker"] = ticker.upper()

    if start_date is not None:
        filters.append("event_date >= :start_date")
        params["start_date"] = start_date

    if end_date is not None:
        filters.append("event_date <= :end_date")
        params["end_date"] = end_date

    if upcoming_only:
        filters.append("event_date >= CURRENT_DATE")

    event_id_expr = _optional_column(event_columns, "event_id", "text")
    event_type_id_expr = _optional_column(event_columns, "event_type_id", "integer")
    event_year_expr = _optional_column(event_columns, "event_year", "integer")
    pay_time_expr = _optional_column(event_columns, "pay_time", "integer")
    ratio_display_expr = _optional_column(event_columns, "ratio_display", "text")
    value_display_expr = _optional_column(event_columns, "value_display", "text")
    source_url_expr = _optional_column(event_columns, "source_url", "text")
    record_date_expr = _optional_date_column(event_columns, "record_date")
    exright_date_expr = _optional_date_column(event_columns, "exright_date")
    payment_date_expr = _optional_date_column(event_columns, "payment_date")
    public_date_expr = _optional_date_column(event_columns, "public_date")

    order_direction = "ASC" if upcoming_only else "DESC"
    where_clause = " AND ".join(filters)

    query = text(
        f"""
        WITH normalized_events AS (
            SELECT
                events.ticker::text AS ticker,
                {event_id_expr} AS event_id,
                COALESCE(
                    {exright_date_expr},
                    {record_date_expr},
                    {payment_date_expr},
                    {public_date_expr}
                ) AS event_date,
                events.event_title::text AS title,
                events.event_type::text AS event_type,
                COALESCE({event_type_id_expr}, 0)::integer AS event_type_id,
                {record_date_expr} AS record_date,
                {exright_date_expr} AS exright_date,
                {payment_date_expr} AS payment_date,
                {public_date_expr} AS public_date,
                {event_year_expr} AS event_year,
                {pay_time_expr} AS pay_time,
                events.ratio::double precision AS ratio,
                events.value::double precision AS value,
                {ratio_display_expr} AS ratio_display,
                {value_display_expr} AS value_display,
                {source_url_expr} AS source_url
            FROM {events_table} AS events
            WHERE events.ticker IS NOT NULL
              AND events.event_title IS NOT NULL
        ),
        deduped_events AS (
            SELECT DISTINCT ON (
                ticker,
                COALESCE(event_id, ''),
                event_date,
                title,
                COALESCE(ratio, -999999),
                COALESCE(value, -999999)
            )
                ticker,
                event_date,
                title,
                event_type,
                NULLIF(event_type_id, 0) AS event_type_id,
                record_date,
                exright_date,
                payment_date,
                public_date,
                event_year,
                pay_time,
                ratio,
                value,
                ratio_display,
                value_display,
                source_url,
                CASE
                    WHEN event_date >= CURRENT_DATE
                    THEN event_date - CURRENT_DATE
                    ELSE NULL
                END AS days_until
            FROM normalized_events
            WHERE {where_clause}
            ORDER BY
                ticker,
                COALESCE(event_id, ''),
                event_date,
                title,
                COALESCE(ratio, -999999),
                COALESCE(value, -999999)
        )
        SELECT
            ticker,
            event_date AS date,
            title,
            event_type,
            event_type_id,
            record_date,
            exright_date,
            payment_date,
            public_date,
            event_year,
            pay_time,
            ratio,
            value,
            ratio_display,
            value_display,
            source_url,
            days_until
        FROM deduped_events
        ORDER BY event_date {order_direction}, ticker, title
        LIMIT :limit
        """
    )

    with engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(query, params).mappings().all()]

    for row in rows:
        for key in ("title", "event_type", "ratio_display", "value_display"):
            row[key] = _repair_mojibake(row.get(key))

    return [DividendEvent(**row) for row in rows]


def get_chart_annotations(
    ticker: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[ChartAnnotation]:
    ticker = ticker.upper()
    price_table = settings.qualified_table
    events_table = _qualified_table("warehouse_events")
    news_table = _qualified_table("warehouse_news")

    date_filters = []
    event_date_filters = []
    news_date_filters = []
    params: dict[str, object] = {"ticker": ticker}
    if start_date is not None:
        date_filters.append("annotation_date >= :start_date")
        event_date_filters.append(
            "COALESCE(NULLIF(exright_date, ''), NULLIF(record_date, ''), NULLIF(public_date, ''))::date >= :start_date"
        )
        news_date_filters.append("news.date_posted::date >= :start_date")
        params["start_date"] = start_date
    if end_date is not None:
        date_filters.append("annotation_date <= :end_date")
        event_date_filters.append(
            "COALESCE(NULLIF(exright_date, ''), NULLIF(record_date, ''), NULLIF(public_date, ''))::date <= :end_date"
        )
        news_date_filters.append("news.date_posted::date <= :end_date")
        params["end_date"] = end_date

    date_filter_clause = f"WHERE {' AND '.join(date_filters)}" if date_filters else ""
    event_date_filter_clause = f" AND {' AND '.join(event_date_filters)}" if event_date_filters else ""
    news_date_filter_clause = f" AND {' AND '.join(news_date_filters)}" if news_date_filters else ""

    query = text(
        f"""
        WITH raw_dividend_events AS (
            SELECT
                ticker,
                COALESCE(NULLIF(exright_date, ''), NULLIF(record_date, ''), NULLIF(public_date, ''))::date AS annotation_date,
                'event' AS type,
                event_title AS title,
                NULL::text AS url,
                ratio,
                value,
                event_type AS source,
                NULL::text AS sentiment,
                NULL::double precision AS price_change,
                NULL::date AS price_change_date
            FROM {events_table}
            WHERE ticker = :ticker
              AND (event_type ILIKE '%cổ tức%' OR event_title ILIKE '%cổ tức%')
              AND COALESCE(NULLIF(exright_date, ''), NULLIF(record_date, ''), NULLIF(public_date, '')) IS NOT NULL
              {event_date_filter_clause}
        ),
        dividend_events AS (
            SELECT DISTINCT ON (ticker, annotation_date, title, ratio, value)
                ticker,
                annotation_date,
                type,
                title,
                url,
                ratio,
                value,
                source,
                sentiment,
                price_change,
                price_change_date
            FROM raw_dividend_events
            ORDER BY ticker, annotation_date, title, ratio, value, source
        ),
        filtered_news AS (
            SELECT news.*
            FROM {news_table} AS news
            WHERE news.ticker = :ticker
              AND news.date_posted IS NOT NULL
              AND news.title IS NOT NULL
              {news_date_filter_clause}
        ),
        ticker_news AS (
            SELECT DISTINCT ON (date_posted, title, url)
                news.ticker,
                news.date_posted::date AS annotation_date,
                'news' AS type,
                news.title,
                news.url,
                NULL::double precision AS ratio,
                NULL::double precision AS value,
                news.source,
                news.sentiment::text AS sentiment,
                NULL::double precision AS price_change,
                NULL::date AS price_change_date
            FROM filtered_news AS news
            ORDER BY news.date_posted, news.title, news.url
        ),
        combined_annotations AS (
            SELECT * FROM dividend_events
            UNION ALL
            SELECT * FROM ticker_news
        )
        SELECT
            ticker,
            annotation_date AS date,
            type,
            title,
            url,
            ratio,
            value,
            source,
            sentiment,
            price_change,
            price_change_date
        FROM combined_annotations
        {date_filter_clause}
        ORDER BY annotation_date, type, title
        """
    )

    with engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(query, params).mappings().all()]

        news_dates = sorted({row["date"] for row in rows if row["type"] == "news"})
        if news_dates:
            price_query = text(
                f"""
                SELECT date, close, chg_1d
                FROM (
                    SELECT DISTINCT ON ({columns["date"]})
                        {columns["date"]}::date AS date,
                        {columns["close"]}::double precision AS close,
                        chg_1d::double precision AS chg_1d
                    FROM {price_table}
                    WHERE {columns["ticker"]} = :ticker
                      AND {columns["date"]}::date <= :max_news_date
                      AND {columns["close"]} IS NOT NULL
                      AND {columns["close"]} > 0
                    ORDER BY {columns["date"]} DESC, (chg_1d IS NOT NULL)::int DESC
                ) AS deduped_prices
                ORDER BY date
                """
            )
            price_rows = [
                dict(row)
                for row in conn.execute(price_query, {"ticker": ticker, "max_news_date": news_dates[-1]}).mappings().all()
            ]

            price_dates = [row["date"] for row in price_rows]
            price_changes: list[dict[str, object]] = []
            previous_close: float | None = None
            for row in price_rows:
                close = float(row["close"])
                change = row["chg_1d"]
                if change is None and previous_close not in (None, 0):
                    change = ((close - previous_close) / previous_close) * 100

                price_changes.append(
                    {
                        "date": row["date"],
                        "change": float(change) if change is not None else None,
                    }
                )
                previous_close = close

            for row in rows:
                if row["type"] != "news":
                    continue

                price_index = bisect_right(price_dates, row["date"]) - 1
                if price_index < 0:
                    continue

                price_match = price_changes[price_index]
                row["price_change"] = price_match["change"]
                row["price_change_date"] = price_match["date"]

    return [ChartAnnotation(**row) for row in rows]


def get_market_news_annotations(
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 120,
) -> list[ChartAnnotation]:
    price_table = settings.qualified_table
    news_table = _qualified_table("warehouse_news")

    news_filters = [
        "news.date_posted IS NOT NULL",
        "news.title IS NOT NULL",
        """
        (
            UPPER(news.ticker) IN ('VN30', 'VN100', 'VNINDEX')
            OR UPPER(COALESCE(news.tags, '')) LIKE '%VN30%'
            OR UPPER(COALESCE(news.tags, '')) LIKE '%VN100%'
            OR UPPER(COALESCE(news.tags, '')) LIKE '%VNINDEX%'
        )
        """,
    ]
    params: dict[str, object] = {"limit": limit}
    if start_date is not None:
        news_filters.append("news.date_posted::date >= :start_date")
        params["start_date"] = start_date
    if end_date is not None:
        news_filters.append("news.date_posted::date <= :end_date")
        params["end_date"] = end_date

    query = text(
        f"""
        SELECT DISTINCT ON (date_posted, title, url)
            COALESCE(NULLIF(news.ticker, ''), 'VNINDEX') AS ticker,
            news.date_posted::date AS date,
            'news' AS type,
            news.title,
            news.url,
            NULL::double precision AS ratio,
            NULL::double precision AS value,
            news.source,
            news.sentiment::text AS sentiment,
            NULL::double precision AS price_change,
            NULL::date AS price_change_date
        FROM {news_table} AS news
        WHERE {" AND ".join(news_filters)}
        ORDER BY date_posted DESC, title, url
        LIMIT :limit
        """
    )

    with engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(query, params).mappings().all()]

        news_dates = sorted({row["date"] for row in rows})
        if news_dates:
            price_query = text(
                f"""
                SELECT date, close, chg_1d
                FROM (
                    SELECT DISTINCT ON ({columns["date"]})
                        {columns["date"]}::date AS date,
                        {columns["close"]}::double precision AS close,
                        chg_1d::double precision AS chg_1d
                    FROM {price_table}
                    WHERE {columns["ticker"]} = 'VNINDEX'
                      AND {columns["date"]}::date <= :max_news_date
                      AND {columns["close"]} IS NOT NULL
                      AND {columns["close"]} > 0
                    ORDER BY {columns["date"]} DESC, (chg_1d IS NOT NULL)::int DESC
                ) AS deduped_prices
                ORDER BY date
                """
            )
            price_rows = [
                dict(row)
                for row in conn.execute(price_query, {"max_news_date": news_dates[-1]}).mappings().all()
            ]

            price_dates = [row["date"] for row in price_rows]
            price_changes: list[dict[str, object]] = []
            previous_close: float | None = None
            for row in price_rows:
                close = float(row["close"])
                change = row["chg_1d"]
                if change is None and previous_close not in (None, 0):
                    change = ((close - previous_close) / previous_close) * 100

                price_changes.append(
                    {
                        "date": row["date"],
                        "change": float(change) if change is not None else None,
                    }
                )
                previous_close = close

            for row in rows:
                price_index = bisect_right(price_dates, row["date"]) - 1
                if price_index < 0:
                    continue

                price_match = price_changes[price_index]
                row["price_change"] = price_match["change"]
                row["price_change_date"] = price_match["date"]

    return [ChartAnnotation(**row) for row in rows]


def get_latest_news_date() -> date | None:
    news_table = _qualified_table("warehouse_news")
    query = text(
        f"""
        SELECT MAX(date_posted::date) AS latest_date
        FROM {news_table}
        WHERE date_posted IS NOT NULL
        """
    )

    with engine.connect() as conn:
        row = conn.execute(query).mappings().first()

    return row["latest_date"] if row else None
