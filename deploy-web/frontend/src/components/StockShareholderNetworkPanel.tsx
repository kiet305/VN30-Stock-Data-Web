import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D, {
  type ForceGraph3DInstance,
  type LinkObject,
  type NodeObject,
} from "3d-force-graph";

import { fetchCandles } from "../api";
import type { Candle, SectorOverviewResponse } from "../types";

type RawShareholder = {
  name: string;
  ownership_percentage: number;
};

type RawCompanyShareholders = {
  ticker: string;
  shareholders: RawShareholder[];
};

type HolderPosition = {
  label: string;
  ownership: number;
};

type SectorMeta = {
  industry: string;
  subindustry: string | null;
  color: string;
};

type StockNode = NodeObject & {
  id: string;
  ticker: string;
  label: string;
  industry: string;
  subindustry: string | null;
  color: string;
  relationCount: number;
  sharedHolderCount: number;
  isMain: boolean;
  val: number;
};

type StockLink = LinkObject<StockNode> & {
  source: string | StockNode;
  target: string | StockNode;
  color: string;
  sharedHolderCount: number;
  sharedOwnershipScore: number;
  holders: string[];
  label: string;
};

type RelatedTicker = {
  ticker: string;
  industry: string;
  subindustry: string | null;
  color: string;
  sharedHolderCount: number;
  sharedOwnershipScore: number;
  holders: string[];
};

type CorrelationRow = RelatedTicker & {
  correlation: number | null;
  observations: number;
  tone: string;
  assessment: string;
};

type Props = {
  selectedTicker: string;
  startDate?: string;
  endDate?: string;
  sectorOverview?: SectorOverviewResponse | null;
  onTickerSelect?: (ticker: string) => void;
};

const DATA_URL = "/assets/vn30_shareholders.json";
const UNKNOWN_SECTOR = "Chưa phân ngành";
const DEFAULT_COMPANY_COLOR = "#8a96a3";
const MAIN_TICKER_COLOR = "#101820";
const SECTOR_COLORS = [
  "#2f80ed",
  "#0f9f6e",
  "#d94b4b",
  "#9b6bcc",
  "#d68b00",
  "#00a6a6",
  "#e4578f",
  "#64748b",
  "#7c9b2e",
  "#b6674f",
  "#4f7db8",
  "#c0803d",
];
const MOJIBAKE_PATTERN = /[ÃÄÂÆ]|á[º»]/;

function repairMojibake(value: string) {
  if (!MOJIBAKE_PATTERN.test(value)) return value;

  try {
    const bytes = Uint8Array.from(value, (char) => char.charCodeAt(0));
    const decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    return decoded.includes("�") ? value : decoded;
  } catch {
    return value;
  }
}

