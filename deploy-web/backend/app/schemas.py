from __future__ import annotations

from datetime import date as Date
from datetime import datetime as DateTime

from pydantic import BaseModel


class Candle(BaseModel):
    ticker: str
    date: Date
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


class StockValuation(BaseModel):
    ticker: str
    latest_period: str | None = None
    current_price: float | None = None
    multiple_target_price_6m: float | None = None
    multiple_target_price_12m: float | None = None
    pe_pb_target_price_6m: float | None = None
    pe_pb_target_price_12m: float | None = None
    ev_ebitda_target_price_6m: float | None = None
    ev_ebitda_target_price_12m: float | None = None
    enterprise_value: float | None = None
    net_debt: float | None = None
    trailing_ebitda: float | None = None
    ev_ebitda: float | None = None
    industry_ev_ebitda: float | None = None
    ev_ebitda_premium: float | None = None
    dcf_target_price: float | None = None
    dcf_target_price_6m: float | None = None
    dcf_upside: float | None = None
    dcf_weight: float | None = None
    multiple_weight: float | None = None
    discount_rate: float | None = None
    terminal_growth: float | None = None
    normalized_fcf: float | None = None
    target_price_6m: float | None = None
    target_price_12m: float | None = None
    upside_6m: float | None = None
    upside_12m: float | None = None
    profit_growth_6m: float | None = None
    profit_growth_12m: float | None = None
    equity_growth_12m: float | None = None
    industry_comparison: "IndustryComparison | None" = None
    method: str


class ValuationBacktestPoint(BaseModel):
    ticker: str
    period: str
    period_end: Date | None = None
    base_date: Date | None = None
    base_price: float | None = None
    target_price_6m: float | None = None
    target_price_12m: float | None = None
    actual_date_6m: Date | None = None
    actual_price_6m: float | None = None
    actual_date_12m: Date | None = None
    actual_price_12m: float | None = None
    target_return_6m: float | None = None
    actual_return_6m: float | None = None
    target_error_6m: float | None = None
    target_return_12m: float | None = None
    actual_return_12m: float | None = None
    target_error_12m: float | None = None


class ValuationBacktestResponse(BaseModel):
    ticker: str
    total: int
    points: list[ValuationBacktestPoint]


class ValuationRankingItem(BaseModel):
    ticker: str
    latest_period: str | None = None
    current_price: float | None = None
    target_price_6m: float | None = None
    target_price_12m: float | None = None
    upside_6m: float | None = None
    upside_12m: float | None = None
    multiple_target_price_12m: float | None = None
    dcf_target_price: float | None = None
    ev_ebitda: float | None = None
    industry_ev_ebitda: float | None = None
    dcf_upside: float | None = None
    method: str


class ValuationRankingResponse(BaseModel):
    universe_size: int
    covered_count: int
    items: list[ValuationRankingItem]
    promising: list[ValuationRankingItem]
    risky: list[ValuationRankingItem]


class SectorConstituent(BaseModel):
    ticker: str
    name: str | None = None
    subindustry: str | None = None
    market_cap: float | None = None
    close: float | None = None
    pe: float | None = None
    pb: float | None = None
    weight: float | None = None
    change_1d: float | None = None
    change_1w: float | None = None
    change_1m: float | None = None
    change_3m: float | None = None
    change_6m: float | None = None
    change_1y: float | None = None
    change_3y: float | None = None


class SectorOverviewItem(BaseModel):
    industry: str
    ticker_count: int
    total_market_cap: float | None = None
    average_pe: float | None = None
    average_pb: float | None = None
    weighted_change_1d: float | None = None
    weighted_change_1w: float | None = None
    weighted_change_1m: float | None = None
    weighted_change_3m: float | None = None
    weighted_change_6m: float | None = None
    weighted_change_1y: float | None = None
    weighted_change_3y: float | None = None
    advancers: int = 0
    decliners: int = 0
    unchanged: int = 0
    top_constituents: list[SectorConstituent]


class SectorOverviewResponse(BaseModel):
    as_of: Date | None = None
    sector_count: int
    total_market_cap: float | None = None
    items: list[SectorOverviewItem]


class IndustryComparison(BaseModel):
    industry: str | None = None
    subindustry: str | None = None
    peer_count: int = 0
    pe: float | None = None
    industry_pe: float | None = None
    pe_premium: float | None = None
    pb: float | None = None
    industry_pb: float | None = None
    pb_premium: float | None = None
    roe: float | None = None
    industry_roe: float | None = None
    roa: float | None = None
    industry_roa: float | None = None
    ros: float | None = None
    industry_ros: float | None = None


class StockOverview(BaseModel):
    name: str | None = None
    company_profile: str | None = None
    exchange: str | None = None
    issue_share: int | None = None
    free_float_percentage: float | None = None
    foreign_percentage: float | None = None


class StockOfficer(BaseModel):
    name: str | None = None
    position: str | None = None
    ownership_percentage: float | None = None
    ownership_quantity: float | None = None


class StockShareholder(BaseModel):
    name: str | None = None
    ownership_percentage: float | None = None
    ownership_quantity: float | None = None


