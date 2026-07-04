import { useState, type CSSProperties, type ReactNode } from "react";

import type { FinancialDashboard, FinancialPoint, FinancialSeries, FinancialStatement } from "../types";

type Props = {
  dashboard: FinancialDashboard | null;
  ticker: string;
  loading?: boolean;
};

type PeriodMode = "quarter" | "year";
type DetailTabKey = string;

type FinancialRatioSpec = {
  key: string;
  label: string;
  aliases?: string[];
};

type SeriesSpec = {
  key: string;
  color: string;
  statementType?: string;
  criteria?: string[];
  label?: string;
};

type ChartSeries = FinancialSeries & {
  color: string;
};

type MetricNote = {
  text: string;
  tone: "up" | "down" | "flat";
};

type FinancialTooltip = {
  x: number;
  y: number;
  bandX: number;
  bandWidth: number;
  color: string;
  label: string;
  periodLabel: string;
  period: string;
  value: string;
  horizontal: "left" | "center" | "right";
  vertical: "above" | "below";
};

const VALUE_FORMATTER = new Intl.NumberFormat("vi-VN", {
  maximumFractionDigits: 0,
});

const DECIMAL_FORMATTER = new Intl.NumberFormat("vi-VN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const CHART_WIDTH = 720;
const CHART_HEIGHT = 260;
const CHART_PADDING = {
  top: 26,
  right: 18,
  bottom: 52,
  left: 64,
};
const FULL_YEAR_QUARTERS = [1, 2, 3, 4];
const FINANCIAL_RATIO_TAB_KEY = "RATIO";
const FINANCIAL_RATIO_SPECS: FinancialRatioSpec[] = [
  { key: "roe", label: "ROE" },
  { key: "roa", label: "ROA" },
  { key: "pe", label: "P/E", aliases: ["p_e"] },
  { key: "pb", label: "P/B", aliases: ["p_b"] },
  { key: "eps", label: "EPS" },
  { key: "bvps", label: "BVPS" },
  { key: "net_interest_margin", label: "NIM", aliases: ["nim"] },
];
const DETAIL_YOY_CRITERIA = new Set([
  "revenue",
  "gross_profit",
  "operating_profit",
  "profit_before_tax",
  "profit",
  "parent_profit",
]);

function formatValue(value: number | null | undefined, unit: string) {
  if (value === null || value === undefined) return "--";
  if (unit === "%") return `${DECIMAL_FORMATTER.format(value)}%`;
  return `${VALUE_FORMATTER.format(value)} tỷ`;
}

function formatDetailValue(value: number | null | undefined, unit: string | null | undefined) {
  if (value === null || value === undefined) return "--";
  if (unit === "%") return `${DECIMAL_FORMATTER.format(value)}%`;
  if (unit === "x") return `${DECIMAL_FORMATTER.format(value)}x`;
  if (unit === "đ/CP") return new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(value);
  return new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 1 }).format(value);
}

function formatAxisValue(value: number, unit: string) {
  if (unit === "%") {
    return `${new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 1 }).format(value)}%`;
  }

  const absoluteValue = Math.abs(value);
  if (absoluteValue >= 1000) {
    return `${new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 1 }).format(value / 1000)}k`;
  }

  return VALUE_FORMATTER.format(value);
}

function shouldShowPeriodTick(point: FinancialPoint, index: number, total: number) {
  if (total <= 10) return true;
  if (index === 0 || index === total - 1) return true;
  if (point.quarter <= 0) return true;

  const step = total > 30 ? 8 : 4;
  return index % step === 0;
}

function periodTickParts(period: string) {
  const [quarter, year] = period.split("/");
  return {
    quarter: quarter || period,
    year: year || "",
  };
}

function getPointValue(point: FinancialPoint | undefined) {
  return point?.value === null || point?.value === undefined ? null : point.value;
}

function getCompleteYearsFromSeries(series: FinancialSeries | undefined) {
  const years = new Set<number>();
  if (!series) return years;

  const grouped = new Map<number, FinancialPoint[]>();
  series.points.forEach((point) => {
    if (point.quarter <= 0) return;
    const points = grouped.get(point.year) ?? [];
    points.push(point);
    grouped.set(point.year, points);
  });

  grouped.forEach((points, year) => {
    const hasFullValues = FULL_YEAR_QUARTERS.every((quarter) => {
      const point = points.find((item) => item.quarter === quarter);
      return point?.value !== null && point?.value !== undefined;
    });
    if (hasFullValues) years.add(year);
  });

  return years;
}

function getCompleteYearsFromStatements(statements: FinancialStatement[]) {
  const years = new Set<number>();
  const periods = statements.flatMap((statement) => statement.periods);
  const grouped = new Map<number, Set<number>>();
  periods.forEach((period) => {
    if (period.quarter <= 0) return;
    const quarters = grouped.get(period.year) ?? new Set<number>();
    quarters.add(period.quarter);
    grouped.set(period.year, quarters);
  });

  grouped.forEach((quarters, year) => {
    if (FULL_YEAR_QUARTERS.every((quarter) => quarters.has(quarter))) {
      years.add(year);
    }
  });

  return years;
}

