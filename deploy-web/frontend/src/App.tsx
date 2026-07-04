import { useCallback, useEffect, useMemo, useState } from "react";

import {
  fetchAnalysisReports,
  fetchCandles,
  fetchChartAnnotations,
  fetchDividendEvents,
  fetchFinancialDashboard,
  fetchMarketNews,
  fetchNewsLatestDate,
  fetchSectorOverview,
  fetchSocialRankings,
  fetchStockInfo,
  fetchTickers,
  fetchTrends,
  fetchValuationRankings,
} from "./api";
import { AnalysisReportsPanel } from "./components/AnalysisReportsPanel";
import { FinancialDashboardPanel } from "./components/FinancialDashboardPanel";
import { NewsEventsPanel } from "./components/NewsEventsPanel";
import { PriceMovementPanel } from "./components/PriceMovementPanel";
import { SectorPanel } from "./components/SectorPanel";
import { SocialPanel } from "./components/SocialPanel";
import { ShareholdersOfficersPanel, StockInfoPanel } from "./components/StockInfoPanel";
import { StockValuationPanel } from "./components/StockValuationPanel";
import { ValuationMarketPanel } from "./components/ValuationMarketPanel";
import type {
  AnalysisReportsResponse,
  Candle,
  ChartAnnotation,
  DividendEvent,
  FinancialDashboard,
  SectorOverviewResponse,
  SocialResponse,
  StockInfo,
  TrendResponse,
  ValuationRankingResponse,
} from "./types";

const DEFAULT_STOCK = "HPG";
const DEFAULT_INDEX = "VNINDEX";
const DEFAULT_LIMIT = 200;
const DEFAULT_START_DATE = "2025-01-01";
const INDEX_TICKERS = ["VNINDEX", "VN30", "VN100", "HNX30", "UPCOMINDEX"];
const VN30_STOCKS = [
  "ACB",
  "BID",
  "BSR",
  "CTG",
  "FPT",
  "GAS",
  "GVR",
  "HDB",
  "HPG",
  "LPB",
  "MBB",
  "MSN",
  "MWG",
  "PLX",
  "POW",
  "SAB",
  "SHB",
  "SSB",
  "SSI",
  "STB",
  "TCB",
  "TPB",
  "VCB",
  "VHM",
  "VIB",
  "VIC",
  "VJC",
  "VNM",
  "VPB",
  "VPL",
];

function getAvailableStocks(tickers: string[]) {
  if (tickers.length === 0) return VN30_STOCKS;

  const availableTickerSet = new Set(tickers.map((item) => item.toUpperCase()));
  return VN30_STOCKS.filter((item) => availableTickerSet.has(item));
}

type TabKey = "watchlist" | "market";
type StockViewKey = "chart" | "info" | "holders" | "valuation" | "financials" | "dividends" | "analysis";
type MarketViewKey = "chart" | "sector" | "valuation" | "social" | "dividends";

type MarketState = {
  input: string;
  selected: string;
  candles: Candle[];
  loading: boolean;
  error: string;
};

function createMarketState(symbol: string): MarketState {
  return {
    input: symbol,
    selected: symbol,
    candles: [],
    loading: false,
    error: "",
  };
}

