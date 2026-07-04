import type { TrendItem, TrendResponse } from "../types";

type Props = {
  trends: TrendResponse | null;
  loading?: boolean;
  error?: string;
};

function formatUpdatedAt(value: string | null | undefined) {
  if (!value) return "--";

  return new Date(value).toLocaleString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
  });
}

function formatTrendKeywords(keywords: string[]) {
  if (keywords.length === 0) return ["--"];
  return keywords.slice(0, 3);
}

function makeSparklinePath(points: number[], width: number, height: number) {
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

function TrendSparkline({ item }: { item: TrendItem }) {
  const width = 164;
  const height = 54;
  const path = makeSparklinePath(item.trend_points, width, height);
  const areaPath = path ? `${path} L ${width} ${height} L 0 ${height} Z` : "";

  if (!path) {
    return (
      <span className="trend-sparkline empty" aria-label="Chưa có đường xu hướng">
        Chưa có dữ liệu
      </span>
    );
  }

  return (
    <span className={item.active ? "trend-sparkline active" : "trend-sparkline"} aria-label={`Đường xu hướng ${item.keyword}`}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img">
        <path className="trend-sparkline-area" d={areaPath} />
        <path className="trend-sparkline-line" d={path} />
      </svg>
    </span>
  );
}

export function TrendsPanel({ trends, loading = false, error = "" }: Props) {
  const items = trends?.items ?? [];

  return (
    <section className="trends-panel">
      <div className="trends-header">
        <div>
          <strong>Xu hướng tìm kiếm</strong>
          <span>
            {trends
              ? `Đã cập nhật vào ${formatUpdatedAt(trends.updated_at)} · ${trends.total} xu hướng`
              : "Dữ liệu từ thư mục trend"}
          </span>
        </div>
        <span className="trends-source">{trends?.source_file ?? "trend/*.csv"}</span>
      </div>

      {error ? <div className="message error">{error}</div> : null}
      {loading ? <div className="message">Đang tải dữ liệu xu hướng...</div> : null}

      <div className="trends-table" role="table" aria-label="Xu hướng tìm kiếm">
        <div className="trends-row trends-row-head" role="row">
          <span role="columnheader">Xu hướng</span>
          <span role="columnheader">Lượng tìm kiếm</span>
          <span role="columnheader">Đã bắt đầu</span>
          <span role="columnheader">Bảng chi tiết</span>
          <span role="columnheader">7 ngày qua</span>
        </div>

        {items.map((item) => (
          <a
            key={`${item.rank}-${item.keyword}`}
            className="trends-row"
            href={item.explore_url}
            target="_blank"
            rel="noreferrer"
            role="row"
          >
            <span className="trend-keyword" role="cell">
              <i>{item.rank}</i>
              <b>{item.keyword}</b>
            </span>
            <span className="trend-volume" role="cell">
              <b>{item.search_volume}</b>
            </span>
            <span className="trend-started" role="cell">
              <b>{item.started_label}</b>
              <small>{item.duration_label ?? item.status_label}</small>
            </span>
            <span className="trend-breakdown" role="cell">
              {formatTrendKeywords(item.trend_breakdown).map((keyword) => (
                <em key={keyword}>{keyword}</em>
              ))}
            </span>
            <span role="cell">
              <TrendSparkline item={item} />
            </span>
          </a>
        ))}
      </div>

      {!loading && !error && items.length === 0 ? (
        <div className="trends-empty">
          <strong>Chưa có dữ liệu xu hướng</strong>
          <span>Hãy kiểm tra file CSV trong thư mục trend.</span>
        </div>
      ) : null}
    </section>
  );
}
