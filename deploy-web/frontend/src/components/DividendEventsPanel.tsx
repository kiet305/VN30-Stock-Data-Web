import type { DividendEvent } from "../types";

type Props = {
  events: DividendEvent[];
  title: string;
  subtitle: string;
  loading?: boolean;
  error?: string;
  emptyTitle?: string;
  emptyMessage?: string;
  showTicker?: boolean;
  onTickerSelect?: (ticker: string) => void;
};

type DividendEventKind = "cash" | "stock" | "bonus" | "rights" | "swap" | "other";

const EVENT_KIND_META: Record<DividendEventKind, { label: string; className: string }> = {
  cash: {
    label: "Cổ tức tiền mặt",
    className: "cash",
  },
  stock: {
    label: "Cổ tức cổ phiếu",
    className: "stock",
  },
  bonus: {
    label: "Thưởng cổ phiếu",
    className: "bonus",
  },
  rights: {
    label: "Phát hành thêm",
    className: "rights",
  },
  swap: {
    label: "Hoán đổi cổ phiếu",
    className: "swap",
  },
  other: {
    label: "Sự kiện khác",
    className: "other",
  },
};

const PERCENT_FORMATTER = new Intl.NumberFormat("vi-VN", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

const MS_PER_DAY = 24 * 60 * 60 * 1000;

function formatDisplayDate(value: string | null) {
  if (!value) return "--";
  const [year, month, day] = value.split("-");
  if (!year || !month || !day) return value;
  return `${day}/${month}/${year}`;
}

function formatRatio(event: DividendEvent) {
  if (event.ratio_display) return event.ratio_display;
  if (event.ratio === null) return "--";

  const ratio = Math.abs(event.ratio) <= 1 ? event.ratio * 100 : event.ratio;
  return `${PERCENT_FORMATTER.format(ratio)}%`;
}

function formatValue(event: DividendEvent) {
  if (event.value_display) return event.value_display;
  if (event.value === null) return "--";

  return event.value.toLocaleString("vi-VN");
}

function formatDaysUntil(value: number | null) {
  if (value === null) return null;
  if (value === 0) return "Hôm nay";
  return `Còn ${value.toLocaleString("vi-VN")} ngày`;
}

function getDaysUntilDisplayDate(value: string | null, fallback: number | null) {
  if (!value) return fallback;

  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return fallback;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(year, month - 1, day);
  const daysUntil = Math.ceil((target.getTime() - today.getTime()) / MS_PER_DAY);
  return daysUntil >= 0 ? daysUntil : null;
}

function normalizeSearchText(value: string) {
  return value
    .toLocaleLowerCase("vi-VN")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function classifyDividendEvent(event: DividendEvent): DividendEventKind {
  if (event.event_type_id === 1) return "cash";
  if (event.event_type_id === 2) return "stock";
  if (event.event_type_id === 3) return "rights";
  if (event.event_type_id === 4) return "bonus";
  if (event.event_type_id === 5) return "swap";

  const text = normalizeSearchText(`${event.event_type ?? ""} ${event.title}`);
  if (text.includes("thuong co phieu")) return "bonus";
  if (text.includes("co tuc") && text.includes("co phieu")) return "stock";
  if (text.includes("tien mat") || text.includes("bang tien")) return "cash";
  if (text.includes("phat hanh them") || text.includes("quyen mua")) return "rights";
  if (text.includes("hoan doi")) return "swap";
  return "other";
}

function getDisplayDate(event: DividendEvent) {
  if (event.exright_date) {
    return {
      label: "Ngày GDKHQ",
      value: event.exright_date,
    };
  }

  if (event.record_date) {
    return {
      label: "Ngày ĐKCC",
      value: event.record_date,
    };
  }

  return {
    label: "Ngày sự kiện",
    value: event.date,
  };
}

export function DividendEventsPanel({
  events,
  title,
  subtitle,
  loading = false,
  error = "",
  emptyTitle = "Không có sự kiện cổ tức",
  emptyMessage = "Dữ liệu sẽ hiển thị sau khi warehouse_events được cập nhật.",
  showTicker = false,
  onTickerSelect,
}: Props) {
  const legendKinds = Array.from(new Set(events.map(classifyDividendEvent)));

  return (
    <div className="dividend-events-card">
      <div className="dividend-events-header">
        <div>
          <strong>{title}</strong>
          <span>{loading ? "Đang tải dữ liệu cổ tức" : subtitle}</span>
        </div>
        {events.length > 0 ? (
          <div className="dividend-events-meta">
            <span className="dividend-events-badge">{events.length.toLocaleString("vi-VN")} sự kiện</span>
            <div className="dividend-event-legend" aria-label="Chú thích loại sự kiện">
              {legendKinds.map((kind) => {
                const meta = EVENT_KIND_META[kind];
                return (
                  <span className={`dividend-event-legend-item dividend-event-legend-item--${meta.className}`} key={kind}>
                    <i />
                    {meta.label}
                  </span>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>

      {error ? (
        <div className="dividend-events-empty">
          <strong>Không tải được dữ liệu</strong>
          <span>{error}</span>
        </div>
      ) : events.length > 0 ? (
        <div className="dividend-events-list">
          {events.map((event, index) => {
            const eventKind = classifyDividendEvent(event);
            const eventMeta = EVENT_KIND_META[eventKind];
            const displayDate = getDisplayDate(event);
            const daysUntil = formatDaysUntil(getDaysUntilDisplayDate(displayDate.value, event.days_until));
            const eventTypeDetail =
              event.event_type && normalizeSearchText(event.event_type) !== normalizeSearchText(eventMeta.label)
                ? event.event_type
                : null;
            const rowClassName = [
              "dividend-event-row",
              showTicker ? "with-ticker" : "",
              `dividend-event-row--${eventMeta.className}`,
            ]
              .filter(Boolean)
              .join(" ");

            return (
              <article className={rowClassName} key={`${event.ticker}-${event.date}-${event.title}-${index}`}>
                {showTicker ? (
                  <button
                    type="button"
                    className="dividend-event-ticker"
                    onClick={() => onTickerSelect?.(event.ticker)}
                  >
                    {event.ticker}
                  </button>
                ) : null}

                <div className="dividend-event-date">
                  <strong>{formatDisplayDate(displayDate.value)}</strong>
                  <span>{displayDate.label}</span>
                  {daysUntil ? <em>{daysUntil}</em> : null}
                </div>

                <div className="dividend-event-content">
                  <span className={`dividend-event-type dividend-event-type--${eventMeta.className}`}>
                    {eventMeta.label}
                  </span>
                  <strong>{event.title}</strong>
                  {eventTypeDetail ? <small>{eventTypeDetail}</small> : null}
                </div>

                <div className="dividend-event-ratio">
                  <span>Tỷ lệ</span>
                  <strong>{formatRatio(event)}</strong>
                  <small>{formatValue(event)}</small>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="dividend-events-empty">
          <strong>{loading ? "Đang tải dữ liệu" : emptyTitle}</strong>
          <span>{loading ? "Danh sách sẽ tự hiển thị khi backend trả dữ liệu." : emptyMessage}</span>
        </div>
      )}
    </div>
  );
}
