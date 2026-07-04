export type Candle = {
  ticker: string;
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
};

export type StockInfo = {
  ticker: string;
  date: string | null;
  reference: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  average_volume_10d: number | null;
  change_1d: number | null;
  change_3d: number | null;
  change_1w: number | null;
  change_1m: number | null;
  change_3m: number | null;
  change_6m: number | null;
  change_1y: number | null;
  beta: number | null;
  market_cap: number | null;
  pe: number | null;
  pb: number | null;
  eps: number | null;
  bvps: number | null;
  issue_share: number | null;
  overview: StockOverview | null;
  shareholders: StockShareholder[];
  officers: StockOfficer[];
  valuation: StockValuation | null;
};

export type StockOverview = {
  name: string | null;
  company_profile: string | null;
  exchange: string | null;
  issue_share: number | null;
  free_float_percentage: number | null;
  foreign_percentage: number | null;
};

export type StockOfficer = {
  name: string | null;
  position: string | null;
  ownership_percentage: number | null;
  ownership_quantity: number | null;
};

export type StockShareholder = {
  name: string | null;
  ownership_percentage: number | null;
  ownership_quantity: number | null;
};

export type StockValuation = {
  ticker: string;
  latest_period: string | null;
  current_price: number | null;
  multiple_target_price_6m: number | null;
  multiple_target_price_12m: number | null;
  pe_pb_target_price_6m: number | null;
  pe_pb_target_price_12m: number | null;
  ev_ebitda_target_price_6m: number | null;
  ev_ebitda_target_price_12m: number | null;
  enterprise_value: number | null;
  net_debt: number | null;
  trailing_ebitda: number | null;
  ev_ebitda: number | null;
  industry_ev_ebitda: number | null;
  ev_ebitda_premium: number | null;
  dcf_target_price: number | null;
  dcf_target_price_6m: number | null;
  dcf_upside: number | null;
  dcf_weight: number | null;
  multiple_weight: number | null;
  discount_rate: number | null;
  terminal_growth: number | null;
  normalized_fcf: number | null;
  target_price_6m: number | null;
  target_price_12m: number | null;
  upside_6m: number | null;
  upside_12m: number | null;
  profit_growth_6m: number | null;
  profit_growth_12m: number | null;
  equity_growth_12m: number | null;
  industry_comparison: IndustryComparison | null;
  method: string;
};

export type ValuationBacktestPoint = {
  ticker: string;
  period: string;
  period_end: string | null;
  base_date: string | null;
  base_price: number | null;
  target_price_6m: number | null;
  target_price_12m: number | null;
  actual_date_6m: string | null;
  actual_price_6m: number | null;
  actual_date_12m: string | null;
  actual_price_12m: number | null;
  target_return_6m: number | null;
  actual_return_6m: number | null;
  target_error_6m: number | null;
  target_return_12m: number | null;
  actual_return_12m: number | null;
  target_error_12m: number | null;
};

export type ValuationBacktestResponse = {
  ticker: string;
  total: number;
  points: ValuationBacktestPoint[];
};

export type IndustryComparison = {
  industry: string | null;
  subindustry: string | null;
  peer_count: number;
  pe: number | null;
  industry_pe: number | null;
  pe_premium: number | null;
  pb: number | null;
  industry_pb: number | null;
  pb_premium: number | null;
  roe: number | null;
  industry_roe: number | null;
  roa: number | null;
  industry_roa: number | null;
  ros: number | null;
  industry_ros: number | null;
};

export type ValuationRankingItem = {
  ticker: string;
  latest_period: string | null;
  current_price: number | null;
  target_price_6m: number | null;
  target_price_12m: number | null;
  upside_6m: number | null;
  upside_12m: number | null;
  multiple_target_price_12m: number | null;
  dcf_target_price: number | null;
  ev_ebitda: number | null;
  industry_ev_ebitda: number | null;
  dcf_upside: number | null;
  method: string;
};

export type ValuationRankingResponse = {
  universe_size: number;
  covered_count: number;
  items: ValuationRankingItem[];
  promising: ValuationRankingItem[];
  risky: ValuationRankingItem[];
};

export type SectorConstituent = {
  ticker: string;
  name: string | null;
  subindustry: string | null;
  market_cap: number | null;
  close: number | null;
  pe: number | null;
  pb: number | null;
  weight: number | null;
  change_1d: number | null;
  change_1w: number | null;
  change_1m: number | null;
  change_3m: number | null;
  change_6m: number | null;
  change_1y: number | null;
  change_3y: number | null;
};

export type SectorOverviewItem = {
  industry: string;
  ticker_count: number;
  total_market_cap: number | null;
  average_pe: number | null;
  average_pb: number | null;
  weighted_change_1d: number | null;
  weighted_change_1w: number | null;
  weighted_change_1m: number | null;
  weighted_change_3m: number | null;
  weighted_change_6m: number | null;
  weighted_change_1y: number | null;
  weighted_change_3y: number | null;
  advancers: number;
  decliners: number;
  unchanged: number;
  top_constituents: SectorConstituent[];
};