function normalizeHolderName(name: string) {
  return name.normalize("NFKC").replace(/\s+/g, " ").trim().toLocaleLowerCase("vi-VN");
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatPercent(value: number) {
  return `${value.toLocaleString("vi-VN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: value % 1 === 0 ? 0 : 1,
  })}%`;
}

function formatCorrelation(value: number | null) {
  return value === null ? "--" : value.toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function buildSectorMetadata(sectorOverview: SectorOverviewResponse | null | undefined) {
  const sectorByTicker = new Map<string, SectorMeta>();
  const sectorColorByIndustry = new Map<string, string>();

  (sectorOverview?.items ?? []).forEach((sector, index) => {
    const industry = repairMojibake(sector.industry).trim();
    if (!industry) return;

    const color = SECTOR_COLORS[index % SECTOR_COLORS.length];
    sectorColorByIndustry.set(industry, color);

    sector.top_constituents.forEach((constituent) => {
      sectorByTicker.set(constituent.ticker.toUpperCase(), {
        industry,
        subindustry: constituent.subindustry ? repairMojibake(constituent.subindustry) : null,
        color,
      });
    });
  });

  return { sectorByTicker, sectorColorByIndustry };
}

function collectCompanyHolders(rawData: RawCompanyShareholders[]) {
  const holdersByTicker = new Map<string, Map<string, HolderPosition>>();

  rawData.forEach((company) => {
    const ticker = company.ticker.trim().toUpperCase();
    const holderMap = new Map<string, HolderPosition>();

    company.shareholders.forEach((shareholder) => {
      const label = repairMojibake(shareholder.name).replace(/\s+/g, " ").trim();
      const ownership = Number(shareholder.ownership_percentage);
      if (!label || !Number.isFinite(ownership) || ownership <= 0) return;

      const key = normalizeHolderName(label);
      const existing = holderMap.get(key);
      holderMap.set(key, {
        label: existing?.label ?? label,
        ownership: (existing?.ownership ?? 0) + ownership,
      });
    });

    holdersByTicker.set(ticker, holderMap);
  });

  return holdersByTicker;
}

function getSharedHolders(first: Map<string, HolderPosition>, second: Map<string, HolderPosition>) {
  const holders: Array<{ key: string; label: string; ownershipScore: number }> = [];

  first.forEach((firstPosition, holderKey) => {
    const secondPosition = second.get(holderKey);
    if (!secondPosition) return;

    holders.push({
      key: holderKey,
      label: firstPosition.label,
      ownershipScore: Math.min(firstPosition.ownership, secondPosition.ownership),
    });
  });

  holders.sort((firstHolder, secondHolder) => secondHolder.ownershipScore - firstHolder.ownershipScore);
  return holders;
}

function buildStockNetwork(
  rawData: RawCompanyShareholders[],
  selectedTicker: string,
  sectorByTicker: Map<string, SectorMeta>,
) {
  const mainTicker = selectedTicker.toUpperCase();
  const holdersByTicker = collectCompanyHolders(rawData);
  const mainHolders = holdersByTicker.get(mainTicker);
  const relatedTickers: RelatedTicker[] = [];

  if (!mainHolders) {
    return { nodes: [], links: [], relatedTickers, sectorLegend: [] };
  }

  holdersByTicker.forEach((holderMap, ticker) => {
    if (ticker === mainTicker) return;

    const shared = getSharedHolders(mainHolders, holderMap);
    if (shared.length === 0) return;

    const sector = sectorByTicker.get(ticker);
    relatedTickers.push({
      ticker,
      industry: sector?.industry ?? UNKNOWN_SECTOR,
      subindustry: sector?.subindustry ?? null,
      color: sector?.color ?? DEFAULT_COMPANY_COLOR,
      sharedHolderCount: shared.length,
      sharedOwnershipScore: shared.reduce((total, holder) => total + holder.ownershipScore, 0),
      holders: shared.map((holder) => holder.label),
    });
  });

  relatedTickers.sort((first, second) => {
    if (second.sharedHolderCount !== first.sharedHolderCount) return second.sharedHolderCount - first.sharedHolderCount;
    return second.sharedOwnershipScore - first.sharedOwnershipScore;
  });

  const visibleTickers = new Set([mainTicker, ...relatedTickers.map((item) => item.ticker)]);
  const nodes: StockNode[] = [...visibleTickers].map((ticker) => {
    const sector = sectorByTicker.get(ticker);
    const related = relatedTickers.find((item) => item.ticker === ticker);
    const isMain = ticker === mainTicker;
    const relationCount = isMain ? relatedTickers.length : 1;
    const sharedHolderCount = isMain
      ? relatedTickers.reduce((total, item) => total + item.sharedHolderCount, 0)
      : related?.sharedHolderCount ?? 0;

    return {
      id: ticker,
      ticker,
      label: ticker,
      industry: sector?.industry ?? UNKNOWN_SECTOR,
      subindustry: sector?.subindustry ?? null,
      color: isMain ? MAIN_TICKER_COLOR : sector?.color ?? DEFAULT_COMPANY_COLOR,
      relationCount,
      sharedHolderCount,
      isMain,
      val: isMain ? 18 : 8 + Math.sqrt(sharedHolderCount) * 2.4,
    };
  });

  const links: StockLink[] = [];
  const tickers = [...visibleTickers];
  for (let firstIndex = 0; firstIndex < tickers.length; firstIndex += 1) {
    for (let secondIndex = firstIndex + 1; secondIndex < tickers.length; secondIndex += 1) {
      const firstTicker = tickers[firstIndex];
      const secondTicker = tickers[secondIndex];
      const firstHolders = holdersByTicker.get(firstTicker);
      const secondHolders = holdersByTicker.get(secondTicker);
      if (!firstHolders || !secondHolders) continue;

      const shared = getSharedHolders(firstHolders, secondHolders);
      if (shared.length === 0) continue;

      const sharedOwnershipScore = shared.reduce((total, holder) => total + holder.ownershipScore, 0);
      const targetSector = sectorByTicker.get(secondTicker) ?? sectorByTicker.get(firstTicker);
      links.push({
        source: firstTicker,
        target: secondTicker,
        color: targetSector?.color ?? DEFAULT_COMPANY_COLOR,
        sharedHolderCount: shared.length,
        sharedOwnershipScore,
        holders: shared.map((holder) => holder.label),
        label: `${firstTicker} - ${secondTicker}: ${shared.length} cổ đông chung`,
      });
    }
  }

  const usedIndustries = new Set(nodes.map((node) => node.industry));
  const sectorLegend = [...sectorByTicker.values()]
    .filter((item, index, values) => usedIndustries.has(item.industry) && values.findIndex((other) => other.industry === item.industry) === index)
    .map((item) => ({ industry: item.industry, color: item.color }));
  if (usedIndustries.has(UNKNOWN_SECTOR)) {
    sectorLegend.push({ industry: UNKNOWN_SECTOR, color: DEFAULT_COMPANY_COLOR });
  }

  return { nodes, links, relatedTickers, sectorLegend };
}

function returnsByDate(candles: Candle[]) {
  const sorted = [...candles].sort((first, second) => first.date.localeCompare(second.date));
  const returns = new Map<string, number>();

  for (let index = 1; index < sorted.length; index += 1) {
    const previous = sorted[index - 1];
    const current = sorted[index];
    if (!previous.close || previous.close <= 0) continue;
    returns.set(current.date, current.close / previous.close - 1);
  }

  return returns;
}

function pearsonCorrelation(firstReturns: Map<string, number>, secondReturns: Map<string, number>) {
  const pairs: Array<[number, number]> = [];
  firstReturns.forEach((firstValue, date) => {
    const secondValue = secondReturns.get(date);
    if (secondValue === undefined) return;
    pairs.push([firstValue, secondValue]);
  });

  if (pairs.length < 8) return { correlation: null, observations: pairs.length };

  const firstMean = pairs.reduce((total, pair) => total + pair[0], 0) / pairs.length;
  const secondMean = pairs.reduce((total, pair) => total + pair[1], 0) / pairs.length;
  let numerator = 0;
  let firstVariance = 0;
  let secondVariance = 0;

  pairs.forEach(([firstValue, secondValue]) => {
    const firstDelta = firstValue - firstMean;
    const secondDelta = secondValue - secondMean;
    numerator += firstDelta * secondDelta;
    firstVariance += firstDelta * firstDelta;
    secondVariance += secondDelta * secondDelta;
  });

  const denominator = Math.sqrt(firstVariance * secondVariance);
  return {
    correlation: denominator === 0 ? null : numerator / denominator,
    observations: pairs.length,
  };
}

function assessCorrelation(value: number | null) {
  if (value === null) return { assessment: "Thiếu dữ liệu", tone: "neutral" };
  if (value >= 0.75) return { assessment: "Rất cao", tone: "strong" };
  if (value >= 0.5) return { assessment: "Cao", tone: "good" };
  if (value >= 0.25) return { assessment: "Trung bình", tone: "moderate" };
  if (value >= -0.25) return { assessment: "Thấp", tone: "low" };
  return { assessment: "Ngược chiều", tone: "inverse" };
}

function getNodeLabel(node: StockNode) {
  const sector = node.subindustry ? `${node.industry} · ${node.subindustry}` : node.industry;
  const details = node.isMain
    ? `Mã chính · ${node.relationCount} mã liên quan`
    : `${sector} · ${node.sharedHolderCount} cổ đông chung với mã chính`;
  return `<strong>${escapeHtml(node.ticker)}</strong><br/><span>${escapeHtml(details)}</span>`;
}

function getNodeCameraPosition(node: StockNode) {
  const x = node.x ?? 0;
  const y = node.y ?? 0;
  const z = node.z ?? 0;
  const distance = 88;
  const currentDistance = Math.hypot(x, y, z) || 1;
  const ratio = 1 + distance / currentDistance;

  return {
    position: { x: x * ratio, y: y * ratio, z: z * ratio },
    lookAt: { x, y, z },
  };
}

function getLinkEndpointTicker(endpoint: string | StockNode) {
  return typeof endpoint === "string" ? endpoint : endpoint.ticker;
}

export function StockShareholderNetworkPanel({
  selectedTicker,
  startDate,
  endDate,
  sectorOverview = null,
  onTickerSelect,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<ForceGraph3DInstance<StockNode, StockLink> | null>(null);
  const [rawData, setRawData] = useState<RawCompanyShareholders[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [correlations, setCorrelations] = useState<CorrelationRow[]>([]);
  const [correlationLoading, setCorrelationLoading] = useState(false);
  const [correlationError, setCorrelationError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");

    fetch(DATA_URL, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("Không tải được dữ liệu cổ đông");
        return response.json() as Promise<RawCompanyShareholders[]>;
      })
      .then((payload) => {
        setRawData(payload);
        setLoading(false);
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        setRawData([]);
        setError(err.message);
        setLoading(false);
      });

    return () => controller.abort();
  }, []);

  const sectorMetadata = useMemo(() => buildSectorMetadata(sectorOverview), [sectorOverview]);
  const network = useMemo(
    () => buildStockNetwork(rawData, selectedTicker, sectorMetadata.sectorByTicker),
    [rawData, sectorMetadata.sectorByTicker, selectedTicker],
  );

  useEffect(() => {
    if (!containerRef.current || graphRef.current) return;

    const graph = new ForceGraph3D(containerRef.current, {
      rendererConfig: { antialias: true, alpha: true },
    }) as unknown as ForceGraph3DInstance<StockNode, StockLink>;

    graph
      .backgroundColor("rgba(0,0,0,0)")
      .nodeLabel(getNodeLabel)
      .nodeColor((node) => node.color)
      .nodeVal((node) => node.val)
      .linkLabel((link) => `${escapeHtml(link.label)}<br/>${escapeHtml(link.holders.slice(0, 5).join(", "))}`)
      .linkColor((link) => link.color)
      .linkOpacity(0.48)
      .linkWidth((link) => Math.max(0.8, Math.min(5, link.sharedHolderCount * 0.85)))
      .linkDirectionalParticles((link) => {
        const mainTicker = selectedTicker.toUpperCase();
        return getLinkEndpointTicker(link.source) === mainTicker || getLinkEndpointTicker(link.target) === mainTicker ? 1 : 0;
      })
      .linkDirectionalParticleWidth(1.6)
      .cooldownTicks(100)
      .showNavInfo(false)
      .onNodeClick((node) => {
        const { position, lookAt } = getNodeCameraPosition(node);
        graph.cameraPosition(position, lookAt, 650);
        if (!node.isMain) onTickerSelect?.(node.ticker);
      });

    graph.d3Force("charge")?.strength?.(-95);
    graphRef.current = graph;

    return () => {
      graph._destructor();
      graphRef.current = null;
    };
  }, [onTickerSelect, selectedTicker]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;

    graph.graphData({ nodes: network.nodes, links: network.links });
    window.setTimeout(() => graph.zoomToFit(650, 72), 220);
  }, [network]);

  useEffect(() => {
    const graph = graphRef.current;
    const container = containerRef.current;
    if (!graph || !container) return;

    const resize = () => {
      const rect = container.getBoundingClientRect();
      graph.width(Math.max(320, Math.floor(rect.width)));
      graph.height(Math.max(460, Math.floor(rect.height)));
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);

    return () => observer.disconnect();
  }, [loading]);

  useEffect(() => {
    if (network.relatedTickers.length === 0) {
      setCorrelations([]);
      setCorrelationLoading(false);
      setCorrelationError("");
      return;
    }

    let ignore = false;
    const related = network.relatedTickers;

    setCorrelationLoading(true);
    setCorrelationError("");

    Promise.allSettled([
      fetchCandles({ ticker: selectedTicker, startDate: startDate || undefined, endDate: endDate || undefined }),
      ...related.map((item) =>
        fetchCandles({ ticker: item.ticker, startDate: startDate || undefined, endDate: endDate || undefined }),
      ),
    ]).then((results) => {
      if (ignore) return;

      const mainResult = results[0];
      if (mainResult.status !== "fulfilled") {
        setCorrelations([]);
        setCorrelationError("Không tải được dữ liệu giá của mã chính");
        setCorrelationLoading(false);
        return;
      }

      const mainReturns = returnsByDate(mainResult.value);
      const rows = related.map((item, index) => {
        const result = results[index + 1];
        if (result.status !== "fulfilled") {
          const assessed = assessCorrelation(null);
          return { ...item, correlation: null, observations: 0, ...assessed };
        }

        const comparison = pearsonCorrelation(mainReturns, returnsByDate(result.value));
        const assessed = assessCorrelation(comparison.correlation);
        return { ...item, ...comparison, ...assessed };
      });

      rows.sort((first, second) => {
        const firstCorrelation = first.correlation ?? -2;
        const secondCorrelation = second.correlation ?? -2;
        return secondCorrelation - firstCorrelation;
      });

      setCorrelations(rows);
      setCorrelationLoading(false);
    });

    return () => {
      ignore = true;
    };
  }, [endDate, network.relatedTickers, selectedTicker, startDate]);

  return (
    <section className="stock-network-panel">
      <div className="stock-network-header">
        <div>
          <strong>Quan hệ cổ đông chung của {selectedTicker}</strong>
          <span>
            {network.relatedTickers.length} mã liên quan · {network.links.length} quan hệ cổ đông chung
          </span>
        </div>
        <span className="stock-network-source">VN30 shareholders</span>
      </div>

      <div className="stock-network-legend" aria-label="Chú giải ngành">
        <span>
          <i style={{ background: MAIN_TICKER_COLOR }} /> Mã chính
        </span>
        {network.sectorLegend.map((sector) => (
          <span key={sector.industry}>
            <i style={{ background: sector.color }} /> {sector.industry}
          </span>
        ))}
      </div>

      <div className="stock-network-stage">
        {loading ? <div className="stock-network-empty">Đang tải dữ liệu cổ đông...</div> : null}
        {error ? <div className="stock-network-empty error">{error}</div> : null}
        {!loading && !error && network.relatedTickers.length === 0 ? (
          <div className="stock-network-empty">Không có mã VN30 nào có cổ đông chung với {selectedTicker}.</div>
        ) : null}
        <div ref={containerRef} className="stock-network-graph" />
      </div>

      <div className="stock-network-table-wrap">
        <div className="stock-network-table-title">
          <strong>Correlation giá với {selectedTicker}</strong>
          <span>{correlationLoading ? "Đang tính..." : `${correlations.length} mã so sánh`}</span>
        </div>
        {correlationError ? <div className="stock-network-table-empty">{correlationError}</div> : null}
        {!correlationError && correlations.length === 0 ? (
          <div className="stock-network-table-empty">Chưa có mã liên quan để tính correlation.</div>
        ) : null}
        {correlations.length > 0 ? (
          <div className="stock-network-table">
            <div className="stock-network-row head">
              <span>Mã</span>
              <span>Ngành</span>
              <span>Cổ đông chung</span>
              <span>Correlation</span>
              <span>Đánh giá</span>
              <span>Phiên khớp</span>
            </div>
            {correlations.map((row) => (
              <button
                type="button"
                key={row.ticker}
                className="stock-network-row"
                onClick={() => onTickerSelect?.(row.ticker)}
              >
                <span className="stock-network-ticker">
                  <i style={{ background: row.color }} />
                  <strong>{row.ticker}</strong>
                </span>
                <span>{row.industry}</span>
                <span title={row.holders.join(", ")}>{row.sharedHolderCount}</span>
                <span>{formatCorrelation(row.correlation)}</span>
                <span className={`stock-network-assessment ${row.tone}`}>{row.assessment}</span>
                <span>{row.observations}</span>
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
