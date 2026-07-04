import { DividendEventsPanel } from "./DividendEventsPanel";
import type { ChartAnnotation, DividendEvent } from "../types";

type Props = {
  dividendEvents: DividendEvent[];
  dividendError?: string;
  dividendLoading?: boolean;
  dividendTitle?: string;
  dividendSubtitle?: string;
  dividendEmptyTitle?: string;
  dividendEmptyMessage?: string;
  showDividendTicker?: boolean;
  onDividendTickerSelect?: (ticker: string) => void;
  latestNewsDate?: string | null;
  news: ChartAnnotation[];
  newsTitle?: string;
  newsEmptyTitle?: string;
  newsEmptyMessage?: string;
  ticker: string;
};

const CHANGE_FORMATTER = new Intl.NumberFormat("vi-VN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "exceptZero",
});

const DAY_IN_MS = 24 * 60 * 60 * 1000;

function formatDisplayDate(value: string) {
  const [year, month, day] = value.split("-");
  if (!year || !month || !day) return value;
  return `${day}/${month}/${year}`;
}

function getSentimentBadge(value: string | null) {
  const label = value?.trim();
  if (!label) return null;

  const normalized = label.toLowerCase();
  if (["positive", "pos", "tích cực", "tich cuc"].includes(normalized)) {
    return { label: "Tích cực", tone: "positive" };
  }
  if (["negative", "neg", "tiêu cực", "tieu cuc"].includes(normalized)) {
    return { label: "Tiêu cực", tone: "negative" };
  }
  if (["neutral", "neu", "trung lập", "trung lap"].includes(normalized)) {
    return { label: "Trung lập", tone: "neutral" };
  }

  return { label, tone: "neutral" };
}

function formatPriceChange(value: number | null) {
  return value === null ? null : `${CHANGE_FORMATTER.format(value)}%`;
}

function getPriceChangeTone(value: number | null) {
  if (value === null || value === 0) return "neutral";
  return value > 0 ? "up" : "down";
}

function parseDateTime(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return null;
  return Date.UTC(year, month - 1, day);
}

function getWeekStart(time: number) {
  const date = new Date(time);
  const day = date.getUTCDay();
  const mondayOffset = (day + 6) % 7;
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() - mondayOffset);
}

function getWeeklySentimentStats(news: ChartAnnotation[]) {
  const dates = news
    .map((item) => parseDateTime(item.date))
    .filter((value): value is number => value !== null);
  const latestTime = dates.length > 0 ? Math.max(...dates) : null;
  const weekStart = latestTime === null ? null : getWeekStart(latestTime);
  const weekEnd = weekStart === null ? null : weekStart + 7 * DAY_IN_MS;
  const stats = { positive: 0, neutral: 0, negative: 0 };

  if (weekStart === null || weekEnd === null) return stats;

  news.forEach((item) => {
    const itemTime = parseDateTime(item.date);
    if (itemTime === null || itemTime < weekStart || itemTime >= weekEnd) return;

    const sentiment = getSentimentBadge(item.sentiment);
    if (sentiment?.tone === "positive") stats.positive += 1;
    else if (sentiment?.tone === "negative") stats.negative += 1;
    else stats.neutral += 1;
  });

  return stats;
}

export function NewsEventsPanel({
  dividendEvents,
  dividendError = "",
  dividendLoading = false,
  dividendTitle,
  dividendSubtitle = "Lịch sử trả cổ tức từ 2024",
  dividendEmptyTitle,
  dividendEmptyMessage = "Hãy chạy asset warehouse_events trong Dagster để cập nhật dữ liệu cổ tức.",
  showDividendTicker = false,
  onDividendTickerSelect,
  latestNewsDate = null,
  news,
  newsTitle,
  newsEmptyTitle = "Chưa có tin tức liên quan",
  newsEmptyMessage = "Tin tức sẽ xuất hiện khi backend trả dữ liệu từ nguồn news.",
  ticker,
}: Props) {
  const weeklySentimentStats = getWeeklySentimentStats(news);

  return (
    <div className="news-events-panel">
      <div className="news-events-dividend-card">
        <DividendEventsPanel
          events={dividendEvents}
          title={dividendTitle ?? `Cổ tức ${ticker}`}
          subtitle={dividendSubtitle}
          loading={dividendLoading}
          error={dividendError}
          emptyTitle={dividendEmptyTitle ?? `Chưa có lịch sử cổ tức ${ticker}`}
          emptyMessage={dividendEmptyMessage}
          showTicker={showDividendTicker}
          onTickerSelect={onDividendTickerSelect}
        />
      </div>

      <section className="chart-news-panel news-events-news-card" aria-label={`Tin tức của ${ticker}`}>
        <div className="chart-news-header">
          <div>
            <strong>{newsTitle ?? `Tin tức ${ticker}`}</strong>
            <span>
              {latestNewsDate ? `Cập nhật đến ngày ${formatDisplayDate(latestNewsDate)}` : "Cập nhật đến ngày --"}
            </span>
          </div>
          {news.length > 0 ? (
            <span className="chart-news-count">{news.length.toLocaleString("vi-VN")} bài viết liên quan</span>
          ) : null}
        </div>
        <div className="news-sentiment-summary" aria-label="Thống kê sắc thái tin tức trong tuần">
          <span>Trong tuần</span>
          <strong className="positive">{weeklySentimentStats.positive.toLocaleString("vi-VN")} tích cực</strong>
          <strong className="neutral">{weeklySentimentStats.neutral.toLocaleString("vi-VN")} trung lập</strong>
          <strong className="negative">{weeklySentimentStats.negative.toLocaleString("vi-VN")} tiêu cực</strong>
        </div>

        {news.length > 0 ? (
          <div className="chart-news-list">
            {news.map((item, index) => {
              const sentiment = getSentimentBadge(item.sentiment);
              const priceChange = formatPriceChange(item.price_change);
              const priceChangeTone = getPriceChangeTone(item.price_change);
              const priceChangeDate = item.price_change_date;

              return (
                <article
                  className={sentiment ? `chart-news-card ${sentiment.tone}` : "chart-news-card"}
                  key={`${item.date}-${item.url ?? item.title}-${index}`}
                >
                  <div className="chart-news-meta">
                    <div className="chart-news-meta-main">
                      <span>{formatDisplayDate(item.date)}</span>
                      {item.source ? <span className="chart-news-source">{item.source}</span> : null}
                    </div>
                    {sentiment ? <span className={`chart-news-sentiment ${sentiment.tone}`}>{sentiment.label}</span> : null}
                  </div>
                  <div className="chart-news-title">
                    {item.url ? (
                      <a href={item.url} target="_blank" rel="noreferrer">
                        {item.title}
                      </a>
                    ) : (
                      <strong>{item.title}</strong>
                    )}
                  </div>
                  <div className="chart-news-footer">
                    {priceChange ? (
                      <div className="chart-news-price-row">
                        <span className={`chart-news-price-change ${priceChangeTone}`}>{priceChange}</span>
                        {priceChangeDate && priceChangeDate !== item.date ? (
                          <span className="chart-news-price-date">Phiên {formatDisplayDate(priceChangeDate)}</span>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="dividend-events-empty">
            <strong>{newsEmptyTitle}</strong>
            <span>{newsEmptyMessage}</span>
          </div>
        )}
      </section>

    </div>
  );
}
