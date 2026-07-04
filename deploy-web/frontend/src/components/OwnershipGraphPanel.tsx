import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D, {
  type ForceGraph3DInstance,
  type LinkObject,
  type NodeObject,
} from "3d-force-graph";
import type { SectorOverviewResponse } from "../types";

type RawShareholder = {
  name: string;
  ownership_percentage: number;
};

type RawCompanyShareholders = {
  ticker: string;
  shareholders: RawShareholder[];
};

type HolderStats = {
  id: string;
  key: string;
  label: string;
  companies: Set<string>;
  totalOwnership: number;
  maxOwnership: number;
};

type AggregatedLink = {
  ticker: string;
  holderKey: string;
  ownership: number;
};

type OwnershipNode = NodeObject & {
  id: string;
  label: string;
  type: "company" | "shareholder";
  ticker?: string;
  industry?: string;
  subindustry?: string | null;
  connectionCount: number;
  totalOwnership: number;
  color: string;
  val: number;
};

type OwnershipLink = LinkObject<OwnershipNode> & {
  source: string | OwnershipNode;
  target: string | OwnershipNode;
  ownership: number;
  color: string;
  label: string;
};

const DATA_URL = "/assets/vn30_shareholders.json";
const DEFAULT_COMPANY_COLOR = "#8a96a3";
const HOLDER_COLOR = "#c2cad4";
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

type Props = {
  sectorOverview?: SectorOverviewResponse | null;
};

type SectorMeta = {
  industry: string;
  subindustry: string | null;
  color: string;
};

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