class StockInfo(BaseModel):
    ticker: str
    date: Date | None = None
    reference: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    average_volume_10d: float | None = None
    change_1d: float | None = None
    change_3d: float | None = None
    change_1w: float | None = None
    change_1m: float | None = None
    change_3m: float | None = None
    change_6m: float | None = None
    change_1y: float | None = None
    beta: float | None = None
    market_cap: float | None = None
    pe: float | None = None
    pb: float | None = None
    eps: float | None = None
    bvps: float | None = None
    issue_share: int | None = None
    overview: StockOverview | None = None
    shareholders: list[StockShareholder] = []
    officers: list[StockOfficer] = []
    valuation: StockValuation | None = None


class ChartAnnotation(BaseModel):
    ticker: str
    date: Date
    type: str
    title: str
    url: str | None = None
    ratio: float | None = None
    value: float | None = None
    source: str | None = None
    sentiment: str | None = None
    price_change: float | None = None
    price_change_date: Date | None = None


class NewsLatestDateResponse(BaseModel):
    latest_date: Date | None = None


class DividendEvent(BaseModel):
    ticker: str
    date: Date
    title: str
    event_type: str | None = None
    event_type_id: int | None = None
    record_date: Date | None = None
    exright_date: Date | None = None
    payment_date: Date | None = None
    public_date: Date | None = None
    event_year: int | None = None
    pay_time: int | None = None
    ratio: float | None = None
    value: float | None = None
    ratio_display: str | None = None
    value_display: str | None = None
    source_url: str | None = None
    days_until: int | None = None


class FinancialPoint(BaseModel):
    period: str
    year: int
    quarter: int
    value: float | None = None


class FinancialSeries(BaseModel):
    key: str
    label: str
    unit: str
    points: list[FinancialPoint]


class FinancialMetricSeries(BaseModel):
    key: str
    label: str
    unit: str
    points: list[FinancialPoint]


class FinancialStatementPeriod(BaseModel):
    key: str
    label: str
    year: int
    quarter: int


class FinancialStatementRow(BaseModel):
    key: str
    item_id: str
    name_vi: str
    name_en: str | None = None
    criteria: str
    section: str | None = None
    display_order: int
    parent_key: str | None = None
    level: int = 0
    is_total: bool = False
    unit: str | None = None
    values: dict[str, float | None]


class FinancialStatement(BaseModel):
    type: str
    label: str
    periods: list[FinancialStatementPeriod]
    rows: list[FinancialStatementRow]


class FinancialDashboard(BaseModel):
    ticker: str
    latest_period: str | None = None
    series: list[FinancialSeries]
    metric_series: list[FinancialMetricSeries] = []
    statements: list[FinancialStatement] = []


class TrendItem(BaseModel):
    rank: int
    keyword: str
    search_volume: str
    started: DateTime | None = None
    ended: DateTime | None = None
    started_label: str
    status_label: str
    duration_label: str | None = None
    active: bool
    trend_breakdown: list[str]
    trend_points: list[float]
    explore_url: str


class TrendResponse(BaseModel):
    source_file: str
    updated_at: DateTime | None = None
    total: int
    items: list[TrendItem]


class SocialTickerItem(BaseModel):
    rank: int
    ticker: str
    interest_score: float
    attention_share: float
    total_interactions: float
    posts: int
    active_days: int
    latest_date: Date | None = None
    likes: float
    shares: float
    love: float
    wow: float
    haha: float
    sad: float


class SocialResponse(BaseModel):
    source_file: str
    updated_at: DateTime | None = None
    date_from: Date | None = None
    date_to: Date | None = None
    total_tickers: int
    total_interest_score: float
    items: list[SocialTickerItem]


class AnalysisReportSection(BaseModel):
    key: str
    title: str
    agent: str
    source_file: str
    last_modified: DateTime
    trade_date: str | None = None
    content: str
    word_count: int


class AnalysisReportsResponse(BaseModel):
    ticker: str
    source_dirs: list[str]
    updated_at: DateTime | None = None
    total: int
    sections: list[AnalysisReportSection]


class AnalysisRunStep(BaseModel):
    key: str
    title: str
    agent: str
    status: str
    detail: str
    source_file: str | None = None
    last_modified: DateTime | None = None
    word_count: int | None = None
    preview: str | None = None


class AnalysisRunLogEntry(BaseModel):
    timestamp: DateTime | None = None
    agent: str | None = None
    message: str
    source: str | None = None


class AnalysisRunStatusResponse(BaseModel):
    ticker: str
    source_dirs: list[str]
    started_at: DateTime | None = None
    updated_at: DateTime
    running: bool
    progress: float
    message: str
    steps: list[AnalysisRunStep]
    logs: list[AnalysisRunLogEntry]


class LlmProviderOption(BaseModel):
    provider: str
    label: str
    key_env: str | None = None
    default_model: str


class LlmConfigResponse(BaseModel):
    provider: str
    model: str
    key_env: str | None = None
    has_api_key: bool
    api_key_preview: str | None = None
    updated_at: DateTime | None = None
    source: str
    providers: list[LlmProviderOption]


class LlmConfigUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False


class HealthResponse(BaseModel):
    status: str


class TickerResponse(BaseModel):
    tickers: list[str]