export type SectorOverviewResponse = {
  as_of: string | null;
  sector_count: number;
  total_market_cap: number | null;
  items: SectorOverviewItem[];
};

export type ChartAnnotation = {
  ticker: string;
  date: string;
  type: "event" | "news";
  title: string;
  url: string | null;
  ratio: number | null;
  value: number | null;
  source: string | null;
  sentiment: string | null;
  price_change: number | null;
  price_change_date: string | null;
};

export type NewsLatestDateResponse = {
  latest_date: string | null;
};

export type DividendEvent = {
  ticker: string;
  date: string;
  title: string;
  event_type: string | null;
  event_type_id: number | null;
  record_date: string | null;
  exright_date: string | null;
  payment_date: string | null;
  public_date: string | null;
  event_year: number | null;
  pay_time: number | null;
  ratio: number | null;
  value: number | null;
  ratio_display: string | null;
  value_display: string | null;
  source_url: string | null;
  days_until: number | null;
};

export type FinancialPoint = {
  period: string;
  year: number;
  quarter: number;
  value: number | null;
};

export type FinancialSeries = {
  key: string;
  label: string;
  unit: string;
  points: FinancialPoint[];
};

export type FinancialMetricSeries = {
  key: string;
  label: string;
  unit: string;
  points: FinancialPoint[];
};

export type FinancialStatementPeriod = {
  key: string;
  label: string;
  year: number;
  quarter: number;
};

export type FinancialStatementRow = {
  key: string;
  item_id: string;
  name_vi: string;
  name_en: string | null;
  criteria: string;
  section: string | null;
  display_order: number;
  parent_key: string | null;
  level: number;
  is_total: boolean;
  unit: string | null;
  values: Record<string, number | null | undefined>;
};

export type FinancialStatement = {
  type: string;
  label: string;
  periods: FinancialStatementPeriod[];
  rows: FinancialStatementRow[];
};

export type FinancialDashboard = {
  ticker: string;
  latest_period: string | null;
  series: FinancialSeries[];
  metric_series: FinancialMetricSeries[];
  statements: FinancialStatement[];
};

export type TrendItem = {
  rank: number;
  keyword: string;
  search_volume: string;
  started: string | null;
  ended: string | null;
  started_label: string;
  status_label: string;
  duration_label: string | null;
  active: boolean;
  trend_breakdown: string[];
  trend_points: number[];
  explore_url: string;
};

export type TrendResponse = {
  source_file: string;
  updated_at: string | null;
  total: number;
  items: TrendItem[];
};

export type SocialTickerItem = {
  rank: number;
  ticker: string;
  interest_score: number;
  attention_share: number;
  total_interactions: number;
  posts: number;
  active_days: number;
  latest_date: string | null;
  likes: number;
  shares: number;
  love: number;
  wow: number;
  haha: number;
  sad: number;
};

export type SocialResponse = {
  source_file: string;
  updated_at: string | null;
  date_from: string | null;
  date_to: string | null;
  total_tickers: number;
  total_interest_score: number;
  items: SocialTickerItem[];
};

export type AnalysisReportSection = {
  key: string;
  title: string;
  agent: string;
  source_file: string;
  last_modified: string;
  trade_date: string | null;
  content: string;
  word_count: number;
};

export type AnalysisReportsResponse = {
  ticker: string;
  source_dirs: string[];
  updated_at: string | null;
  total: number;
  sections: AnalysisReportSection[];
};

export type AnalysisRunStep = {
  key: string;
  title: string;
  agent: string;
  status: "waiting" | "running" | "done" | "error";
  detail: string;
  source_file: string | null;
  last_modified: string | null;
  word_count: number | null;
  preview: string | null;
};

export type AnalysisRunLogEntry = {
  timestamp: string | null;
  agent: string | null;
  message: string;
  source: string | null;
};

export type AnalysisRunStatusResponse = {
  ticker: string;
  source_dirs: string[];
  started_at: string | null;
  updated_at: string;
  running: boolean;
  progress: number;
  message: string;
  steps: AnalysisRunStep[];
  logs: AnalysisRunLogEntry[];
};

export type LlmProviderOption = {
  provider: string;
  label: string;
  key_env: string | null;
  default_model: string;
};

export type LlmConfigResponse = {
  provider: string;
  model: string;
  key_env: string | null;
  has_api_key: boolean;
  api_key_preview: string | null;
  updated_at: string | null;
  source: string;
  providers: LlmProviderOption[];
};

export type LlmConfigUpdate = {
  provider?: string;
  model?: string;
  api_key?: string;
  clear_api_key?: boolean;
};
