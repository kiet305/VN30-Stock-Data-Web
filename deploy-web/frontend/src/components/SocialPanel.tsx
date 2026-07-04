import type { CSSProperties } from "react";

import type { SocialResponse, SocialTickerItem, TrendItem, TrendResponse } from "../types";

type Props = {
  social: SocialResponse | null;
  trends?: TrendResponse | null;
  loading?: boolean;
  error?: string;
  onTickerSelect?: (ticker: string) => void;
};

const CLOUD_COLORS = ["#0f766e", "#2f6ca8", "#17202a", "#526171", "#8a6600", "#0f9f6e"];
const CLOUD_LAYOUT = [
  [50, 48, 0],
  [36, 42, -3],
  [64, 42, 3],
  [40, 62, 2],
  [60, 62, -2],
  [27, 52, -4],
  [73, 52, 4],
  [50, 30, -1],
  [50, 74, 1],
  [33, 28, 2],
  [67, 28, -2],
  [32, 74, -3],
  [68, 74, 3],
  [24, 38, 4],
  [76, 38, -4],
  [25, 66, -2],
  [75, 66, 2],
  [40, 20, -3],
  [60, 20, 3],
  [40, 84, 2],
  [60, 84, -2],
  [25, 24, -4],
  [75, 24, 4],
  [25, 82, 3],
];

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return "--";
  return new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(value);
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined) return "--";
  return `${new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 1 }).format(value)}%`;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "--";
  return new Date(value).toLocaleDateString("vi-VN");
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "--";
  return new Date(value).toLocaleString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
  });
}