function formatPercent(value: number) {
  return `${value.toLocaleString("vi-VN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: value % 1 === 0 ? 0 : 1,
  })}%`;
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function collectShareholderData(rawData: RawCompanyShareholders[]) {
  const holders = new Map<string, HolderStats>();
  const links: AggregatedLink[] = [];

  rawData.forEach((company) => {
    const ticker = company.ticker.trim().toUpperCase();
    const companyHolders = new Map<string, { label: string; ownership: number }>();

    company.shareholders.forEach((shareholder) => {
      const label = repairMojibake(shareholder.name).replace(/\s+/g, " ").trim();
      const ownership = Number(shareholder.ownership_percentage);
      if (!label || !Number.isFinite(ownership) || ownership <= 0) return;

      const key = normalizeHolderName(label);
      const existing = companyHolders.get(key);
      companyHolders.set(key, {
        label: existing?.label ?? label,
        ownership: (existing?.ownership ?? 0) + ownership,
      });
    });

    companyHolders.forEach((holder, key) => {
      const stats =
        holders.get(key) ??
        ({
          id: `shareholder:${key}`,
          key,
          label: holder.label,
          companies: new Set<string>(),
          totalOwnership: 0,
          maxOwnership: 0,
        } satisfies HolderStats);

      stats.companies.add(ticker);
      stats.totalOwnership += holder.ownership;
      stats.maxOwnership = Math.max(stats.maxOwnership, holder.ownership);
      holders.set(key, stats);

      links.push({
        ticker,
        holderKey: key,
        ownership: holder.ownership,
      });
    });
  });

  return { holders, links };
}

function buildSectorMetadata(sectorOverview: SectorOverviewResponse | null | undefined) {
  const sectorColorByIndustry = new Map<string, string>();
  const sectorByTicker = new Map<string, SectorMeta>();

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

function buildGraph(
  rawData: RawCompanyShareholders[],
  minOwnership: number,
  onlyShared: boolean,
  focusTicker: string,
  sectorByTicker: Map<string, SectorMeta>,
) {
  const { holders, links } = collectShareholderData(rawData);
  const normalizedFocusTicker = focusTicker === "ALL" ? "" : focusTicker.toUpperCase();
  const qualifyingLinks = links.filter((link) => {
    const holder = holders.get(link.holderKey);
    if (!holder) return false;
    if (link.ownership < minOwnership) return false;
    return !onlyShared || holder.companies.size > 1;
  });

  const focusHolderKeys = normalizedFocusTicker
    ? new Set(qualifyingLinks.filter((link) => link.ticker === normalizedFocusTicker).map((link) => link.holderKey))
    : null;

  const visibleLinks = focusHolderKeys
    ? qualifyingLinks.filter((link) => link.ticker === normalizedFocusTicker || focusHolderKeys.has(link.holderKey))
    : qualifyingLinks;

  const companyDegrees = new Map<string, number>();
  const holderDegrees = new Map<string, number>();

  visibleLinks.forEach((link) => {
    companyDegrees.set(link.ticker, (companyDegrees.get(link.ticker) ?? 0) + 1);
    holderDegrees.set(link.holderKey, (holderDegrees.get(link.holderKey) ?? 0) + 1);
  });

  const nodes: OwnershipNode[] = [];
  companyDegrees.forEach((degree, ticker) => {
    const sector = sectorByTicker.get(ticker);
    nodes.push({
      id: `company:${ticker}`,
      label: ticker,
      type: "company",
      ticker,
      industry: sector?.industry ?? "Chưa phân ngành",
      subindustry: sector?.subindustry ?? null,
      connectionCount: degree,
      totalOwnership: visibleLinks
        .filter((link) => link.ticker === ticker)
        .reduce((total, link) => total + link.ownership, 0),
      color: sector?.color ?? DEFAULT_COMPANY_COLOR,
      val: 8 + Math.sqrt(degree) * 2.2,
    });
  });

  holderDegrees.forEach((degree, holderKey) => {
    const holder = holders.get(holderKey);
    if (!holder) return;

    nodes.push({
      id: holder.id,
      label: holder.label,
      type: "shareholder",
      connectionCount: degree,
      totalOwnership: holder.totalOwnership,
      color: HOLDER_COLOR,
      val: 2.8 + Math.sqrt(Math.max(holder.maxOwnership, 0.5)) * 1.4 + Math.min(degree, 8) * 0.45,
    });
  });

  const graphLinks: OwnershipLink[] = visibleLinks.map((link) => {
    const holder = holders.get(link.holderKey);
    const holderLabel = holder?.label ?? link.holderKey;
    return {
      source: `shareholder:${link.holderKey}`,
      target: `company:${link.ticker}`,
      ownership: link.ownership,
      color: sectorByTicker.get(link.ticker)?.color ?? DEFAULT_COMPANY_COLOR,
      label: `${holderLabel} -> ${link.ticker}: ${formatPercent(link.ownership)}`,
    };
  });

  return {
    nodes,
    links: graphLinks,
    summary: {
      companyCount: companyDegrees.size,
      shareholderCount: holderDegrees.size,
      linkCount: visibleLinks.length,
      sectorCount: new Set(
        [...companyDegrees.keys()].map((ticker) => sectorByTicker.get(ticker)?.industry ?? "Chưa phân ngành"),
      ).size,
      sharedShareholderCount: [...holderDegrees.keys()].filter((holderKey) => (holders.get(holderKey)?.companies.size ?? 0) > 1)
        .length,
    },
  };
}

function getNodeLabel(node: OwnershipNode) {
  const title = escapeHtml(node.label);
  const details =
    node.type === "company"
      ? `${node.connectionCount} cổ đông · ${formatPercent(node.totalOwnership)} tổng tỷ lệ trong graph`
      : `${node.connectionCount} công ty · ${formatPercent(node.totalOwnership)} tổng tỷ lệ sở hữu`;

  return `<strong>${title}</strong><br/><span>${escapeHtml(details)}</span>`;
}

function getSectorNodeLabel(node: OwnershipNode) {
  const title = escapeHtml(node.label);
  const sectorLabel =
    node.type === "company" && node.subindustry
      ? `${node.industry ?? "Chưa phân ngành"} · ${node.subindustry}`
      : node.industry ?? "Chưa phân ngành";
  const details =
    node.type === "company"
      ? `${sectorLabel} · ${node.connectionCount} cổ đông · ${formatPercent(node.totalOwnership)} tổng tỷ lệ trong graph`
      : `${node.connectionCount} công ty · ${formatPercent(node.totalOwnership)} tổng tỷ lệ sở hữu`;

  return `<strong>${title}</strong><br/><span>${escapeHtml(details)}</span>`;
}

function getNodeCameraPosition(node: OwnershipNode) {
  const x = node.x ?? 0;
  const y = node.y ?? 0;
  const z = node.z ?? 0;
  const distance = 90;
  const currentDistance = Math.hypot(x, y, z) || 1;
  const ratio = 1 + distance / currentDistance;

  return {
    position: { x: x * ratio, y: y * ratio, z: z * ratio },
    lookAt: { x, y, z },
  };
}

export function OwnershipGraphPanel({ sectorOverview = null }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<ForceGraph3DInstance<OwnershipNode, OwnershipLink> | null>(null);
  const [rawData, setRawData] = useState<RawCompanyShareholders[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [minOwnership, setMinOwnership] = useState(0);
  const [onlyShared, setOnlyShared] = useState(false);
  const [focusTicker, setFocusTicker] = useState("ALL");
  const [selectedNode, setSelectedNode] = useState<OwnershipNode | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");

    fetch(DATA_URL, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) {
          throw new Error("Không tải được dữ liệu cổ đông");
        }
        return response.json() as Promise<RawCompanyShareholders[]>;
      })
      .then((payload) => {
        setRawData(payload);
        setLoading(false);
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        setError(err.message);
        setRawData([]);
        setLoading(false);
      });

    return () => controller.abort();
  }, []);

  const tickerOptions = useMemo(() => rawData.map((item) => item.ticker.toUpperCase()).sort(), [rawData]);
  const sectorMetadata = useMemo(() => buildSectorMetadata(sectorOverview), [sectorOverview]);
  const graphData = useMemo(
    () => buildGraph(rawData, minOwnership, onlyShared, focusTicker, sectorMetadata.sectorByTicker),
    [focusTicker, minOwnership, onlyShared, rawData, sectorMetadata.sectorByTicker],
  );
  const visibleSectorLegend = useMemo(() => {
    const usedIndustries = new Set(
      graphData.nodes
        .filter((node) => node.type === "company")
        .map((node) => node.industry ?? "Chưa phân ngành"),
    );
    const sectorItems = [...sectorMetadata.sectorColorByIndustry.entries()]
      .filter(([industry]) => usedIndustries.has(industry))
      .map(([industry, color]) => ({ industry, color }));

    if (usedIndustries.has("Chưa phân ngành")) {
      sectorItems.push({ industry: "Chưa phân ngành", color: DEFAULT_COMPANY_COLOR });
    }

    return sectorItems;
  }, [graphData.nodes, sectorMetadata.sectorColorByIndustry]);

  useEffect(() => {
    if (!containerRef.current || graphRef.current) return;

    const graph = new ForceGraph3D(containerRef.current, {
      rendererConfig: { antialias: true, alpha: true },
    }) as unknown as ForceGraph3DInstance<OwnershipNode, OwnershipLink>;

    graph
      .backgroundColor("rgba(0,0,0,0)")
      .nodeLabel(getSectorNodeLabel)
      .nodeColor((node) => node.color)
      .nodeVal((node) => node.val)
      .linkLabel((link) => escapeHtml(link.label))
      .linkColor((link) => link.color)
      .linkOpacity(0.34)
      .linkWidth((link) => Math.max(0.35, Math.min(3.2, link.ownership / 2)))
      .linkDirectionalArrowLength((link) => Math.max(1.8, Math.min(4.8, link.ownership * 0.55)))
      .linkDirectionalArrowRelPos(1)
      .linkDirectionalParticles((link) => (link.ownership >= 5 ? 1 : 0))
      .linkDirectionalParticleWidth((link) => Math.max(1.2, Math.min(3, link.ownership / 2.4)))
      .cooldownTicks(120)
      .showNavInfo(false)
      .onNodeClick((node) => {
        setSelectedNode(node);
        const { position, lookAt } = getNodeCameraPosition(node);
        graph.cameraPosition(position, lookAt, 800);
      });

    graph.d3Force("charge")?.strength?.(-72);
    graphRef.current = graph;

    return () => {
      graph._destructor();
      graphRef.current = null;
    };
  }, []);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;

    graph.graphData({ nodes: graphData.nodes, links: graphData.links });
    setSelectedNode(null);

    window.setTimeout(() => {
      graph.zoomToFit(650, 70);
    }, 250);
  }, [graphData]);

  useEffect(() => {
    const graph = graphRef.current;
    const container = containerRef.current;
    if (!graph || !container) return;

    const resize = () => {
      const rect = container.getBoundingClientRect();
      graph.width(Math.max(320, Math.floor(rect.width)));
      graph.height(Math.max(420, Math.floor(rect.height)));
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);

    return () => observer.disconnect();
  }, [loading]);

  return (
    <div className="ownership-panel">
      <div className="ownership-header">
        <div>
          <strong>Graph cổ đông lớn VN30</strong>
          <span>3d-force-graph</span>
        </div>
        <div className="ownership-summary" aria-label="Tóm tắt graph">
          <span>{graphData.summary.companyCount} công ty</span>
          <span>{graphData.summary.shareholderCount} cổ đông</span>
          <span>{graphData.summary.linkCount} liên kết</span>
          <span>{graphData.summary.sectorCount} ngành</span>
        </div>
      </div>

      <div className="ownership-toolbar">
        <div className="field">
          <label htmlFor="ownership-focus">Focus mã</label>
          <select id="ownership-focus" value={focusTicker} onChange={(event) => setFocusTicker(event.target.value)}>
            <option value="ALL">Tất cả VN30</option>
            {tickerOptions.map((ticker) => (
              <option key={ticker} value={ticker}>
                {ticker}
              </option>
            ))}
          </select>
        </div>

        <div className="field ownership-range-field">
          <label htmlFor="ownership-threshold">Ngưỡng sở hữu: {formatPercent(minOwnership)}</label>
          <input
            id="ownership-threshold"
            type="range"
            min="0"
            max="5"
            step="0.25"
            value={minOwnership}
            onChange={(event) => setMinOwnership(Number(event.target.value))}
          />
        </div>

        <label className="ownership-toggle">
          <input type="checkbox" checked={onlyShared} onChange={(event) => setOnlyShared(event.target.checked)} />
          <span>Chỉ cổ đông chung</span>
        </label>

        <button
          type="button"
          className="ownership-reset-button"
          onClick={() => {
            setFocusTicker("ALL");
            setMinOwnership(0);
            setOnlyShared(false);
          }}
        >
          Reset
        </button>
      </div>

      <div className="ownership-legend" aria-label="Chú giải ngành">
        <span>
          <i style={{ background: HOLDER_COLOR }} /> Cổ đông
        </span>
        {visibleSectorLegend.map((sector) => (
          <span key={sector.industry}>
            <i style={{ background: sector.color }} /> {sector.industry}
          </span>
        ))}
      </div>

      <div className="ownership-legend" aria-label="Chú giải">
        <span>
          <i className="company" /> Công ty
        </span>
        <span>
          <i className="shared-holder" /> Cổ đông chung
        </span>
        <span>
          <i className="holder" /> Cổ đông
        </span>
      </div>

      <div className="ownership-stage">
        {loading ? <div className="ownership-empty">Đang tải dữ liệu cổ đông...</div> : null}
        {error ? <div className="ownership-empty error">{error}</div> : null}
        {!loading && !error && graphData.links.length === 0 ? (
          <div className="ownership-empty">Không có liên kết phù hợp với bộ lọc hiện tại.</div>
        ) : null}
        <div ref={containerRef} className="ownership-graph" />
      </div>

      <div className="ownership-selected">
        {selectedNode ? (
          <>
            <strong>{selectedNode.label}</strong>
            <span>
              {selectedNode.type === "company" ? "Công ty" : "Cổ đông"} · {selectedNode.connectionCount} liên kết ·{" "}
              {formatPercent(selectedNode.totalOwnership)}
            </span>
          </>
        ) : (
          <>
            <strong>Chưa chọn node</strong>
            <span>Click một node để xem nhanh số liên kết và tỷ lệ sở hữu.</span>
          </>
        )}
      </div>
    </div>
  );
}