function intersectYearSets(yearSets: Set<number>[]) {
  if (yearSets.length === 0) return new Set<number>();

  const [first, ...rest] = yearSets;
  return new Set([...first].filter((year) => rest.every((set) => set.has(year))));
}

function resolveCompleteYears(seriesList: Array<FinancialSeries | undefined>, statements: FinancialStatement[]) {
  const populatedSeriesSets = seriesList.map(getCompleteYearsFromSeries).filter((set) => set.size > 0);
  const seriesYears = intersectYearSets(populatedSeriesSets);
  if (seriesYears.size > 0) return seriesYears;
  return getCompleteYearsFromStatements(statements);
}

function getAxisTicks(min: number, max: number) {
  const tickCount = 5;
  const range = max - min || 1;

  return Array.from({ length: tickCount }, (_, index) => {
    const value = min + (range * index) / (tickCount - 1);
    return Number(value.toFixed(6));
  });
}

function getLatestPoint(series: FinancialSeries | undefined) {
  if (!series) return undefined;
  return [...series.points].reverse().find((point) => point.value !== null);
}

function getYoYNote(series: FinancialSeries | undefined): MetricNote | undefined {
  const latest = getLatestPoint(series);
  if (!series || latest?.value === null || latest?.value === undefined) return undefined;

  const previous = series.points.find(
    (point) =>
      point.year === latest.year - 1 &&
      (latest.quarter === 0 || point.quarter === latest.quarter) &&
      point.value !== null,
  );
  if (previous?.value === null || previous?.value === undefined || previous.value === 0) return undefined;

  const change = ((latest.value - previous.value) / Math.abs(previous.value)) * 100;
  const formatted = DECIMAL_FORMATTER.format(Math.abs(change));
  const sign = change > 0 ? "+" : change < 0 ? "-" : "";
  const tone = change > 0 ? "up" : change < 0 ? "down" : "flat";
  return {
    text: `${sign}${formatted}% YoY`,
    tone,
  };
}

function aggregateSeries(
  series: FinancialSeries | undefined,
  mode: PeriodMode,
  aggregation: "sum" | "last",
  completeYears?: Set<number>,
) {
  if (!series || mode === "quarter") return series;

  const groups = new Map<number, FinancialPoint[]>();
  series.points.forEach((point) => {
    const points = groups.get(point.year) ?? [];
    points.push(point);
    groups.set(point.year, points);
  });

  const years = completeYears?.size
    ? [...completeYears].sort((firstYear, secondYear) => firstYear - secondYear)
    : [...groups.keys()].sort((firstYear, secondYear) => firstYear - secondYear);

  return {
    ...series,
    points: years.map((year) => {
      const points = groups.get(year) ?? [];
      const quarterPoints = FULL_YEAR_QUARTERS.map((quarter) => points.find((point) => point.quarter === quarter));
      const quarterValues = quarterPoints.map(getPointValue);
      const hasFullYearValues = quarterValues.every((value) => value !== null);
      const value =
        aggregation === "sum"
          ? hasFullYearValues
            ? quarterValues.reduce((total, value) => total + (value ?? 0), 0)
            : null
          : getPointValue(quarterPoints[quarterPoints.length - 1]);

      return {
        period: String(year),
        year,
        quarter: 0,
        value,
      };
    }),
  };
}

function aggregateChartSeries(
  series: ChartSeries[],
  mode: PeriodMode,
  aggregation: "sum" | "last",
  completeYears?: Set<number>,
) {
  return series.map((item) => {
    const aggregated = aggregateSeries(item, mode, aggregation, completeYears) ?? item;
    return { ...aggregated, color: item.color };
  });
}

function annualizeMetricSeries(series: FinancialSeries | undefined, mode: PeriodMode) {
  if (!series || mode === "quarter") return series;

  const groups = new Map<number, FinancialPoint[]>();
  series.points.forEach((point) => {
    if (point.quarter <= 0) return;
    const points = groups.get(point.year) ?? [];
    points.push(point);
    groups.set(point.year, points);
  });

  return {
    ...series,
    points: [...groups.entries()]
      .sort(([firstYear], [secondYear]) => firstYear - secondYear)
      .map(([year, points]) => {
        const sortedPoints = [...points].sort((first, second) => first.quarter - second.quarter);
        const q4Point = sortedPoints.find((point) => point.quarter === 4);
        const selectedPoint = q4Point ?? sortedPoints[sortedPoints.length - 1];
        return {
          period: String(year),
          year,
          quarter: 0,
          value: selectedPoint?.value ?? null,
        };
      }),
  };
}

function resolveFinancialRatioSeries(seriesList: FinancialSeries[], spec: FinancialRatioSpec) {
  const acceptedKeys = new Set([spec.key, ...(spec.aliases ?? [])].map((key) => normalizeSearchText(key)));
  const acceptedLabels = new Set([spec.label, ...(spec.aliases ?? [])].map((label) => normalizeSearchText(label)));

  return (
    seriesList.find((item) => acceptedKeys.has(normalizeSearchText(item.key))) ??
    seriesList.find((item) => acceptedLabels.has(normalizeSearchText(item.label)))
  );
}