function makeMiniTrendPath(points: number[], width: number, height: number) {
  if (points.length === 0) return "";

  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const step = points.length > 1 ? width / (points.length - 1) : width;

  return points
    .map((point, index) => {
      const x = index * step;
      const y = height - ((point - min) / range) * height;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

function formatTrendKeywords(keywords: string[]) {
  if (keywords.length === 0) return ["--"];
  return keywords.slice(0, 2);
}

function SocialTrendSparkline({ item }: { item: TrendItem }) {
  const width = 124;
  const height = 42;
  const path = makeMiniTrendPath(item.trend_points, width, height);
  const areaPath = path ? `${path} L ${width} ${height} L 0 ${height} Z` : "";

  if (!path) {
    return (
      <span className="social-trend-sparkline empty" aria-label="Chưa có đường xu hướng">
        --
      </span>
    );
  }

  return (
    <span
      className={item.active ? "social-trend-sparkline active" : "social-trend-sparkline"}
      aria-label={`Đường xu hướng ${item.keyword}`}
    >
      <svg viewBox={`0 0 ${width} ${height}`} role="img">
        <path className="social-trend-sparkline-area" d={areaPath} />
        <path className="social-trend-sparkline-line" d={path} />
      </svg>
    </span>
  );
}

function SocialTrendCompactRow({ item }: { item: TrendItem }) {
  return (
    <a
      className="social-trend-row"
      href={item.explore_url}
      target="_blank"
      rel="noreferrer"
      role="row"
      title={item.keyword}
    >
      <span className="social-trend-keyword" role="cell">
        <i>{item.rank}</i>
        <b>{item.keyword}</b>
      </span>
      <span className="social-trend-volume" role="cell">
        <b>{item.search_volume}</b>
      </span>
      <span className="social-trend-started" role="cell">
        <b>{item.started_label}</b>
        <small>{item.duration_label ?? item.status_label}</small>
      </span>
      <span className="social-trend-breakdown" role="cell">
        {formatTrendKeywords(item.trend_breakdown).map((keyword) => (
          <em key={keyword}>{keyword}</em>
        ))}
      </span>
      <span className="social-trend-chart" role="cell">
        <SocialTrendSparkline item={item} />
      </span>
    </a>
  );
}

function getCloudStyle(item: SocialTickerItem, maxScore: number, index: number): CSSProperties {
  const ratio = maxScore > 0 ? item.posts / maxScore : 0;
  const fontSize = 15 + ratio * 30;
  const opacity = 0.64 + ratio * 0.36;
  const [x, y, rotation] = CLOUD_LAYOUT[index % CLOUD_LAYOUT.length];

  return {
    "--cloud-color": CLOUD_COLORS[index % CLOUD_COLORS.length],
    "--cloud-size": `${fontSize}px`,
    "--cloud-opacity": opacity,
    "--cloud-x": `${x}%`,
    "--cloud-y": `${y}%`,
    "--cloud-rotation": `${rotation}deg`,
    zIndex: 40 - index,
  } as CSSProperties;
}

function SocialMetric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="social-metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

export function SocialPanel({ social, trends = null, loading = false, error = "", onTickerSelect }: Props) {
  const items = social?.items ?? [];
  const topItem = items[0];
  const maxScore = Math.max(...items.map((item) => item.posts), 0);
  const cloudItems = items.slice(0, 24);
  const socialTrendItems = trends?.items.filter((item) => item.trend_points.length > 0) ?? [];

  return (
    <section className="social-panel">
      <div className="social-header">
        <div>
          <strong>Social cổ phiếu</strong>
          <span>
            {social
              ? `Dữ liệu ${formatDate(social.date_from)} - ${formatDate(social.date_to)} · cập nhật ${formatDateTime(
                  social.updated_at,
                )}`
              : "Xếp hạng mức độ thảo luận theo số bài social"}
          </span>
        </div>
        <span className="social-source">{social?.source_file ?? "social.csv"}</span>
      </div>

      {error ? <div className="message error">{error}</div> : null}
      {loading ? <div className="message">Đang tải dữ liệu social...</div> : null}

      {social ? (
        <>
          <div className="social-metric-grid">
            <SocialMetric label="Số mã theo dõi" value={formatNumber(social.total_tickers)} detail="mã cổ phiếu" />
            <SocialMetric
              label="Tổng số bài"
              value={formatNumber(social.total_interest_score)}
              detail="theo post_count trong social.csv"
            />
            <SocialMetric
              label="Dẫn đầu"
              value={topItem?.ticker ?? "--"}
              detail={topItem ? `${formatPercent(topItem.attention_share)} tỷ trọng bài` : "--"}
            />
            <SocialMetric
              label="Nhiều bài nhất"
              value={items.length ? items.reduce((best, item) => (item.posts > best.posts ? item : best), items[0]).ticker : "--"}
              detail={items.length ? `${formatNumber(Math.max(...items.map((item) => item.posts)))} bài` : "--"}
            />
          </div>

          <div className="social-content-grid">
            <section className="social-cloud-card" aria-label="Đám mây số bài social">
              <div className="social-section-title">
                <strong>Đám mây bài viết</strong>
                <span>Kích thước mã tương ứng với số bài post</span>
              </div>
              <div className="social-cloud">
                {cloudItems.map((item, index) => (
                  <button
                    type="button"
                    key={item.ticker}
                    className="social-cloud-word"
                    style={getCloudStyle(item, maxScore, index)}
                    title={`${item.ticker}: ${formatNumber(item.posts)} bài viết`}
                    onClick={() => onTickerSelect?.(item.ticker)}
                  >
                    {item.ticker}
                    <small>{formatNumber(item.posts)}</small>
                  </button>
                ))}
              </div>
              {socialTrendItems.length > 0 ? (
                <div className="social-cloud-trends" aria-label="Xu hướng tìm kiếm nổi bật">
                  <div className="social-cloud-trends-title">
                    <strong>Toàn bộ xu hướng tìm kiếm</strong>
                    <span>{socialTrendItems.length} biểu đồ · 7 ngày qua</span>
                  </div>
                  <div className="social-trends-compact-table" role="table" aria-label="Xu hướng tìm kiếm thu gọn">
                    <div className="social-trend-row social-trend-row-head" role="row">
                      <span role="columnheader">Xu hướng</span>
                      <span role="columnheader">Lượng tìm kiếm</span>
                      <span role="columnheader">Đã bắt đầu</span>
                      <span role="columnheader">Chi tiết</span>
                      <span role="columnheader">7 ngày qua</span>
                    </div>
                    {socialTrendItems.map((item) => (
                      <SocialTrendCompactRow key={`${item.rank}-${item.keyword}`} item={item} />
                    ))}
                  </div>
                </div>
              ) : null}
            </section>

            <section className="social-ranking-card">
              <div className="social-section-title">
                <strong>Xếp hạng social</strong>
                <span>Top 13 mã theo số bài post</span>
              </div>
              <div className="social-table" role="table" aria-label="Xếp hạng social cổ phiếu">
                <div className="social-row social-row-head" role="row">
                  <span role="columnheader">Mã</span>
                  <span role="columnheader">Bài viết</span>
                  <span role="columnheader">Tương tác</span>
                  <span role="columnheader">Tỷ trọng</span>
                </div>
                {items.slice(0, 13).map((item) => (
                  <div key={item.ticker} className="social-row" role="row">
                    <button
                      type="button"
                      className="social-ticker"
                      role="cell"
                      onClick={() => onTickerSelect?.(item.ticker)}
                    >
                      <i>{item.rank}</i>
                      <b>{item.ticker}</b>
                    </button>
                    <span role="cell">
                      <b>{formatNumber(item.posts)}</b>
                      <small>{item.active_days} ngày có bài</small>
                    </span>
                    <span role="cell">
                      <b>{formatNumber(item.total_interactions)}</b>
                      <small>{formatNumber(item.shares)} share</small>
                    </span>
                    <span role="cell">
                      <b>{formatPercent(item.attention_share)}</b>
                      <small>trên tổng bài</small>
                    </span>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </>
      ) : null}

      {!loading && !error && !social ? (
        <div className="trends-empty">
          <strong>Chưa có dữ liệu social</strong>
          <span>Hãy kiểm tra file social.csv trong thư mục trend.</span>
        </div>
      ) : null}
    </section>
  );
}
