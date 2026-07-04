from datetime import date, datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.schemas import (
    AnalysisReportsResponse,
    AnalysisRunStatusResponse,
    ChartAnnotation,
    DividendEvent,
    FinancialDashboard,
    HealthResponse,
    LlmConfigResponse,
    LlmConfigUpdate,
    NewsLatestDateResponse,
    SectorOverviewResponse,
    SocialResponse,
    StockInfo,
    StockValuation,
    TickerResponse,
    TrendResponse,
    ValuationBacktestResponse,
    ValuationRankingResponse,
)
from app.services.analysis_reports import get_analysis_reports, get_analysis_run_status, start_analysis_report_run
from app.services.llm_config import get_llm_config, update_llm_config
from app.services.market_data import (
    get_candles,
    get_chart_annotations,
    get_dividend_events,
    get_financial_dashboard,
    get_latest_news_date,
    get_market_news_annotations,
    get_sector_overview,
    get_stock_info,
    get_stock_valuation,
    get_tickers,
    get_valuation_backtest,
    get_valuation_rankings,
)
from app.services.social_data import get_social_rankings
from app.services.trend_data import get_trends


settings = get_settings()

app = FastAPI(
    title="Deploy Web API",
    version="0.1.0",
    description="API đọc dữ liệu biểu đồ nến từ PostgreSQL",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/api/tickers", response_model=TickerResponse)
def list_tickers() -> TickerResponse:
    try:
        tickers = get_tickers()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return TickerResponse(tickers=tickers)


@app.get("/api/candles")
def list_candles(
    ticker: str = Query(..., min_length=1, max_length=20),
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=200, ge=10, le=2000),
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="Ngày bắt đầu phải nhỏ hơn hoặc bằng ngày kết thúc")

    try:
        candles = get_candles(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not candles:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy dữ liệu cho mã {ticker.upper()}")

    return candles


@app.get("/api/stock-info", response_model=StockInfo)
def stock_info(ticker: str = Query(..., min_length=1, max_length=20)) -> StockInfo:
    try:
        info = get_stock_info(ticker=ticker)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if info is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy thông tin cho mã {ticker.upper()}")

    return info


@app.get("/api/stock-valuation", response_model=StockValuation)
def stock_valuation(ticker: str = Query(..., min_length=1, max_length=20)) -> StockValuation:
    try:
        valuation = get_stock_valuation(ticker=ticker)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if valuation is None:
        raise HTTPException(status_code=404, detail=f"KhÃ´ng tÃ¬m tháº¥y BCTC Ä‘á»ƒ Ä‘á»‹nh giÃ¡ mÃ£ {ticker.upper()}")

    return valuation


@app.get("/api/valuation-backtest", response_model=ValuationBacktestResponse)
def valuation_backtest(
    ticker: str = Query(..., min_length=1, max_length=20),
    limit: int = Query(default=10, ge=3, le=16),
) -> ValuationBacktestResponse:
    try:
        return get_valuation_backtest(ticker=ticker, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/valuation-rankings", response_model=ValuationRankingResponse)
def valuation_rankings(
    tickers: list[str] = Query(default=[]),
    limit: int = Query(default=10, ge=1, le=30),
) -> ValuationRankingResponse:
    try:
        return get_valuation_rankings(tickers=tickers, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/sector-overview", response_model=SectorOverviewResponse)
def sector_overview(top_limit: int = Query(default=5, ge=1, le=10)) -> SectorOverviewResponse:
    try:
        return get_sector_overview(top_limit=top_limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/financial-dashboard", response_model=FinancialDashboard)
def financial_dashboard(
    ticker: str = Query(..., min_length=1, max_length=20),
    periods: int = Query(default=80, ge=4, le=120),
) -> FinancialDashboard:
    try:
        dashboard = get_financial_dashboard(ticker=ticker, period_limit=periods)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if dashboard is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy BCTC cho mã {ticker.upper()}")

    return dashboard


@app.get("/api/analysis-reports", response_model=AnalysisReportsResponse)
def analysis_reports(ticker: str = Query(..., min_length=1, max_length=20)) -> AnalysisReportsResponse:
    try:
        return get_analysis_reports(ticker=ticker)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/analysis-reports/run", response_model=AnalysisRunStatusResponse)
def analysis_reports_run(ticker: str = Query(..., min_length=1, max_length=20)) -> AnalysisRunStatusResponse:
    try:
        return start_analysis_report_run(ticker=ticker)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/analysis-reports/status", response_model=AnalysisRunStatusResponse)
def analysis_reports_status(
    ticker: str = Query(..., min_length=1, max_length=20),
    started_at: datetime | None = None,
) -> AnalysisRunStatusResponse:
    try:
        return get_analysis_run_status(ticker=ticker, started_at=started_at)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/llm-config", response_model=LlmConfigResponse)
def llm_config() -> LlmConfigResponse:
    try:
        return get_llm_config()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.put("/api/llm-config", response_model=LlmConfigResponse)
def save_llm_config(payload: LlmConfigUpdate) -> LlmConfigResponse:
    try:
        return update_llm_config(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/trends", response_model=TrendResponse)
def trends(limit: int = Query(default=50, ge=1, le=200)) -> TrendResponse:
    try:
        return get_trends(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/social", response_model=SocialResponse)
def social_rankings(limit: int = Query(default=50, ge=1, le=100)) -> SocialResponse:
    try:
        return get_social_rankings(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/chart-annotations", response_model=list[ChartAnnotation])
def chart_annotations(
    ticker: str = Query(..., min_length=1, max_length=20),
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[ChartAnnotation]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="Ngày bắt đầu phải nhỏ hơn hoặc bằng ngày kết thúc")

    try:
        return get_chart_annotations(ticker=ticker, start_date=start_date, end_date=end_date)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/news/latest-date", response_model=NewsLatestDateResponse)
def news_latest_date() -> NewsLatestDateResponse:
    try:
        return NewsLatestDateResponse(latest_date=get_latest_news_date())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/market-news", response_model=list[ChartAnnotation])
def market_news(
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=120, ge=1, le=300),
) -> list[ChartAnnotation]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="Ngày bắt đầu phải nhỏ hơn hoặc bằng ngày kết thúc")

    try:
        return get_market_news_annotations(start_date=start_date, end_date=end_date, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/dividend-events", response_model=list[DividendEvent])
def dividend_events(
    ticker: str | None = Query(default=None, min_length=1, max_length=20),
    start_date: date | None = None,
    end_date: date | None = None,
    upcoming_only: bool = False,
    limit: int = Query(default=80, ge=1, le=500),
) -> list[DividendEvent]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="Ngày bắt đầu phải nhỏ hơn hoặc bằng ngày kết thúc")

    try:
        return get_dividend_events(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            upcoming_only=upcoming_only,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