function getFinancialRatioRows(seriesList: FinancialSeries[], mode: PeriodMode) {
  return FINANCIAL_RATIO_SPECS.map((spec) => {
    const series = resolveFinancialRatioSeries(seriesList, spec);
    const displaySeries = annualizeMetricSeries(series, mode);
    return {
      key: spec.key,
      label: spec.label,
      unit: series?.unit ?? "",
      points: displaySeries?.points ?? [],
    };
  });
}

function getFinancialRatioPeriods(rows: ReturnType<typeof getFinancialRatioRows>) {
  const periodMap = new Map<string, FinancialPoint>();

  rows.forEach((row) => {
    row.points.forEach((point) => {
      if (!periodMap.has(point.period)) {
        periodMap.set(point.period, point);
      }
    });
  });

  return [...periodMap.values()].sort((first, second) => first.year - second.year || first.quarter - second.quarter);
}

function buildMarginSeries(
  marginSeries: ChartSeries | undefined,
  revenueSeries: FinancialSeries | undefined,
  profitSeries: FinancialSeries | undefined,
  mode: PeriodMode,
  completeYears?: Set<number>,
): ChartSeries | undefined {
  if (!marginSeries || mode === "quarter") return marginSeries;

  const annualRevenue = aggregateSeries(revenueSeries, "year", "sum", completeYears);
  const annualProfit = aggregateSeries(profitSeries, "year", "sum", completeYears);
  if (!annualRevenue || !annualProfit) return aggregateSeries(marginSeries, "year", "last", completeYears) as ChartSeries;

  return {
    ...marginSeries,
    points: annualRevenue.points.map((revenuePoint) => {
      const profitPoint = annualProfit.points.find((point) => point.year === revenuePoint.year);
      const value =
        revenuePoint.value === null ||
        revenuePoint.value === undefined ||
        revenuePoint.value === 0 ||
        profitPoint?.value === null ||
        profitPoint?.value === undefined
          ? null
          : (profitPoint.value / revenuePoint.value) * 100;

      return {
        period: revenuePoint.period,
        year: revenuePoint.year,
        quarter: 0,
        value,
      };
    }),
  };
}

function hasSeriesData(series: FinancialSeries | undefined) {
  return Boolean(series?.points.some((point) => point.value !== null && point.value !== undefined));
}

function seriesFromStatement(dashboard: FinancialDashboard, spec: SeriesSpec): FinancialSeries | null {
  if (!spec.statementType || !spec.criteria?.length) return null;

  const statement = dashboard.statements?.find((item) => item.type === spec.statementType);
  if (!statement) return null;

  const row = statement.rows.find((item) => spec.criteria?.includes(item.criteria) || spec.criteria?.includes(item.item_id));
  if (!row) return null;

  const periods = [...statement.periods].sort((first, second) => first.year - second.year || first.quarter - second.quarter);
  return {
    key: spec.key,
    label: spec.label ?? row.name_vi,
    unit: row.unit ?? "tỷ đồng",
    points: periods.map((period) => ({
      period: period.label,
      year: period.year,
      quarter: period.quarter,
      value: row.values[period.key] ?? null,
    })),
  };
}

function selectSeries(dashboard: FinancialDashboard, specs: SeriesSpec[]): ChartSeries[] {
  return specs
    .map((spec) => {
      const series = dashboard.series.find((item) => item.key === spec.key);
      const fallback = seriesFromStatement(dashboard, spec);
      const resolved = hasSeriesData(series) ? series : fallback;
      return resolved ? { ...resolved, color: spec.color } : null;
    })
    .filter((item): item is ChartSeries => item !== null);
}

function getBounds(series: ChartSeries[]) {
  const values = series
    .flatMap((item) => item.points.map((point) => point.value))
    .filter((value): value is number => value !== null);
  if (values.length === 0) return { min: 0, max: 1 };

  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  if (min === max) return { min: min - 1, max: max + 1 };

  const padding = (max - min) * 0.12;
  return { min: min - padding, max: max + padding };
}

function scaleY(value: number, min: number, max: number) {
  const innerHeight = CHART_HEIGHT - CHART_PADDING.top - CHART_PADDING.bottom;
  return CHART_PADDING.top + ((max - value) / (max - min)) * innerHeight;
}

function createTooltip(
  label: string,
  periodLabel: string,
  period: string,
  value: number,
  unit: string,
  color: string,
  x: number,
  y: number,
  bandX: number,
  bandWidth: number,
): FinancialTooltip {
  const xPercent = (x / CHART_WIDTH) * 100;
  const yPercent = (y / CHART_HEIGHT) * 100;

  return {
    x: xPercent,
    y: yPercent,
    bandX,
    bandWidth,
    color,
    label,
    periodLabel,
    period,
    value: formatValue(value, unit),
    horizontal: xPercent < 18 ? "right" : xPercent > 82 ? "left" : "center",
    vertical: yPercent < 24 ? "below" : "above",
  };
}

