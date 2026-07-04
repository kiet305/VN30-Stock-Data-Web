import type { ValuationRankingItem, ValuationRankingResponse } from "../types";

type Props = {
  rankings: ValuationRankingResponse | null;
  loading?: boolean;
  error?: string;
  onTickerSelect?: (ticker: string) => void;
};

const PRICE_FORMATTER = new Intl.NumberFormat("vi-VN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
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

function formatPrice(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : PRICE_FORMATTER.format(value);
}

function formatChange(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : `${CHANGE_FORMATTER.format(value)}%`;
}

function formatDecimal(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : DECIMAL_FORMATTER.format(value);
}

function toneFromUpside(value: number | null | undefined) {
  if (value === null || value === undefined || value === 0) return "";
  return value > 0 ? "up" : "down";
}

function uniqueItems(items: ValuationRankingItem[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.ticker)) return false;
    seen.add(item.ticker);
    return true;
  });
}

function getChartItems(rankings: ValuationRankingResponse | null) {
  if (!rankings) return [];
  const source =
    rankings.items && rankings.items.length > 0
      ? rankings.items
      : uniqueItems([...(rankings.promising ?? []), ...(rankings.risky ?? [])]);

  return [...source].sort((first, second) => (second.upside_12m ?? -999) - (first.upside_12m ?? -999));
}

function ValuationComparisonChart({
  items,
  onTickerSelect,
}: {
  items: ValuationRankingItem[];
  onTickerSelect?: (ticker: string) => void;
}) {
  if (items.length === 0) {
    return (
      <section className="valuation-chart-card">
        <div className="valuation-ranking-empty">Chưa có đủ dữ liệu để vẽ biểu đồ định giá VN30.</div>
      </section>
    );
  }

  const maxPrice = Math.max(
    ...items.flatMap((item) => [item.current_price ?? 0, item.target_price_12m ?? 0]).filter((value) => value > 0),
    1,
  );
  const valuedItems = items.filter((item) => item.upside_12m !== null && item.upside_12m !== undefined);
  const averageUpside =
    valuedItems.reduce((total, item) => total + (item.upside_12m ?? 0), 0) / Math.max(valuedItems.length, 1);

  return (
    <section className="valuation-chart-card" aria-label="Biểu đồ định giá VN30">
      <div className="valuation-chart-header">
        <div>
          <strong>VN30: thị giá so với định giá</strong>
          <span>
            {items.length} mã VN30, {valuedItems.length} mã có target 12 tháng
          </span>
        </div>
        <div className="valuation-chart-summary">
          <span>Upside TB</span>
          <strong className={toneFromUpside(averageUpside) ? `metric-value ${toneFromUpside(averageUpside)}` : "metric-value"}>
            {formatChange(averageUpside)}
          </strong>
        </div>
      </div>

      <div className="valuation-chart-legend" aria-hidden="true">
        <span>
          <i className="actual" />
          Thị giá
        </span>
        <span>
          <i className="target" />
          Định giá 12T
        </span>
      </div>

      <div className="valuation-chart-scroll">
        {items.map((item) => {
          const currentWidth = Math.max(((item.current_price ?? 0) / maxPrice) * 100, item.current_price ? 2 : 0);
          const targetWidth = Math.max(((item.target_price_12m ?? 0) / maxPrice) * 100, item.target_price_12m ? 2 : 0);
          const tone = toneFromUpside(item.upside_12m);

          return (
            <button
              key={item.ticker}
              type="button"
              className="valuation-chart-row"
              onClick={() => onTickerSelect?.(item.ticker)}
            >
              <span className="valuation-chart-ticker">
                <strong>{item.ticker}</strong>
                <small>{item.latest_period ?? "--"}</small>
              </span>
              <span className="valuation-chart-bars">
                <span className="valuation-chart-bar actual" style={{ width: `${currentWidth}%` }}>
                  <b>{formatPrice(item.current_price)}</b>
                </span>
                <span className="valuation-chart-bar target" style={{ width: `${targetWidth}%` }}>
                  <b>{formatPrice(item.target_price_12m)}</b>
                </span>
              </span>
              <span className={tone ? `valuation-chart-upside metric-value ${tone}` : "valuation-chart-upside metric-value"}>
                {formatChange(item.upside_12m)}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function RankingTable({
  title,
  subtitle,
  items,
  type,
  onTickerSelect,
}: {
  title: string;
  subtitle: string;
  items: ValuationRankingItem[];
  type: "promising" | "risky";
  onTickerSelect?: (ticker: string) => void;
}) {
  return (
    <section className="valuation-ranking-card">
      <div className="valuation-ranking-title">
        <strong>{title}</strong>
        <span>{subtitle}</span>
      </div>
      <div className="valuation-ranking-table">
        <div className="valuation-ranking-row head">
          <span>Mã</span>
          <span>Thị giá</span>
          <span>Target 12T</span>
          <span>Upside</span>
          <span>EV/EBITDA</span>
        </div>
        {items.length > 0 ? (
          items.map((item, index) => {
            const tone = toneFromUpside(item.upside_12m);
            return (
              <button
                key={`${type}-${item.ticker}`}
                type="button"
                className="valuation-ranking-row"
                onClick={() => onTickerSelect?.(item.ticker)}
              >
                <span>
                  <b>{index + 1}</b>
                  <strong>{item.ticker}</strong>
                  <small>{item.latest_period ?? "--"}</small>
                </span>
                <span>{formatPrice(item.current_price)}</span>
                <span>{formatPrice(item.target_price_12m)}</span>
                <span className={tone ? `metric-value ${tone}` : "metric-value"}>{formatChange(item.upside_12m)}</span>
                <span>
                  {formatDecimal(item.ev_ebitda)}
                  <small>/ {formatDecimal(item.industry_ev_ebitda)}</small>
                </span>
              </button>
            );
          })
        ) : (
          <div className="valuation-ranking-empty">Chưa có mã đủ dữ liệu định giá.</div>
        )}
      </div>
    </section>
  );
}

export function ValuationMarketPanel({ rankings, loading = false, error = "", onTickerSelect }: Props) {
  const chartItems = getChartItems(rankings);

  if (loading) {
    return (
      <div className="valuation-market-panel">
        <div className="valuation-ranking-empty tall">
          <strong>Đang quét định giá</strong>
          <span>Hệ thống đang tính upside cho các mã trong danh sách theo dõi.</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="valuation-market-panel">
        <div className="valuation-ranking-empty tall">
          <strong>Không tải được định giá thị trường</strong>
          <span>{error}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="valuation-market-panel">
      <div className="valuation-market-header">
        <div>
          <strong>Triển vọng và rủi ro định giá</strong>
          <span>
            {rankings
              ? `${rankings.covered_count}/${rankings.universe_size} mã có đủ dữ liệu định giá`
              : "Xếp hạng theo target blended 12 tháng"}
          </span>
        </div>
        <div className="valuation-market-badge">Upside 12T</div>
      </div>

      <div className="valuation-ranking-grid">
        <ValuationComparisonChart items={chartItems} onTickerSelect={onTickerSelect} />
        <RankingTable
          title="Triển vọng"
          subtitle="Upside định giá 12 tháng cao nhất"
          items={rankings?.promising ?? []}
          type="promising"
          onTickerSelect={onTickerSelect}
        />
        <RankingTable
          title="Rủi ro"
          subtitle="Upside thấp nhất hoặc âm so với thị giá"
          items={rankings?.risky ?? []}
          type="risky"
          onTickerSelect={onTickerSelect}
        />
      </div>
    </div>
  );
}
