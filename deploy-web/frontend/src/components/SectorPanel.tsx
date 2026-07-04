import type { SectorConstituent, SectorOverviewItem, SectorOverviewResponse } from "../types";

type Props = {
  overview: SectorOverviewResponse | null;
  loading?: boolean;
  error?: string;
  onTickerSelect?: (ticker: string) => void;
};

const NUMBER_FORMATTER = new Intl.NumberFormat("vi-VN", {
  maximumFractionDigits: 0,
});

const DECIMAL_FORMATTER = new Intl.NumberFormat("vi-VN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const CHANGE_FORMATTER = new Intl.NumberFormat("vi-VN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "exceptZero",
});

const PERIODS = [
  ["weighted_change_1d", "1D"],
  ["weighted_change_1w", "1W"],
  ["weighted_change_1m", "1M"],
  ["weighted_change_3m", "3M"],
  ["weighted_change_6m", "6M"],
  ["weighted_change_1y", "1Y"],
  ["weighted_change_3y", "3Y"],
] as const;

function formatNumber(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : NUMBER_FORMATTER.format(value);
}

function formatDecimal(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : DECIMAL_FORMATTER.format(value);
}

function formatPercent(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : `${CHANGE_FORMATTER.format(value)}%`;
}

function formatMarketCap(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : `${NUMBER_FORMATTER.format(value)} tỷ`;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "--";
  return new Date(value).toLocaleDateString("vi-VN");
}

function toneFromChange(value: number | null | undefined) {
  if (value === null || value === undefined || value === 0) return "";
  return value > 0 ? "up" : "down";
}

function getSectorStatus(item: SectorOverviewItem) {
  const oneDayTone = toneFromChange(item.weighted_change_1d);
  if (oneDayTone === "up" && item.advancers >= item.decliners) return { label: "Tích cực", tone: "up" };
  if (oneDayTone === "down" && item.decliners > item.advancers) return { label: "Tiêu cực", tone: "down" };
  return { label: "Trung tính", tone: "" };
}

