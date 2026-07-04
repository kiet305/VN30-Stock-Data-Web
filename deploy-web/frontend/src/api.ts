import type {
  AnalysisReportsResponse,
  AnalysisRunStatusResponse,
  Candle,
  ChartAnnotation,
  DividendEvent,
  FinancialDashboard,
  LlmConfigResponse,
  LlmConfigUpdate,
  NewsLatestDateResponse,
  SectorOverviewResponse,
  SocialResponse,
  StockInfo,
  TrendResponse,
  ValuationBacktestResponse,
  ValuationRankingResponse,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function fetchTickers(): Promise<string[]> {
  const response = await fetch(`${API_BASE_URL}/api/tickers`);
  if (!response.ok) {
    throw new Error("Không tải được danh sách mã");
  }

  const payload = (await response.json()) as { tickers: string[] };
  return payload.tickers;
}

export async function fetchCandles(params: {
  ticker: string;
  startDate?: string;
  endDate?: string;
  limit?: number;
}): Promise<Candle[]> {
  const searchParams = new URLSearchParams({
    ticker: params.ticker,
  });

  if (params.startDate) {
    searchParams.set("start_date", params.startDate);
  }

  if (params.endDate) {
    searchParams.set("end_date", params.endDate);
  }

  if (params.limit) {
    searchParams.set("limit", String(params.limit));
  }

  const response = await fetch(`${API_BASE_URL}/api/candles?${searchParams.toString()}`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Không tải được dữ liệu nến");
  }

  return (await response.json()) as Candle[];
}

export async function fetchStockInfo(ticker: string): Promise<StockInfo> {
  const searchParams = new URLSearchParams({ ticker });
  const response = await fetch(`${API_BASE_URL}/api/stock-info?${searchParams.toString()}`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Không tải được thông tin cổ phiếu");
  }

  return (await response.json()) as StockInfo;
}

export async function fetchFinancialDashboard(ticker: string): Promise<FinancialDashboard> {
  const searchParams = new URLSearchParams({ ticker });
  const response = await fetch(`${API_BASE_URL}/api/financial-dashboard?${searchParams.toString()}`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Không tải được dashboard BCTC");
  }

  return (await response.json()) as FinancialDashboard;
}

export async function fetchAnalysisReports(ticker: string): Promise<AnalysisReportsResponse> {
  const searchParams = new URLSearchParams({ ticker });
  const response = await fetch(`${API_BASE_URL}/api/analysis-reports?${searchParams.toString()}`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Không tải được báo cáo phân tích AI");
  }

  return (await response.json()) as AnalysisReportsResponse;
}

export async function startAnalysisReportRun(ticker: string): Promise<AnalysisRunStatusResponse> {
  const searchParams = new URLSearchParams({ ticker });
  const response = await fetch(`${API_BASE_URL}/api/analysis-reports/run?${searchParams.toString()}`, {
    method: "POST",
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Không kích hoạt được báo cáo phân tích AI");
  }

  return (await response.json()) as AnalysisRunStatusResponse;
}

export async function fetchAnalysisRunStatus(params: {
  ticker: string;
  startedAt?: string | null;
}): Promise<AnalysisRunStatusResponse> {
  const searchParams = new URLSearchParams({ ticker: params.ticker });
  if (params.startedAt) {
    searchParams.set("started_at", params.startedAt);
  }

  const response = await fetch(`${API_BASE_URL}/api/analysis-reports/status?${searchParams.toString()}`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Không tải được tiến trình báo cáo phân tích AI");
  }

  return (await response.json()) as AnalysisRunStatusResponse;
}

export async function fetchLlmConfig(): Promise<LlmConfigResponse> {
  const response = await fetch(`${API_BASE_URL}/api/llm-config`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Không tải được cấu hình LLM");
  }

  return (await response.json()) as LlmConfigResponse;
}

export async function updateLlmConfig(payload: LlmConfigUpdate): Promise<LlmConfigResponse> {
  const response = await fetch(`${API_BASE_URL}/api/llm-config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorPayload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(errorPayload?.detail ?? "Không lưu được cấu hình LLM");
  }

  return (await response.json()) as LlmConfigResponse;
}

export async function fetchChartAnnotations(params: {
  ticker: string;
  startDate?: string;
  endDate?: string;
}): Promise<ChartAnnotation[]> {
  const searchParams = new URLSearchParams({ ticker: params.ticker });

  if (params.startDate) {
    searchParams.set("start_date", params.startDate);
  }

  if (params.endDate) {
    searchParams.set("end_date", params.endDate);
  }

  const response = await fetch(`${API_BASE_URL}/api/chart-annotations?${searchParams.toString()}`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Không tải được sự kiện và tin tức");
  }

  return (await response.json()) as ChartAnnotation[];
}

export async function fetchNewsLatestDate(): Promise<NewsLatestDateResponse> {
  const response = await fetch(`${API_BASE_URL}/api/news/latest-date`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "KhÃ´ng táº£i Ä‘Æ°á»£c ngÃ y cáº­p nháº­t tin tá»©c");
  }

  return (await response.json()) as NewsLatestDateResponse;
}

export async function fetchMarketNews(params: {
  startDate?: string;
  endDate?: string;
  limit?: number;
} = {}): Promise<ChartAnnotation[]> {
  const searchParams = new URLSearchParams();

  if (params.startDate) {
    searchParams.set("start_date", params.startDate);
  }

  if (params.endDate) {
    searchParams.set("end_date", params.endDate);
  }

  if (params.limit) {
    searchParams.set("limit", String(params.limit));
  }

  const query = searchParams.toString();
  const response = await fetch(`${API_BASE_URL}/api/market-news${query ? `?${query}` : ""}`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Không tải được tin tức thị trường");
  }

  return (await response.json()) as ChartAnnotation[];
}

export async function fetchDividendEvents(params: {
  ticker?: string;
  startDate?: string;
  endDate?: string;
  upcomingOnly?: boolean;
  limit?: number;
}): Promise<DividendEvent[]> {
  const searchParams = new URLSearchParams();

  if (params.ticker) {
    searchParams.set("ticker", params.ticker);
  }

  if (params.startDate) {
    searchParams.set("start_date", params.startDate);
  }

  if (params.endDate) {
    searchParams.set("end_date", params.endDate);
  }

  if (params.upcomingOnly) {
    searchParams.set("upcoming_only", "true");
  }

  if (params.limit) {
    searchParams.set("limit", String(params.limit));
  }

  const response = await fetch(`${API_BASE_URL}/api/dividend-events?${searchParams.toString()}`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Không tải được lịch cổ tức");
  }

  return (await response.json()) as DividendEvent[];
}

export async function fetchTrends(limit = 50): Promise<TrendResponse> {
  const searchParams = new URLSearchParams({ limit: String(limit) });
  const response = await fetch(`${API_BASE_URL}/api/trends?${searchParams.toString()}`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Không tải được dữ liệu xu hướng");
  }

  return (await response.json()) as TrendResponse;
}

export async function fetchSocialRankings(limit = 50): Promise<SocialResponse> {
  const searchParams = new URLSearchParams({ limit: String(limit) });
  const response = await fetch(`${API_BASE_URL}/api/social?${searchParams.toString()}`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Không tải được dữ liệu social");
  }

  return (await response.json()) as SocialResponse;
}

export async function fetchValuationRankings(tickers: string[], limit = 10): Promise<ValuationRankingResponse> {
  const searchParams = new URLSearchParams({ limit: String(limit) });
  tickers.forEach((ticker) => searchParams.append("tickers", ticker));

  const response = await fetch(`${API_BASE_URL}/api/valuation-rankings?${searchParams.toString()}`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Không tải được dữ liệu định giá thị trường");
  }

  return (await response.json()) as ValuationRankingResponse;
}

export async function fetchValuationBacktest(ticker: string, limit = 10): Promise<ValuationBacktestResponse> {
  const searchParams = new URLSearchParams({ ticker, limit: String(limit) });
  const response = await fetch(`${API_BASE_URL}/api/valuation-backtest?${searchParams.toString()}`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Không tải được dữ liệu backtest định giá");
  }

  return (await response.json()) as ValuationBacktestResponse;
}

export async function fetchSectorOverview(topLimit = 5): Promise<SectorOverviewResponse> {
  const searchParams = new URLSearchParams({ top_limit: String(topLimit) });
  const response = await fetch(`${API_BASE_URL}/api/sector-overview?${searchParams.toString()}`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Không tải được dữ liệu ngành");
  }

  return (await response.json()) as SectorOverviewResponse;
}