function FinancialChartTooltip({ tooltip }: { tooltip: FinancialTooltip | null }) {
  if (!tooltip) return null;

  const style = {
    "--tooltip-color": tooltip.color,
    left: `${tooltip.x}%`,
    top: `${tooltip.y}%`,
  } as CSSProperties;

  return (
    <div className={`financial-chart-tooltip ${tooltip.horizontal} ${tooltip.vertical}`} style={style}>
      <div className="financial-chart-tooltip-title">
        <span className="financial-chart-tooltip-dot" />
        <strong>{tooltip.label}</strong>
      </div>
      <div className="financial-chart-tooltip-row">
        <span>{tooltip.periodLabel}</span>
        <b>{tooltip.period}</b>
      </div>
      <div className="financial-chart-tooltip-row">
        <span>Giá trị</span>
        <b>{tooltip.value}</b>
      </div>
    </div>
  );
}

function FinancialHoverBand({ tooltip }: { tooltip: FinancialTooltip | null }) {
  if (!tooltip) return null;

  return (
    <rect
      className="financial-hover-band"
      x={tooltip.bandX}
      y={CHART_PADDING.top - 6}
      width={tooltip.bandWidth}
      height={CHART_HEIGHT - CHART_PADDING.top - CHART_PADDING.bottom + 12}
      rx="12"
    />
  );
}

function FinancialAxes({
  min,
  max,
  unit,
  periodLabel = "Quý",
}: {
  min: number;
  max: number;
  unit: string;
  periodLabel?: string;
}) {
  const ticks = getAxisTicks(min, max);
  const xAxisY = CHART_HEIGHT - CHART_PADDING.bottom;

  return (
    <g className="financial-axes">
      <text x={CHART_PADDING.left} y="13" className="financial-axis-title">
        {unit === "%" ? "%" : "Tỷ đồng"}
      </text>
      {ticks.map((tick) => {
        const y = scaleY(tick, min, max);

        return (
          <g key={tick}>
            <line
              x1={CHART_PADDING.left}
              x2={CHART_WIDTH - CHART_PADDING.right}
              y1={y}
              y2={y}
              className="financial-grid-line"
            />
            <text x={CHART_PADDING.left - 10} y={y + 4} textAnchor="end" className="financial-y-axis-label">
              {formatAxisValue(tick, unit)}
            </text>
          </g>
        );
      })}
      <line
        x1={CHART_PADDING.left}
        x2={CHART_PADDING.left}
        y1={CHART_PADDING.top}
        y2={xAxisY}
        className="financial-axis-line"
      />
      <line
        x1={CHART_PADDING.left}
        x2={CHART_WIDTH - CHART_PADDING.right}
        y1={xAxisY}
        y2={xAxisY}
        className="financial-axis-line"
      />
      <text x={CHART_WIDTH - CHART_PADDING.right} y={CHART_HEIGHT - 3} textAnchor="end" className="financial-axis-title">
        {periodLabel}
      </text>
    </g>
  );
}