function SectorMetric({
  label,
  value,
  tone = "",
  detail,
}: {
  label: string;
  value: string;
  tone?: string;
  detail?: string;
}) {
  return (
    <div className="sector-metric">
      <span>{label}</span>
      <strong className={tone ? `metric-value ${tone}` : "metric-value"}>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function ConstituentRow({
  item,
  onTickerSelect,
}: {
  item: SectorConstituent;
  onTickerSelect?: (ticker: string) => void;
}) {
  const tone = toneFromChange(item.change_1d);

  return (
    <button type="button" className="sector-constituent-row" onClick={() => onTickerSelect?.(item.ticker)}>
      <span className="sector-constituent-name">
        <strong>{item.ticker}</strong>
        <small>{item.name ?? item.subindustry ?? "--"}</small>
      </span>
      <span>{formatMarketCap(item.market_cap)}</span>
      <span>{formatPercent(item.weight)}</span>
      <span className={tone ? `metric-value ${tone}` : "metric-value"}>{formatPercent(item.change_1d)}</span>
      <span>{formatDecimal(item.pe)}</span>
      <span>{formatDecimal(item.pb)}</span>
    </button>
  );
}

function SectorCard({ item, onTickerSelect }: { item: SectorOverviewItem; onTickerSelect?: (ticker: string) => void }) {
  const status = getSectorStatus(item);
  const oneDayTone = toneFromChange(item.weighted_change_1d);

  return (
    <section className="sector-card">
      <div className="sector-card-header">
        <div>
          <strong>{item.industry}</strong>
          <span>
            {formatNumber(item.ticker_count)} mã · {formatMarketCap(item.total_market_cap)}
          </span>
        </div>
        <span className={status.tone ? `sector-status ${status.tone}` : "sector-status"}>{status.label}</span>
      </div>

      <div className="sector-metric-grid">
        <SectorMetric label="P/E ngành" value={formatDecimal(item.average_pe)} />
        <SectorMetric label="P/B ngành" value={formatDecimal(item.average_pb)} />
        <SectorMetric label="Trong ngày" value={formatPercent(item.weighted_change_1d)} tone={oneDayTone} />
        <SectorMetric
          label="Độ rộng"
          value={`${formatNumber(item.advancers)}/${formatNumber(item.decliners)}`}
          detail={`${formatNumber(item.unchanged)} trung tính`}
        />
      </div>

      <div className="sector-period-strip" aria-label={`Biến động nhiều period của ${item.industry}`}>
        {PERIODS.map(([key, label]) => {
          const value = item[key];
          const tone = toneFromChange(value);
          return (
            <div className="sector-period-pill" key={key}>
              <span>{label}</span>
              <strong className={tone ? `metric-value ${tone}` : "metric-value"}>{formatPercent(value)}</strong>
            </div>
          );
        })}
      </div>

      <div className="sector-constituent-table">
        <div className="sector-constituent-row head">
          <span>Mã</span>
          <span>Vốn hóa</span>
          <span>T.trọng</span>
          <span>1D</span>
          <span>P/E</span>
          <span>P/B</span>
        </div>
        {item.top_constituents.length > 0 ? (
          item.top_constituents.map((constituent) => (
            <ConstituentRow key={constituent.ticker} item={constituent} onTickerSelect={onTickerSelect} />
          ))
        ) : (
          <div className="sector-empty compact">Chưa có mã vốn hóa lớn để so sánh.</div>
        )}
      </div>
    </section>
  );
}

export function SectorPanel({ overview, loading = false, error = "", onTickerSelect }: Props) {
  const items = overview?.items ?? [];
  const bestSector = items.reduce<SectorOverviewItem | null>((best, item) => {
    if (!best) return item;
    return (item.weighted_change_1d ?? Number.NEGATIVE_INFINITY) >
      (best.weighted_change_1d ?? Number.NEGATIVE_INFINITY)
      ? item
      : best;
  }, null);
  const positiveSectorCount = items.filter((item) => (item.weighted_change_1d ?? 0) > 0).length;

  if (loading) {
    return (
      <section className="sector-panel">
        <div className="sector-empty tall">
          <strong>Đang tải tổng quan ngành</strong>
          <span>Hệ thống đang nhóm P/E, P/B, biến động và vốn hóa theo từng ngành.</span>
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="sector-panel">
        <div className="sector-empty tall">
          <strong>Không tải được dữ liệu ngành</strong>
          <span>{error}</span>
        </div>
      </section>
    );
  }

  return (
    <section className="sector-panel">
      <div className="sector-header">
        <div>
          <strong>Tổng quan ngành</strong>
          <span>
            {overview
              ? `Dữ liệu ${formatDate(overview.as_of)} · ${formatNumber(overview.sector_count)} ngành`
              : "P/E, P/B, breadth trong ngày và so sánh các mã vốn hóa lớn có phân ngành"}
          </span>
        </div>
        <span className="sector-source">Market snapshot</span>
      </div>

      <div className="sector-summary-grid">
        <SectorMetric label="Số ngành" value={formatNumber(overview?.sector_count)} detail="nhóm theo ICB level 2" />
        <SectorMetric label="Tổng vốn hóa" value={formatMarketCap(overview?.total_market_cap)} detail="các mã có phân ngành" />
        <SectorMetric
          label="Ngành dẫn dắt"
          value={bestSector?.industry ?? "--"}
          tone={toneFromChange(bestSector?.weighted_change_1d)}
          detail={formatPercent(bestSector?.weighted_change_1d)}
        />
        <SectorMetric
          label="Độ rộng sector"
          value={`${formatNumber(positiveSectorCount)}/${formatNumber(items.length)}`}
          detail="số ngành tăng trong ngày"
        />
      </div>

      {items.length > 0 ? (
        <div className="sector-grid">
          {items.map((item) => (
            <SectorCard key={item.industry} item={item} onTickerSelect={onTickerSelect} />
          ))}
        </div>
      ) : (
        <div className="sector-empty tall">
          <strong>Chưa có dữ liệu sector</strong>
          <span>Cần dữ liệu giá và phân ngành trong warehouse để hiển thị tab này.</span>
        </div>
      )}
    </section>
  );
}