function getTodayInputValue() {
  const today = new Date();
  const year = today.getFullYear();
  const month = String(today.getMonth() + 1).padStart(2, "0");
  const day = String(today.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function getCandleChange(candles: Candle[], offset: number) {
  const latest = candles[candles.length - 1];
  const reference = candles[candles.length - 1 - offset];
  if (!latest || !reference || reference.close === 0) return null;
  return ((latest.close - reference.close) / reference.close) * 100;
}

function getIndexTradingInfo(ticker: string, candles: Candle[]): StockInfo | null {
  const latest = candles[candles.length - 1];
  const previous = candles[candles.length - 2];
  if (!latest) return null;

  const recentVolumeValues = candles
    .slice(-10)
    .map((item) => item.volume)
    .filter((value): value is number => value !== null && value !== undefined);
  const averageVolume10d =
    recentVolumeValues.length > 0
      ? recentVolumeValues.reduce((total, value) => total + value, 0) / recentVolumeValues.length
      : null;

  return {
    ticker,
    date: latest.date,
    reference: previous?.close ?? null,
    open: latest.open,
    high: latest.high,
    low: latest.low,
    close: latest.close,
    volume: latest.volume,
    average_volume_10d: averageVolume10d,
    change_1d: getCandleChange(candles, 1),
    change_3d: getCandleChange(candles, 3),
    change_1w: getCandleChange(candles, 5),
    change_1m: getCandleChange(candles, 21),
    change_3m: getCandleChange(candles, 63),
    change_6m: getCandleChange(candles, 126),
    change_1y: getCandleChange(candles, 252),
    beta: null,
    market_cap: null,
    pe: null,
    pb: null,
    eps: null,
    bvps: null,
    issue_share: null,
    overview: null,
    shareholders: [],
    officers: [],
    valuation: null,
  };
}

export default function App() {
  const [activeTab, setActiveTab] = useState<TabKey>("watchlist");
  const [stockView, setStockView] = useState<StockViewKey>("chart");
  const [marketView, setMarketView] = useState<MarketViewKey>("chart");
  const [tickers, setTickers] = useState<string[]>([]);
  const [startDate, setStartDate] = useState(DEFAULT_START_DATE);
  const [endDate, setEndDate] = useState(() => getTodayInputValue());
  const [stockState, setStockState] = useState<MarketState>(() => createMarketState(DEFAULT_STOCK));
  const [indexState, setIndexState] = useState<MarketState>(() => createMarketState(DEFAULT_INDEX));
  const [stockInfo, setStockInfo] = useState<StockInfo | null>(null);
  const [stockInfoLoading, setStockInfoLoading] = useState(false);
  const [financialDashboard, setFinancialDashboard] = useState<FinancialDashboard | null>(null);
  const [financialDashboardLoading, setFinancialDashboardLoading] = useState(false);
  const [stockDividendEvents, setStockDividendEvents] = useState<DividendEvent[]>([]);
  const [stockDividendEventsLoading, setStockDividendEventsLoading] = useState(false);
  const [stockDividendEventsError, setStockDividendEventsError] = useState("");
  const [marketDividendEvents, setMarketDividendEvents] = useState<DividendEvent[]>([]);
  const [marketDividendEventsLoading, setMarketDividendEventsLoading] = useState(false);
  const [marketDividendEventsError, setMarketDividendEventsError] = useState("");
  const [marketNews, setMarketNews] = useState<ChartAnnotation[]>([]);
  const [marketNewsError, setMarketNewsError] = useState("");
  const [analysisReports, setAnalysisReports] = useState<AnalysisReportsResponse | null>(null);
  const [analysisReportsLoading, setAnalysisReportsLoading] = useState(false);
  const [analysisReportsError, setAnalysisReportsError] = useState("");
  const refreshAnalysisReports = useCallback(() => {
    setAnalysisReportsLoading(true);
    setAnalysisReportsError("");

    fetchAnalysisReports(stockState.selected)
      .then((payload) => {
        setAnalysisReports(payload);
        setAnalysisReportsLoading(false);
      })
      .catch((err: Error) => {
        setAnalysisReports(null);
        setAnalysisReportsError(err.message);
        setAnalysisReportsLoading(false);
      });
  }, [stockState.selected]);
  const [chartAnnotations, setChartAnnotations] = useState<ChartAnnotation[]>([]);
  const [latestNewsDate, setLatestNewsDate] = useState<string | null>(null);
  const [trends, setTrends] = useState<TrendResponse | null>(null);
  const [social, setSocial] = useState<SocialResponse | null>(null);
  const [socialLoading, setSocialLoading] = useState(false);
  const [socialError, setSocialError] = useState("");
  const [valuationRankings, setValuationRankings] = useState<ValuationRankingResponse | null>(null);
  const [valuationRankingsLoading, setValuationRankingsLoading] = useState(false);
  const [valuationRankingsError, setValuationRankingsError] = useState("");
  const [sectorOverview, setSectorOverview] = useState<SectorOverviewResponse | null>(null);
  const [sectorOverviewLoading, setSectorOverviewLoading] = useState(false);
  const [sectorOverviewError, setSectorOverviewError] = useState("");

  const currentState = activeTab === "watchlist" ? stockState : indexState;
  const setCurrentState = activeTab === "watchlist" ? setStockState : setIndexState;
  const currentCandles = currentState.candles;
  const tabTitle = activeTab === "watchlist" ? "Theo dõi mã cổ phiếu" : "Chỉ số thị trường";
  const activeSymbolLabel = activeTab === "watchlist" ? "Mã đang theo dõi" : "Chỉ số đang xem";
  const submitLabel = activeTab === "watchlist" ? "Tra cứu cổ phiếu" : "Tải chỉ số";
  const inputLabel = activeTab === "watchlist" ? "Tìm kiếm cổ phiếu" : "Mã chỉ số";
  const inputPlaceholder = activeTab === "watchlist" ? "Nhập mã VN30, VD: HPG" : "VD: VNINDEX";
  const symbolInputId = activeTab === "watchlist" ? "stock-symbol-input" : "index-symbol-input";
  const symbolListId = activeTab === "watchlist" ? "vn30-stock-list" : "market-index-list";
  const stockOptions = useMemo(() => getAvailableStocks(tickers), [tickers]);
  const indexOptions = useMemo(
    () => INDEX_TICKERS.filter((item) => tickers.length === 0 || tickers.includes(item)),
    [tickers],
  );

  useEffect(() => {
    let ignore = false;

    fetchTickers()
      .then((items) => {
        if (ignore) return;

        setTickers(items);
        const availableStocks = getAvailableStocks(items);
        if (availableStocks.length > 0 && !availableStocks.includes(DEFAULT_STOCK)) {
          setStockState((previous) => ({
            ...previous,
            input: availableStocks[0],
            selected: availableStocks[0],
          }));
        }
      })
      .catch((err: Error) => {
        if (!ignore) {
          setStockState((previous) => ({ ...previous, error: err.message }));
        }
      });

    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    let ignore = false;

    setStockInfoLoading(true);
    fetchStockInfo(stockState.selected)
      .then((info) => {
        if (!ignore) {
          setStockInfo(info);
          setStockInfoLoading(false);
        }
      })
      .catch(() => {
        if (!ignore) {
          setStockInfo(null);
          setStockInfoLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [stockState.selected]);

  useEffect(() => {
    if (activeTab !== "watchlist" || stockView !== "analysis") return;

    let ignore = false;

    setAnalysisReportsLoading(true);
    setAnalysisReportsError("");
    setAnalysisReports(null);
    fetchAnalysisReports(stockState.selected)
      .then((payload) => {
        if (!ignore) {
          setAnalysisReports(payload);
          setAnalysisReportsLoading(false);
        }
      })
      .catch((err: Error) => {
        if (!ignore) {
          setAnalysisReports(null);
          setAnalysisReportsError(err.message);
          setAnalysisReportsLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [activeTab, stockState.selected, stockView]);

  useEffect(() => {
    let ignore = false;

    setFinancialDashboardLoading(true);
    fetchFinancialDashboard(stockState.selected)
      .then((dashboard) => {
        if (!ignore) {
          setFinancialDashboard(dashboard);
          setFinancialDashboardLoading(false);
        }
      })
      .catch(() => {
        if (!ignore) {
          setFinancialDashboard(null);
          setFinancialDashboardLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [stockState.selected]);

  useEffect(() => {
    let ignore = false;

    fetchNewsLatestDate()
      .then((payload) => {
        if (!ignore) {
          setLatestNewsDate(payload.latest_date);
        }
      })
      .catch(() => {
        if (!ignore) {
          setLatestNewsDate(null);
        }
      });

    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    let ignore = false;

    fetchChartAnnotations({
      ticker: stockState.selected,
      startDate: startDate || undefined,
      endDate: endDate || undefined,
    })
      .then((items) => {
        if (!ignore) {
          setChartAnnotations(items);
        }
      })
      .catch(() => {
        if (!ignore) {
          setChartAnnotations([]);
        }
      });

    return () => {
      ignore = true;
    };
  }, [endDate, startDate, stockState.selected]);

  useEffect(() => {
    if (activeTab !== "watchlist" || stockView !== "dividends") return;

    let ignore = false;

    setStockDividendEventsLoading(true);
    setStockDividendEventsError("");
    fetchDividendEvents({
      ticker: stockState.selected,
      startDate: startDate || undefined,
      endDate: endDate || undefined,
      limit: 120,
    })
      .then((items) => {
        if (!ignore) {
          setStockDividendEvents(items);
          setStockDividendEventsLoading(false);
        }
      })
      .catch((err: Error) => {
        if (!ignore) {
          setStockDividendEvents([]);
          setStockDividendEventsError(err.message);
          setStockDividendEventsLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [activeTab, endDate, startDate, stockState.selected, stockView]);

  useEffect(() => {
    if (activeTab !== "market" || marketView !== "dividends") return;

    let ignore = false;

    setMarketDividendEventsLoading(true);
    setMarketDividendEventsError("");
    fetchDividendEvents({
      upcomingOnly: true,
      limit: 80,
    })
      .then((items) => {
        if (!ignore) {
          setMarketDividendEvents(items);
          setMarketDividendEventsLoading(false);
        }
      })
      .catch((err: Error) => {
        if (!ignore) {
          setMarketDividendEvents([]);
          setMarketDividendEventsError(err.message);
          setMarketDividendEventsLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [activeTab, marketView]);

  useEffect(() => {
    if (activeTab !== "market" || marketView !== "dividends") return;

    let ignore = false;

    setMarketNewsError("");
    fetchMarketNews({
      startDate: startDate || undefined,
      endDate: endDate || undefined,
      limit: 160,
    })
      .then((items) => {
        if (!ignore) {
          setMarketNews(items);
        }
      })
      .catch((err: Error) => {
        if (!ignore) {
          setMarketNews([]);
          setMarketNewsError(err.message);
        }
      });

    return () => {
      ignore = true;
    };
  }, [activeTab, endDate, marketView, startDate]);

  useEffect(() => {
    if (activeTab !== "market" || marketView !== "social") return;

    let ignore = false;

    fetchTrends(200)
      .then((payload) => {
        if (!ignore) {
          setTrends(payload);
        }
      })
      .catch(() => {
        if (!ignore) {
          setTrends(null);
        }
      });

    return () => {
      ignore = true;
    };
  }, [activeTab, marketView]);

  useEffect(() => {
    if (activeTab !== "market" || marketView !== "valuation") return;

    let ignore = false;
    const universe = stockOptions.length > 0 ? stockOptions : VN30_STOCKS;
    if (valuationRankings?.universe_size === universe.length && !valuationRankingsError) return;

    setValuationRankingsLoading(true);
    setValuationRankingsError("");
    fetchValuationRankings(universe, 30)
      .then((payload) => {
        if (!ignore) {
          setValuationRankings(payload);
          setValuationRankingsLoading(false);
        }
      })
      .catch((err: Error) => {
        if (!ignore) {
          setValuationRankings(null);
          setValuationRankingsError(err.message);
          setValuationRankingsLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [activeTab, marketView, stockOptions, valuationRankings, valuationRankingsError]);

  useEffect(() => {
    if (activeTab !== "market" || marketView !== "sector") {
      return;
    }
    if (sectorOverview) return;

    let ignore = false;

    setSectorOverviewLoading(true);
    setSectorOverviewError("");
    fetchSectorOverview(10)
      .then((payload) => {
        if (!ignore) {
          setSectorOverview(payload);
          setSectorOverviewLoading(false);
        }
      })
      .catch((err: Error) => {
        if (!ignore) {
          setSectorOverview(null);
          setSectorOverviewError(err.message);
          setSectorOverviewLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [activeTab, marketView, sectorOverview]);

  useEffect(() => {
    if (activeTab !== "market" || marketView !== "social") return;

    let ignore = false;

    setSocialLoading(true);
    setSocialError("");
    fetchSocialRankings(50)
      .then((payload) => {
        if (!ignore) {
          setSocial(payload);
          setSocialLoading(false);
        }
      })
      .catch((err: Error) => {
        if (!ignore) {
          setSocial(null);
          setSocialError(err.message);
          setSocialLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [activeTab, marketView]);

  useEffect(() => {
    if (activeTab === "market" && marketView !== "chart") return;

    let ignore = false;
    const selected = currentState.selected;

    setCurrentState((previous) => ({
      ...previous,
      loading: true,
      error: "",
    }));

    fetchCandles({
      ticker: selected,
      startDate: startDate || undefined,
      endDate: endDate || undefined,
      limit: startDate || endDate ? undefined : DEFAULT_LIMIT,
    })
      .then((items) => {
        if (!ignore) {
          setCurrentState((previous) => ({
            ...previous,
            candles: items,
            loading: false,
          }));
        }
      })
      .catch((err: Error) => {
        if (!ignore) {
          setCurrentState((previous) => ({
            ...previous,
            candles: [],
            loading: false,
            error: err.message,
          }));
        }
      });

    return () => {
      ignore = true;
    };
  }, [activeTab, currentState.selected, endDate, marketView, setCurrentState, startDate]);

  const summary = useMemo(() => {
    if (currentCandles.length === 0) {
      return {
        latestClose: "--",
        highestHigh: "--",
        lowestLow: "--",
        change: "--",
      };
    }

    const first = currentCandles[0];
    const last = currentCandles[currentCandles.length - 1];
    const highest = Math.max(...currentCandles.map((item) => item.high));
    const lowest = Math.min(...currentCandles.map((item) => item.low));
    const percentChange = first.open === 0 ? 0 : ((last.close - first.open) / first.open) * 100;

    return {
      latestClose: last.close.toLocaleString("vi-VN"),
      highestHigh: highest.toLocaleString("vi-VN"),
      lowestLow: lowest.toLocaleString("vi-VN"),
      change: `${percentChange >= 0 ? "+" : ""}${percentChange.toFixed(2)}%`,
    };
  }, [currentCandles]);

  const dataRange = useMemo(() => {
    if (currentCandles.length === 0) return "Chưa có dữ liệu";
    return `${currentCandles[0].date} đến ${currentCandles[currentCandles.length - 1].date}`;
  }, [currentCandles]);

  const chartEvents = useMemo(
    () =>
      chartAnnotations
        .filter((item) => item.type === "event")
        .sort((first, second) => second.date.localeCompare(first.date)),
    [chartAnnotations],
  );
  const indexTradingInfo = useMemo(
    () => getIndexTradingInfo(indexState.selected, indexState.candles),
    [indexState.candles, indexState.selected],
  );
  const chartNews = useMemo(
    () =>
      chartAnnotations
        .filter((item) => item.type === "news")
        .sort((first, second) => second.date.localeCompare(first.date)),
    [chartAnnotations],
  );

  function updateInput(value: string) {
    const nextValue = value.toUpperCase();
    setCurrentState((previous) => ({
      ...previous,
      input: nextValue,
      error: previous.error && (activeTab !== "watchlist" || stockOptions.includes(nextValue.trim())) ? "" : previous.error,
    }));
  }

  function selectSymbol(symbol: string) {
    const nextSymbol = symbol.trim().toUpperCase();
    if (!nextSymbol) return;

    if (activeTab === "watchlist" && !stockOptions.includes(nextSymbol)) {
      setStockState((previous) => ({
        ...previous,
        input: nextSymbol,
        error: "Chỉ hỗ trợ các mã cổ phiếu VN30 hiện tại.",
      }));
      return;
    }

    setCurrentState((previous) => ({
      ...previous,
      input: nextSymbol,
      selected: nextSymbol,
      error: "",
    }));
  }

  function openStockTicker(ticker: string) {
    const nextSymbol = ticker.trim().toUpperCase();
    if (!nextSymbol) return;

    setStockState((previous) => ({
      ...previous,
      input: nextSymbol,
      selected: nextSymbol,
      error: "",
    }));
    setStockView("chart");
    setActiveTab("watchlist");
  }

  function openStockValuation(ticker: string) {
    const nextSymbol = ticker.trim().toUpperCase();
    if (!nextSymbol) return;

    setStockState((previous) => ({
      ...previous,
      input: nextSymbol,
      selected: nextSymbol,
      error: "",
    }));
    setStockView("valuation");
    setActiveTab("watchlist");
  }

  function openStockDividends(ticker: string) {
    const nextSymbol = ticker.trim().toUpperCase();
    if (!nextSymbol) return;

    setStockState((previous) => ({
      ...previous,
      input: nextSymbol,
      selected: nextSymbol,
      error: "",
    }));
    setStockView("dividends");
    setActiveTab("watchlist");
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    selectSymbol(currentState.input);
  }

  return (
    <div className="page-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <h1>Bảng giá</h1>
        </div>

        <div className="tab-list">
          <button
            type="button"
            className={activeTab === "watchlist" ? "tab-button active" : "tab-button"}
            onClick={() => setActiveTab("watchlist")}
          >
            <span>01</span>
            Theo dõi mã cổ phiếu
          </button>
          <button
            type="button"
            className={activeTab === "market" ? "tab-button active" : "tab-button"}
            onClick={() => setActiveTab("market")}
          >
            <span>02</span>
            Chỉ số thị trường
          </button>
        </div>

        <div className="stats-grid">
          <div className="stat-card">
            <span>Giá đóng cửa gần nhất</span>
            <strong>{summary.latestClose}</strong>
          </div>
          <div className="stat-card">
            <span>Biến động trong khung</span>
            <strong>{summary.change}</strong>
          </div>
          <div className="stat-card">
            <span>Đỉnh trong khung dữ liệu</span>
            <strong>{summary.highestHigh}</strong>
          </div>
          <div className="stat-card">
            <span>Đáy trong khung dữ liệu</span>
            <strong>{summary.lowestLow}</strong>
          </div>
        </div>
      </aside>

      <main className="main-panel">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2>{tabTitle}</h2>
              <p className="panel-subtitle">
                {activeSymbolLabel}: <strong>{currentState.selected}</strong> · Khoảng dữ liệu: {dataRange}
              </p>
            </div>
          </div>

          {activeTab !== "market" || marketView === "chart" ? (
          <form className="toolbar" onSubmit={handleSubmit}>
            <div className="field">
              <label htmlFor={symbolInputId}>{inputLabel}</label>
              <input
                id={symbolInputId}
                name={symbolInputId}
                list={symbolListId}
                autoComplete="off"
                value={currentState.input}
                onChange={(event) => updateInput(event.target.value)}
                placeholder={inputPlaceholder}
              />
              <datalist id="vn30-stock-list">
                {stockOptions.map((item) => (
                  <option key={item} value={item} />
                ))}
              </datalist>
              <datalist id="market-index-list">
                {indexOptions.map((item) => (
                  <option key={item} value={item} />
                ))}
              </datalist>
            </div>

            <div className="field">
              <label htmlFor="start-date">Từ ngày</label>
              <input
                id="start-date"
                type="date"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
              />
            </div>

            <div className="field">
              <label htmlFor="end-date">Đến ngày</label>
              <input
                id="end-date"
                type="date"
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
              />
            </div>

            <button className="primary-button" type="submit">
              {submitLabel}
            </button>
          </form>
          ) : null}

          {activeTab === "watchlist" ? (
            <>
              <div className="stock-instruction">
                Chỉ tìm kiếm trong danh sách cổ phiếu VN30 hiện tại.
              </div>

              <div className="stock-view-tabs" aria-label="Nội dung cổ phiếu">
                <button
                  type="button"
                  className={stockView === "chart" ? "stock-view-tab active" : "stock-view-tab"}
                  onClick={() => setStockView("chart")}
                >
                  Biến động giá
                </button>
                <button
                  type="button"
                  className={stockView === "info" ? "stock-view-tab active" : "stock-view-tab"}
                  onClick={() => setStockView("info")}
                >
                  Thông tin chung
                </button>
                <button
                  type="button"
                  className={stockView === "holders" ? "stock-view-tab active" : "stock-view-tab"}
                  onClick={() => setStockView("holders")}
                >
                  Cổ đông và lãnh đạo
                </button>
                <button
                  type="button"
                  className={stockView === "valuation" ? "stock-view-tab active" : "stock-view-tab"}
                  onClick={() => setStockView("valuation")}
                >
                  Định giá
                </button>
                <button
                  type="button"
                  className={stockView === "financials" ? "stock-view-tab active" : "stock-view-tab"}
                  onClick={() => setStockView("financials")}
                >
                  BCTC
                </button>
                <button
                  type="button"
                  className={stockView === "dividends" ? "stock-view-tab active" : "stock-view-tab"}
                  onClick={() => setStockView("dividends")}
                >
                  Tin tức và sự kiện
                </button>
                <button
                  type="button"
                  className={stockView === "analysis" ? "stock-view-tab active" : "stock-view-tab"}
                  onClick={() => setStockView("analysis")}
                >
                  Phân tích AI
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="stock-view-tabs" aria-label="Nội dung thị trường chung">
                <button
                  type="button"
                  className={marketView === "chart" ? "stock-view-tab active" : "stock-view-tab"}
                  onClick={() => setMarketView("chart")}
                >
                  Biến động
                </button>
                <button
                  type="button"
                  className={marketView === "sector" ? "stock-view-tab active" : "stock-view-tab"}
                  onClick={() => setMarketView("sector")}
                >
                  Ngành
                </button>
                <button
                  type="button"
                  className={marketView === "social" ? "stock-view-tab active" : "stock-view-tab"}
                  onClick={() => setMarketView("social")}
                >
                  Social
                </button>
                <button
                  type="button"
                  className={marketView === "valuation" ? "stock-view-tab active" : "stock-view-tab"}
                  onClick={() => setMarketView("valuation")}
                >
                  Định giá
                </button>
                <button
                  type="button"
                  className={marketView === "dividends" ? "stock-view-tab active" : "stock-view-tab"}
                  onClick={() => setMarketView("dividends")}
                >
                  Tin tức và sự kiện
                </button>
              </div>

              {marketView === "chart" ? (
                <div className="quick-list" aria-label="Chỉ số thị trường">
              {indexOptions.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={currentState.selected === item ? "quick-chip active" : "quick-chip"}
                  onClick={() => selectSymbol(item)}
                >
                  {item}
                </button>
              ))}
                </div>
              ) : null}
            </>
          )}

          {(activeTab !== "market" || marketView === "chart") && currentState.error ? (
            <div className="message error">{currentState.error}</div>
          ) : null}
          {(activeTab !== "market" || marketView === "chart") && currentState.loading ? (
            <div className="message">Đang tải dữ liệu...</div>
          ) : null}

          <div className="chart-panel">
            {activeTab === "watchlist" && stockView === "info" ? (
              <StockInfoPanel
                info={stockInfo}
                ticker={currentState.selected}
                loading={currentState.loading || stockInfoLoading}
              />
            ) : activeTab === "watchlist" && stockView === "holders" ? (
              <ShareholdersOfficersPanel
                info={stockInfo}
                ticker={currentState.selected}
                loading={currentState.loading || stockInfoLoading}
              />
            ) : activeTab === "watchlist" && stockView === "valuation" ? (
              <StockValuationPanel
                info={stockInfo}
                ticker={currentState.selected}
                loading={currentState.loading || stockInfoLoading}
              />
            ) : activeTab === "watchlist" && stockView === "financials" ? (
              <FinancialDashboardPanel
                dashboard={financialDashboard}
                ticker={currentState.selected}
                loading={financialDashboardLoading}
              />
            ) : activeTab === "watchlist" && stockView === "dividends" ? (
              <NewsEventsPanel
                dividendEvents={stockDividendEvents}
                dividendError={stockDividendEventsError}
                dividendLoading={stockDividendEventsLoading}
                latestNewsDate={latestNewsDate}
                news={chartNews}
                ticker={currentState.selected}
              />
            ) : activeTab === "watchlist" && stockView === "analysis" ? (
              <AnalysisReportsPanel
                reports={analysisReports}
                ticker={currentState.selected}
                loading={analysisReportsLoading}
                error={analysisReportsError}
                onRefresh={refreshAnalysisReports}
              />
            ) : activeTab === "market" && marketView === "social" ? (
              <SocialPanel
                social={social}
                trends={trends}
                loading={socialLoading}
                error={socialError}
                onTickerSelect={openStockTicker}
              />
            ) : activeTab === "market" && marketView === "sector" ? (
              <SectorPanel
                overview={sectorOverview}
                loading={sectorOverviewLoading}
                error={sectorOverviewError}
                onTickerSelect={openStockTicker}
              />
            ) : activeTab === "market" && marketView === "valuation" ? (
              <ValuationMarketPanel
                rankings={valuationRankings}
                loading={valuationRankingsLoading}
                error={valuationRankingsError}
                onTickerSelect={openStockValuation}
              />
            ) : activeTab === "market" && marketView === "dividends" ? (
              <NewsEventsPanel
                dividendEvents={marketDividendEvents}
                dividendError={marketDividendEventsError}
                dividendLoading={marketDividendEventsLoading}
                dividendTitle="Cổ tức thị trường"
                dividendSubtitle={
                  marketDividendEvents.length > 0
                    ? `${marketDividendEvents.length.toLocaleString("vi-VN")} sự kiện trong lịch sắp tới`
                    : "Theo dõi sự kiện cổ tức sắp tới trên thị trường"
                }
                dividendEmptyTitle="Chưa có sự kiện cổ tức sắp tới"
                dividendEmptyMessage="Danh sách sẽ xuất hiện khi warehouse_events có sự kiện từ hôm nay trở đi."
                latestNewsDate={latestNewsDate}
                news={marketNews}
                newsTitle="Tin tức chỉ số thị trường"
                newsEmptyTitle="Chưa có tin tức chỉ số thị trường"
                newsEmptyMessage={
                  marketNewsError ||
                  "Tin tức sẽ xuất hiện khi warehouse_news có ticker hoặc tag là VN30, VN100, VNINDEX."
                }
                ticker="VNINDEX"
                showDividendTicker
                onDividendTickerSelect={openStockDividends}
              />
            ) : (
              <PriceMovementPanel
                key={`${activeTab}-${currentState.selected}-${dataRange}`}
                annotations={activeTab === "watchlist" ? chartEvents : []}
                candles={currentCandles}
                info={activeTab === "watchlist" ? stockInfo : indexTradingInfo}
                ticker={currentState.selected}
                loading={currentState.loading}
                showTradingSummary={activeTab === "watchlist" ? stockView === "chart" : marketView === "chart"}
              />
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
