import { useEffect, useRef, useState } from "react";
import {
  ColorType,
  CrosshairMode,
  createChart,
  type BusinessDay,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
} from "lightweight-charts";

import type { Candle, ChartAnnotation } from "../types";

type Props = {
  annotations?: ChartAnnotation[];
  candles: Candle[];
  ticker: string;
  loading?: boolean;
};

const UP_COLOR = "#0f9f6e";
const DOWN_COLOR = "#d94b4b";
const DEFAULT_VISIBLE_BARS = 80;
const TOOLTIP_WIDTH = 236;
const TOOLTIP_HEIGHT = 172;
const TOOLTIP_MARGIN = 12;
const ANNOTATION_TOOLTIP_WIDTH = 340;
const ANNOTATION_TOOLTIP_HEIGHT = 190;

const PRICE_FORMATTER = new Intl.NumberFormat("vi-VN", {
  maximumFractionDigits: 2,
});

const VOLUME_FORMATTER = new Intl.NumberFormat("vi-VN", {
  maximumFractionDigits: 0,
});

type TooltipState = {
  date: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  trend: "up" | "down";
  x: number;
  y: number;
};

type AnnotationMarker = {
  date: string;
  type: "event" | "news" | "mixed";
  items: ChartAnnotation[];
  x: number;
  y: number;
  popupX: number;
  popupY: number;
};

function toBusinessDay(value: string): BusinessDay {
  const [year, month, day] = value.split("-").map(Number);
  return { year, month, day };
}

function isBusinessDay(value: unknown): value is BusinessDay {
  if (typeof value !== "object" || value === null) return false;

  const maybeDay = value as Partial<BusinessDay>;
  return typeof maybeDay.year === "number" && typeof maybeDay.month === "number" && typeof maybeDay.day === "number";
}