function ChartLegend({ series }: { series: ChartSeries[] }) {
  return (
    <div className="financial-chart-legend">
      {series.map((item) => (
        <span key={item.key}>
          <i style={{ background: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  );
}

function BarChart({ series, periodLabel }: { series: ChartSeries[]; periodLabel?: string }) {
  const [tooltip, setTooltip] = useState<FinancialTooltip | null>(null);
  const periods = series[0]?.points ?? [];
  const { min, max } = getBounds(series);
  const innerWidth = CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
  const groupWidth = periods.length > 0 ? innerWidth / periods.length : innerWidth;
  const barWidth = Math.max(5, Math.min(18, (groupWidth * 0.68) / Math.max(series.length, 1)));
  const zeroY = scaleY(0, min, max);
  const unit = series[0]?.unit ?? "tỷ đồng";

  return (
    <div className="financial-chart-body">
      <div className="financial-chart-plot" onPointerLeave={() => setTooltip(null)}>
        <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} role="img">
          <FinancialAxes min={min} max={max} unit={unit} periodLabel={periodLabel} />
          <FinancialHoverBand tooltip={tooltip} />
          <line
            x1={CHART_PADDING.left}
            x2={CHART_WIDTH - CHART_PADDING.right}
            y1={zeroY}
            y2={zeroY}
            className="financial-axis"
          />
          {periods.map((period, periodIndex) => {
            const groupX = CHART_PADDING.left + periodIndex * groupWidth + groupWidth / 2;
            const showPeriodLabel = shouldShowPeriodTick(period, periodIndex, periods.length);
            const tickParts = periodTickParts(period.period);

            return (
              <g key={period.period}>
                {series.map((item, seriesIndex) => {
                  const value = item.points[periodIndex]?.value;
                  if (value === null || value === undefined) return null;

                  const x = groupX - (barWidth * series.length) / 2 + seriesIndex * barWidth;
                  const y = scaleY(Math.max(value, 0), min, max);
                  const valueY = scaleY(value, min, max);
                  const height = Math.abs(valueY - zeroY);
                  const barX = x;
                  const barWidthVisible = barWidth * 0.78;
                  const tooltipData = createTooltip(
                    item.label,
                    periodLabel ?? "Quý",
                    period.period,
                    value,
                    item.unit,
                    item.color,
                    barX + barWidthVisible / 2,
                    valueY,
                    groupX - groupWidth / 2,
                    groupWidth,
                  );

                  return (
                    <rect
                      key={item.key}
                      aria-label={`${item.label} ${period.period} ${formatValue(value, item.unit)}`}
                      className="financial-data-point"
                      tabIndex={0}
                      x={barX}
                      y={value >= 0 ? y : zeroY}
                      width={barWidthVisible}
                      height={Math.max(height, 1)}
                      rx="4"
                      fill={item.color}
                      onFocus={() => setTooltip(tooltipData)}
                      onPointerEnter={() => setTooltip(tooltipData)}
                    />
                  );
                })}
                <line
                  x1={groupX}
                  x2={groupX}
                  y1={CHART_HEIGHT - CHART_PADDING.bottom}
                  y2={CHART_HEIGHT - CHART_PADDING.bottom + 4}
                  className="financial-period-tick"
                />
                {showPeriodLabel ? (
                  <text x={groupX} y={CHART_HEIGHT - 34} textAnchor="middle" className="financial-axis-label">
                    <tspan x={groupX}>{tickParts.quarter}</tspan>
                    {tickParts.year ? (
                      <tspan x={groupX} dy="12">
                        {tickParts.year}
                      </tspan>
                    ) : null}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
        <FinancialChartTooltip tooltip={tooltip} />
      </div>
    </div>
  );
}

function LineChart({ series, periodLabel }: { series: ChartSeries; periodLabel?: string }) {
  const [tooltip, setTooltip] = useState<FinancialTooltip | null>(null);
  const values = series.points.filter((point) => point.value !== null);
  const chartSeries = [{ ...series }];
  const { min, max } = getBounds(chartSeries);
  const innerWidth = CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
  const step = series.points.length > 1 ? innerWidth / (series.points.length - 1) : innerWidth;
  const points = values
    .map((point) => {
      const index = series.points.findIndex((item) => item.period === point.period);
      const x = CHART_PADDING.left + index * step;
      const y = scaleY(point.value ?? 0, min, max);
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <div className="financial-chart-body">
      <div className="financial-chart-plot" onPointerLeave={() => setTooltip(null)}>
        <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} role="img">
          <FinancialAxes min={min} max={max} unit={series.unit} periodLabel={periodLabel} />
          <FinancialHoverBand tooltip={tooltip} />
          <line
            x1={CHART_PADDING.left}
            x2={CHART_WIDTH - CHART_PADDING.right}
            y1={scaleY(0, min, max)}
            y2={scaleY(0, min, max)}
            className="financial-axis"
          />
          <polyline points={points} fill="none" stroke={series.color} strokeWidth="3" strokeLinejoin="round" />
          {series.points.map((point, index) => {
            if (point.value === null) return null;

            const x = CHART_PADDING.left + index * step;
            const y = scaleY(point.value, min, max);
            const bandWidth = series.points.length > 1 ? step : innerWidth;
            const bandX = Math.max(
              CHART_PADDING.left,
              Math.min(x - bandWidth / 2, CHART_WIDTH - CHART_PADDING.right - bandWidth),
            );
            const tooltipData = createTooltip(
              series.label,
              periodLabel ?? "Quý",
              point.period,
              point.value,
              series.unit,
              series.color,
              x,
              y,
              bandX,
              bandWidth,
            );

            return (
              <g
                key={point.period}
                aria-label={`${series.label} ${point.period} ${formatValue(point.value, series.unit)}`}
                className="financial-data-point"
                tabIndex={0}
                onFocus={() => setTooltip(tooltipData)}
                onPointerEnter={() => setTooltip(tooltipData)}
              >
                <circle cx={x} cy={y} r="10" fill="transparent" />
                <circle className="financial-point-halo" cx={x} cy={y} r="8" fill={series.color} />
                <circle cx={x} cy={y} r="4" fill={series.color} />
              </g>
            );
          })}
          {series.points.map((point, index) => {
            const x = CHART_PADDING.left + index * step;
            const showPeriodLabel = shouldShowPeriodTick(point, index, series.points.length);
            const tickParts = periodTickParts(point.period);
            return (
              <g key={point.period}>
                <line
                  x1={x}
                  x2={x}
                  y1={CHART_HEIGHT - CHART_PADDING.bottom}
                  y2={CHART_HEIGHT - CHART_PADDING.bottom + 4}
                  className="financial-period-tick"
                />
                {showPeriodLabel ? (
                  <text x={x} y={CHART_HEIGHT - 34} textAnchor="middle" className="financial-axis-label">
                    <tspan x={x}>{tickParts.quarter}</tspan>
                    {tickParts.year ? (
                      <tspan x={x} dy="12">
                        {tickParts.year}
                      </tspan>
                    ) : null}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
        <FinancialChartTooltip tooltip={tooltip} />
      </div>
    </div>
  );
}

function MetricCard({
  label,
  point,
  unit,
  note,
}: {
  label: string;
  point: FinancialPoint | undefined;
  unit: string;
  note?: MetricNote;
}) {
  return (
    <div className="financial-metric-card">
      <span>{label}</span>
      <strong>{formatValue(point?.value, unit)}</strong>
      <small>{point?.period ?? "--"}</small>
      {note ? <em className={`financial-metric-note ${note.tone}`}>{note.text}</em> : null}
    </div>
  );
}

function ChartCard({
  title,
  subtitle,
  children,
  series,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  series: ChartSeries[];
}) {
  return (
    <section className="financial-chart-card">
      <div className="financial-chart-header">
        <div>
          <strong>{title}</strong>
          <span>{subtitle}</span>
        </div>
        <ChartLegend series={series} />
      </div>
      {children}
    </section>
  );
}

function aggregateStatement(statement: FinancialStatement, mode: PeriodMode, completeYears: Set<number>) {
  if (mode === "quarter") return statement;

  const years = [...completeYears].sort((firstYear, secondYear) => firstYear - secondYear);
  const periods = years.map((year) => ({
    key: String(year),
    label: String(year),
    year,
    quarter: 0,
  }));
  const aggregation = statement.type === "BS" ? "last" : "sum";

  return {
    ...statement,
    periods,
    rows: statement.rows.map((row) => {
      const values: Record<string, number | null> = {};

      periods.forEach((period) => {
        const originalPeriods = FULL_YEAR_QUARTERS.map((quarter) =>
          statement.periods.find((item) => item.year === period.year && item.quarter === quarter),
        );
        const quarterValues = originalPeriods.map((item) =>
          item ? row.values[item.key] ?? null : null,
        );
        const hasFullYearValues = quarterValues.every((value) => value !== null && value !== undefined);

        values[period.key] =
          aggregation === "sum"
            ? hasFullYearValues
              ? quarterValues.reduce((total, value) => total + (value ?? 0), 0)
              : null
            : quarterValues[quarterValues.length - 1] ?? null;
      });

      return {
        ...row,
        values,
      };
    }),
  };
}

function normalizeSearchText(value: string | null | undefined) {
  return (value ?? "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d");
}

function isImportantDetailRow(row: FinancialStatement["rows"][number]) {
  const criteria = row.criteria.toLowerCase();
  if (DETAIL_YOY_CRITERIA.has(criteria)) return true;

  const label = normalizeSearchText(`${row.name_vi} ${row.name_en ?? ""}`);
  return label.includes("doanh thu") || label.includes("loi nhuan");
}

function getDetailYoYNote(
  row: FinancialStatement["rows"][number],
  period: FinancialStatement["periods"][number],
  periods: FinancialStatement["periods"],
): MetricNote | undefined {
  if (!isImportantDetailRow(row)) return undefined;

  const value = row.values[period.key];
  if (value === null || value === undefined) return undefined;

  const previousPeriod = periods.find(
    (item) => item.year === period.year - 1 && (period.quarter === 0 || item.quarter === period.quarter),
  );
  if (!previousPeriod) return undefined;

  const previousValue = row.values[previousPeriod.key];
  if (previousValue === null || previousValue === undefined || previousValue === 0) return undefined;

  const change = ((value - previousValue) / Math.abs(previousValue)) * 100;
  const formatted = DECIMAL_FORMATTER.format(Math.abs(change));
  const sign = change > 0 ? "+" : change < 0 ? "-" : "";
  const tone = change > 0 ? "up" : change < 0 ? "down" : "flat";

  return {
    text: `${sign}${formatted}% YoY`,
    tone,
  };
}

function FinancialStatementTable({ statement }: { statement: FinancialStatement }) {
  return (
    <div className="financial-detail-table-wrap">
      <table className="financial-detail-table">
        <thead>
          <tr>
            <th>Tiêu chí</th>
            {statement.periods.map((period) => (
              <th key={period.key}>{period.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {statement.rows.map((row) => (
            <tr className={row.is_total || row.level === 0 ? "financial-detail-total-row" : ""} key={row.key}>
              <td>
                <span
                  className="financial-detail-label"
                  style={{ paddingLeft: `${Math.min(row.level, 4) * 18}px` }}
                  title={row.name_en ?? row.criteria}
                >
                  {row.name_vi}
                </span>
              </td>
              {statement.periods.map((period) => {
                const yoyNote = getDetailYoYNote(row, period, statement.periods);

                return (
                  <td key={`${row.key}-${period.key}`}>
                    <span className="financial-detail-value">{formatDetailValue(row.values[period.key], row.unit)}</span>
                    {yoyNote ? <em className={`financial-detail-yoy ${yoyNote.tone}`}>{yoyNote.text}</em> : null}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FinancialRatioTable({ seriesList, mode }: { seriesList: FinancialSeries[]; mode: PeriodMode }) {
  const rows = getFinancialRatioRows(seriesList, mode);
  const periods = getFinancialRatioPeriods(rows);

  return (
    <div className="financial-ratio-table-wrap">
      <table className="financial-ratio-table">
        <thead>
          <tr>
            <th>Chỉ số</th>
            {periods.map((period) => (
              <th key={period.period}>{period.period}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td>
                <span>{row.label}</span>
                <small>{row.unit || "--"}</small>
              </td>
              {periods.map((period) => {
                const point = row.points.find((item) => item.period === period.period);

                return (
                  <td key={`${row.key}-${period.period}`}>
                    {formatDetailValue(point?.value, row.unit)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {periods.length === 0 ? (
        <div className="financial-ratio-empty">
          <strong>Chưa có dữ liệu chỉ số tài chính</strong>
          <span>Backend chưa trả dữ liệu cho ROE, ROA, P/E, P/B, EPS, BVPS hoặc NIM.</span>
        </div>
      ) : null}
    </div>
  );
}

function FinancialDetailContent({
  activeTab,
  activeStatement,
  financialMetricSeries,
  periodMode,
}: {
  activeTab: DetailTabKey;
  activeStatement: FinancialStatement | null;
  financialMetricSeries: FinancialSeries[];
  periodMode: PeriodMode;
}) {
  if (activeTab === FINANCIAL_RATIO_TAB_KEY) {
    return <FinancialRatioTable seriesList={financialMetricSeries} mode={periodMode} />;
  }

  if (!activeStatement) {
    return (
      <div className="financial-ratio-empty">
        <strong>Chưa có dữ liệu báo cáo</strong>
        <span>Backend chưa trả dữ liệu chi tiết cho loại báo cáo này.</span>
      </div>
    );
  }

  return <FinancialStatementTable statement={activeStatement} />;
}

export function FinancialDashboardPanel({ dashboard, ticker, loading = false }: Props) {
  const [showDetails, setShowDetails] = useState(false);
  const [activeStatementType, setActiveStatementType] = useState("");
  const [periodMode, setPeriodMode] = useState<PeriodMode>("quarter");

  if (!dashboard) {
    return (
      <div className="financial-dashboard-card">
        <div className="financial-dashboard-empty">
          <strong>{loading ? "Đang tải dashboard BCTC" : "Chưa có dữ liệu BCTC"}</strong>
          <span>
            {loading
              ? "Dashboard sẽ tự hiển thị khi backend trả dữ liệu."
              : "Hãy thử mã cổ phiếu khác trong danh sách VN30."}
          </span>
        </div>
      </div>
    );
  }

  const periodAxisLabel = periodMode === "year" ? "Năm" : "Quý";
  const periodText = periodMode === "year" ? "Theo năm" : "Theo quý";
  const rawIncomeSeries = selectSeries(dashboard, [
    { key: "revenue", color: "#2f6ca8" },
    { key: "profit", color: "#0f9f6e" },
  ]);
  const rawCashFlowSeries = selectSeries(dashboard, [
    {
      key: "cf_operating",
      color: "#0f9f6e",
      statementType: "CF",
      criteria: ["cashflow_operating", "net_cash_from_operating_activities", "cf_operating"],
      label: "Dòng tiền kinh doanh",
    },
    {
      key: "cf_investment",
      color: "#d94b4b",
      statementType: "CF",
      criteria: ["cashflow_investing", "net_cash_from_investing_activities", "cf_investment"],
      label: "Dòng tiền đầu tư",
    },
    {
      key: "cf_finance",
      color: "#7a5af8",
      statementType: "CF",
      criteria: ["cashflow_financing", "net_cash_from_financing_activities", "cf_finance"],
      label: "Dòng tiền tài chính",
    },
    {
      key: "net_cf",
      color: "#526171",
      statementType: "CF",
      criteria: ["net_cashflow", "net_increase_decrease_in_cash_and_cash_equivalents", "net_cf"],
      label: "Lưu chuyển tiền thuần",
    },
  ]);
  const rawBalanceSeries = selectSeries(dashboard, [
    { key: "total_assets", color: "#2f6ca8" },
    { key: "liabilities", color: "#d94b4b" },
    { key: "equity", color: "#0f9f6e" },
  ]);
  const rawMarginSeries = selectSeries(dashboard, [{ key: "profit_margin", color: "#a17900" }])[0];
  const rawRevenueSeries =
    rawIncomeSeries.find((item) => item.key === "revenue") ?? dashboard.series.find((item) => item.key === "revenue");
  const rawProfitSeries =
    rawIncomeSeries.find((item) => item.key === "profit") ?? dashboard.series.find((item) => item.key === "profit");
  const rawDetailStatements = dashboard.statements ?? [];
  const financialMetricSeries = dashboard.metric_series ?? [];
  const annualCompleteYears = resolveCompleteYears([rawRevenueSeries, rawProfitSeries], rawDetailStatements);
  const incomeSeries = aggregateChartSeries(rawIncomeSeries, periodMode, "sum", annualCompleteYears);
  const cashFlowSeries = aggregateChartSeries(rawCashFlowSeries, periodMode, "sum", annualCompleteYears);
  const balanceSeries = aggregateChartSeries(rawBalanceSeries, periodMode, "last", annualCompleteYears);
  const revenueSeries = aggregateSeries(rawRevenueSeries, periodMode, "sum", annualCompleteYears);
  const profitSeries = aggregateSeries(rawProfitSeries, periodMode, "sum", annualCompleteYears);
  const marginSeries = buildMarginSeries(rawMarginSeries, rawRevenueSeries, rawProfitSeries, periodMode, annualCompleteYears);
  const operatingCashFlowSeries = cashFlowSeries.find((item) => item.key === "cf_operating");
  const revenueYoY = getYoYNote(revenueSeries);
  const profitYoY = getYoYNote(profitSeries);
  const detailStatements =
    periodMode === "year"
      ? rawDetailStatements.map((statement) => aggregateStatement(statement, periodMode, annualCompleteYears))
      : rawDetailStatements;
  const requestedStatementType = activeStatementType === FINANCIAL_RATIO_TAB_KEY ? "" : activeStatementType;
  const activeStatement =
    detailStatements.find((statement) => statement.type === requestedStatementType) ?? detailStatements[0] ?? null;
  const activeDetailTab =
    activeStatementType === FINANCIAL_RATIO_TAB_KEY ? FINANCIAL_RATIO_TAB_KEY : activeStatement?.type ?? FINANCIAL_RATIO_TAB_KEY;
  const latestDisplayPeriod =
    periodMode === "year" ? getLatestPoint(revenueSeries)?.period ?? null : dashboard.latest_period;
  const dashboardSubtitle = latestDisplayPeriod
    ? periodMode === "year"
      ? `BCTC năm đủ 4 quý đến ${latestDisplayPeriod}`
      : `BCTC cập nhật đến ${latestDisplayPeriod}`
    : "Dashboard BCTC";

  return (
    <div className="financial-dashboard-card">
      <div className="financial-dashboard-header">
        <div>
          <strong>{ticker}</strong>
          <span>{dashboardSubtitle}</span>
        </div>
        <div className="financial-dashboard-actions">
          <div className="financial-period-toggle" role="tablist" aria-label="Chế độ kỳ BCTC">
            <button
              type="button"
              className={periodMode === "quarter" ? "active" : ""}
              aria-selected={periodMode === "quarter"}
              onClick={() => setPeriodMode("quarter")}
            >
              Theo quý
            </button>
            <button
              type="button"
              className={periodMode === "year" ? "active" : ""}
              aria-selected={periodMode === "year"}
              onClick={() => setPeriodMode("year")}
            >
              Theo năm
            </button>
          </div>
          <button
            type="button"
            className="financial-detail-button"
            disabled={detailStatements.length === 0 && financialMetricSeries.length === 0}
            aria-expanded={showDetails}
            onClick={() => setShowDetails((current) => !current)}
          >
            {showDetails ? "Ẩn chi tiết" : "Chi tiết"}
          </button>
        </div>
      </div>

      <div className="financial-metric-grid">
        <MetricCard label="Doanh thu" point={getLatestPoint(revenueSeries)} unit="tỷ đồng" note={revenueYoY} />
        <MetricCard label="Lợi nhuận sau thuế" point={getLatestPoint(profitSeries)} unit="tỷ đồng" note={profitYoY} />
        <MetricCard label="Biên lợi nhuận ròng" point={getLatestPoint(marginSeries)} unit="%" />
        <MetricCard label="Dòng tiền kinh doanh" point={getLatestPoint(operatingCashFlowSeries)} unit="tỷ đồng" />
      </div>

      {showDetails && (activeStatement || financialMetricSeries.length > 0) ? (
        <section className="financial-detail-panel">
          <div className="financial-detail-header">
            <div>
              <strong>Chi tiết BCTC</strong>
              <span>Chọn nhanh 3 loại báo cáo hoặc bộ chỉ số tài chính theo kỳ.</span>
            </div>
            <div className="financial-detail-tabs" role="tablist" aria-label="Loại báo cáo tài chính">
              {detailStatements.map((statement) => (
                <button
                  type="button"
                  className={statement.type === activeDetailTab ? "active" : ""}
                  key={statement.type}
                  onClick={() => setActiveStatementType(statement.type)}
                >
                  {statement.label}
                </button>
              ))}
              <button
                type="button"
                className={activeDetailTab === FINANCIAL_RATIO_TAB_KEY ? "active" : ""}
                onClick={() => setActiveStatementType(FINANCIAL_RATIO_TAB_KEY)}
              >
                Chỉ số tài chính
              </button>
            </div>
          </div>
          <FinancialDetailContent
            activeTab={activeDetailTab}
            activeStatement={activeStatement}
            financialMetricSeries={financialMetricSeries}
            periodMode={periodMode}
          />
        </section>
      ) : null}

      <div className="financial-chart-grid">
        <ChartCard title="Doanh thu & lợi nhuận" subtitle={`${periodText}, đơn vị tỷ đồng`} series={incomeSeries}>
          <BarChart series={incomeSeries} periodLabel={periodAxisLabel} />
        </ChartCard>

        {marginSeries ? (
          <ChartCard title="Biên lợi nhuận ròng" subtitle="Lợi nhuận sau thuế / doanh thu" series={[marginSeries]}>
            <LineChart series={marginSeries} periodLabel={periodAxisLabel} />
          </ChartCard>
        ) : null}

        <ChartCard
          title="Cơ cấu dòng tiền"
          subtitle={`${periodText}; kinh doanh, đầu tư, tài chính và lưu chuyển thuần`}
          series={cashFlowSeries}
        >
          <BarChart series={cashFlowSeries} periodLabel={periodAxisLabel} />
        </ChartCard>

        <ChartCard
          title="Cân đối kế toán"
          subtitle={`${periodText}; tổng tài sản, nợ phải trả và vốn chủ sở hữu`}
          series={balanceSeries}
        >
          <BarChart series={balanceSeries} periodLabel={periodAxisLabel} />
        </ChartCard>
      </div>
    </div>
  );
}