function timeToDateKey(value: unknown) {
  if (typeof value === "string") return value;
  if (!isBusinessDay(value)) return "";

  const month = String(value.month).padStart(2, "0");
  const day = String(value.day).padStart(2, "0");
  return `${value.year}-${month}-${day}`;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

function formatVolume(value: number | null) {
  return value === null ? "--" : VOLUME_FORMATTER.format(value);
}

function formatEventRatio(value: number | null) {
  if (value === null) return "--";

  const ratio = Math.abs(value) <= 1 ? value * 100 : value;
  return `${PRICE_FORMATTER.format(ratio)}%`;
}

function getAnnotationMarkerType(items: ChartAnnotation[]): AnnotationMarker["type"] {
  const hasEvent = items.some((item) => item.type === "event");
  const hasNews = items.some((item) => item.type === "news");
  if (hasEvent && hasNews) return "mixed";
  return hasEvent ? "event" : "news";
}

function getAnnotationMarkerLabel(marker: AnnotationMarker) {
  if (marker.items.length > 1) return String(marker.items.length);
  return marker.type === "event" ? "C" : "N";
}

function findAnchorDate(annotationDate: string, candleDates: string[]) {
  return candleDates.find((date) => date >= annotationDate) ?? candleDates[candleDates.length - 1] ?? "";
}

export function CandlestickChart({ annotations = [], candles, ticker, loading = false }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const [annotationMarkers, setAnnotationMarkers] = useState<AnnotationMarker[]>([]);
  const [activeAnnotation, setActiveAnnotation] = useState<AnnotationMarker | null>(null);
  const hasData = candles.length > 0;

  useEffect(() => {
    if (!hasData) {
      setTooltip(null);
      setAnnotationMarkers([]);
      setActiveAnnotation(null);
      return;
    }

    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth || 900,
      height: container.clientHeight || 540,
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#697586",
        fontFamily: "Manrope, Segoe UI, sans-serif",
      },
      grid: {
        vertLines: { color: "#edf1f5" },
        horzLines: { color: "#edf1f5" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: "#e6ebf1",
        scaleMargins: {
          top: 0.08,
          bottom: 0.26,
        },
      },
      timeScale: {
        borderColor: "#e6ebf1",
        fixLeftEdge: true,
        fixRightEdge: true,
        barSpacing: 8,
        minBarSpacing: 3,
        rightOffset: 0,
        secondsVisible: false,
        timeVisible: false,
      },
      handleScroll: {
        horzTouchDrag: true,
        mouseWheel: true,
        pressedMouseMove: true,
        vertTouchDrag: true,
      },
      handleScale: {
        axisDoubleClickReset: true,
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: UP_COLOR,
      downColor: DOWN_COLOR,
      borderUpColor: UP_COLOR,
      borderDownColor: DOWN_COLOR,
      wickUpColor: UP_COLOR,
      wickDownColor: DOWN_COLOR,
      priceFormat: {
        type: "price",
        precision: 2,
        minMove: 0.01,
      },
    });

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: {
        type: "volume",
      },
      priceScaleId: "",
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.78,
        bottom: 0,
      },
    });

    const candleData: CandlestickData<BusinessDay>[] = candles.map((item) => ({
      time: toBusinessDay(item.date),
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
    }));

    const volumeData: HistogramData<BusinessDay>[] = candles.map((item) => ({
      time: toBusinessDay(item.date),
      value: item.volume ?? 0,
      color: item.close >= item.open ? "rgba(15, 159, 110, 0.28)" : "rgba(217, 75, 75, 0.28)",
    }));
    const candlesByDate = new Map(candles.map((item) => [item.date, item]));
    const candleDates = candles.map((item) => item.date);
    const groupedAnnotations = annotations.reduce((groups, item) => {
      const anchorDate = findAnchorDate(item.date, candleDates);
      if (!anchorDate) return groups;

      const items = groups.get(anchorDate) ?? [];
      items.push(item);
      groups.set(anchorDate, items);
      return groups;
    }, new Map<string, ChartAnnotation[]>());

    candleSeries.setData(candleData);
    volumeSeries.setData(volumeData);

    const visibleBars = Math.min(candleData.length, DEFAULT_VISIBLE_BARS);
    const visibleRange = {
      from: Math.max(0, candleData.length - visibleBars),
      to: candleData.length - 1,
    };

    chart.timeScale().setVisibleLogicalRange(visibleRange);

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    const updateAnnotationMarkers = () => {
      const markerY = Math.round(container.clientHeight * 0.735);
      const nextMarkers: AnnotationMarker[] = [];

      groupedAnnotations.forEach((items, date) => {
        const x = chart.timeScale().timeToCoordinate(toBusinessDay(date));
        if (x === null || x < 0 || x > container.clientWidth) return;

        const preferredPopupX =
          x + ANNOTATION_TOOLTIP_WIDTH + TOOLTIP_MARGIN > container.clientWidth
            ? x - ANNOTATION_TOOLTIP_WIDTH - TOOLTIP_MARGIN
            : x + TOOLTIP_MARGIN;
        const preferredPopupY =
          markerY + ANNOTATION_TOOLTIP_HEIGHT > container.clientHeight
            ? markerY - ANNOTATION_TOOLTIP_HEIGHT - TOOLTIP_MARGIN
            : markerY + TOOLTIP_MARGIN;

        nextMarkers.push({
          date,
          type: getAnnotationMarkerType(items),
          items,
          x,
          y: markerY,
          popupX: clamp(preferredPopupX, TOOLTIP_MARGIN, container.clientWidth - ANNOTATION_TOOLTIP_WIDTH - TOOLTIP_MARGIN),
          popupY: clamp(preferredPopupY, TOOLTIP_MARGIN, container.clientHeight - ANNOTATION_TOOLTIP_HEIGHT - TOOLTIP_MARGIN),
        });
      });

      setAnnotationMarkers(nextMarkers);
      setActiveAnnotation((current) => {
        if (!current) return null;
        return nextMarkers.find((marker) => marker.date === current.date) ?? null;
      });
    };

    const resizeObserver = new ResizeObserver(([entry]) => {
      if (!entry) return;

      chart.applyOptions({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      });
      window.requestAnimationFrame(updateAnnotationMarkers);
    });

    resizeObserver.observe(container);

    const handleCrosshairMove: Parameters<IChartApi["subscribeCrosshairMove"]>[0] = (param) => {
      const point = param.point;
      const dateKey = timeToDateKey(param.time);

      if (
        !point ||
        !dateKey ||
        point.x < 0 ||
        point.y < 0 ||
        point.x > container.clientWidth ||
        point.y > container.clientHeight
      ) {
        setTooltip(null);
        return;
      }

      const candle = candlesByDate.get(dateKey);
      if (!candle) {
        setTooltip(null);
        return;
      }

      const preferredX =
        point.x + TOOLTIP_WIDTH + TOOLTIP_MARGIN > container.clientWidth
          ? point.x - TOOLTIP_WIDTH - TOOLTIP_MARGIN
          : point.x + TOOLTIP_MARGIN;
      const preferredY =
        point.y + TOOLTIP_HEIGHT + TOOLTIP_MARGIN > container.clientHeight
          ? point.y - TOOLTIP_HEIGHT - TOOLTIP_MARGIN
          : point.y + TOOLTIP_MARGIN;

      setTooltip({
        date: candle.date,
        open: PRICE_FORMATTER.format(candle.open),
        high: PRICE_FORMATTER.format(candle.high),
        low: PRICE_FORMATTER.format(candle.low),
        close: PRICE_FORMATTER.format(candle.close),
        volume: formatVolume(candle.volume),
        trend: candle.close >= candle.open ? "up" : "down",
        x: clamp(preferredX, TOOLTIP_MARGIN, container.clientWidth - TOOLTIP_WIDTH - TOOLTIP_MARGIN),
        y: clamp(preferredY, TOOLTIP_MARGIN, container.clientHeight - TOOLTIP_HEIGHT - TOOLTIP_MARGIN),
      });
    };

    chart.subscribeCrosshairMove(handleCrosshairMove);

    const handleVisibleRangeChange = () => {
      updateAnnotationMarkers();
    };

    chart.timeScale().subscribeVisibleLogicalRangeChange(handleVisibleRangeChange);

    const fitTimer = window.setTimeout(() => {
      chart.timeScale().setVisibleLogicalRange(visibleRange);
      updateAnnotationMarkers();
    }, 0);

    return () => {
      window.clearTimeout(fitTimer);
      chart.unsubscribeCrosshairMove(handleCrosshairMove);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(handleVisibleRangeChange);
      resizeObserver.disconnect();
      chart.remove();
      setTooltip(null);
      setAnnotationMarkers([]);
      setActiveAnnotation(null);
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, [annotations, candles, hasData, ticker]);

  return (
    <div className="chart-frame">
      <div className="chart-title">
        <div>
          <strong>{ticker}</strong>
          <span>{hasData ? `${candles.length.toLocaleString("vi-VN")} phiên giao dịch` : "Đang chờ dữ liệu"}</span>
        </div>
        <div className="legend">
          <span className="legend-item up">Tăng</span>
          <span className="legend-item down">Giảm</span>
          <span className="legend-item volume">Khối lượng giao dịch (cột dưới)</span>
        </div>
      </div>

      {hasData ? (
        <>
          <div className="chart-canvas" ref={containerRef} onMouseLeave={() => setActiveAnnotation(null)}>
            <div className="chart-annotations-layer" aria-label="Sự kiện cổ tức trên biểu đồ">
            {annotationMarkers.map((marker) => (
              <button
                key={marker.date}
                type="button"
                className={`chart-annotation-marker ${marker.type}`}
                style={{ left: marker.x, top: marker.y }}
                onMouseEnter={() => setActiveAnnotation(marker)}
                onFocus={() => setActiveAnnotation(marker)}
              >
                {getAnnotationMarkerLabel(marker)}
              </button>
            ))}
            </div>

          {activeAnnotation ? (
            <div
              className="chart-annotation-popover"
              style={{ left: activeAnnotation.popupX, top: activeAnnotation.popupY }}
              onMouseEnter={() => setActiveAnnotation(activeAnnotation)}
            >
              <div className="chart-annotation-popover-header">
                <strong>{activeAnnotation.date}</strong>
                <span>{activeAnnotation.items.length.toLocaleString("vi-VN")} mục</span>
              </div>
              <div className="chart-annotation-list">
                {activeAnnotation.items.map((item, index) => (
                  <div className={`chart-annotation-item ${item.type}`} key={`${item.type}-${item.title}-${index}`}>
                    <span className="chart-annotation-type">Cổ tức</span>
                    <strong>{item.title}</strong>
                    <p>
                      Tỉ lệ: <b>{formatEventRatio(item.ratio)}</b>
                    </p>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {tooltip ? (
            <div className={`ohlcv-tooltip ${tooltip.trend}`} style={{ left: tooltip.x, top: tooltip.y }}>
              <div className="ohlcv-tooltip-header">
                <strong>OHLCV</strong>
                <span>{tooltip.date}</span>
              </div>
              <div className="ohlcv-tooltip-grid">
                {[
                  ["O", "Giá mở cửa", tooltip.open],
                  ["H", "Giá cao nhất", tooltip.high],
                  ["L", "Giá thấp nhất", tooltip.low],
                  ["C", "Giá đóng cửa", tooltip.close],
                  ["V", "Khối lượng giao dịch", tooltip.volume],
                ].map(([label, name, value]) => (
                  <div className="ohlcv-tooltip-row" key={label}>
                    <span>
                      <b>{label}</b>
                      {name}
                    </span>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          </div>

        </>
      ) : (
        <div className="chart-empty-state static">
          <strong>{loading ? "Đang tải dữ liệu nến" : "Chưa có dữ liệu để vẽ biểu đồ"}</strong>
          <span>{loading ? "Biểu đồ sẽ tự hiển thị sau khi backend trả dữ liệu." : "Hãy chọn mã và tải dữ liệu từ PostgreSQL."}</span>
        </div>
      )}
    </div>
  );
}
