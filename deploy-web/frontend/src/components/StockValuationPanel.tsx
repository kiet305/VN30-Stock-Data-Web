import { useEffect, useState, type ReactNode } from "react";

import { fetchValuationBacktest } from "../api";
import type { StockInfo, ValuationBacktestPoint } from "../types";

type Props = {
  info: StockInfo | null;
  ticker: string;
  loading?: boolean;
};

type Tone = "up" | "down" | undefined;

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

function formatDecimal(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : DECIMAL_FORMATTER.format(value);
}

function formatChange(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : `${CHANGE_FORMATTER.format(value)}%`;
}

function formatRatio(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : formatChange(value * 100);
}

function formatWeight(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : `${DECIMAL_FORMATTER.format(value * 100)}%`;
}

function formatBillion(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : `${DECIMAL_FORMATTER.format(value)} tỷ`;
}

function toneFromChange(value: number | null | undefined): Tone {
  if (value === null || value === undefined || value === 0) return undefined;
  return value > 0 ? "up" : "down";
}

function toneFromDifference(value: number | null | undefined, benchmark: number | null | undefined): Tone {
  if (value === null || value === undefined || benchmark === null || benchmark === undefined) return undefined;
  return toneFromChange(value - benchmark);
}

function toneFromValuationPremium(value: number | null | undefined): Tone {
  if (value === null || value === undefined || value === 0) return undefined;
  return value < 0 ? "up" : "down";
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function getGaugePosition(upside: number | null | undefined) {
  if (upside === null || upside === undefined) return 50;
  return clamp(((upside + 30) / 60) * 100, 0, 100);
}

function formatDisplayDate(value: string | null | undefined) {
  if (!value) return "--";
  return new Date(value).toLocaleDateString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function getGaugeSignal(upside: number | null | undefined) {
  if (upside === null || upside === undefined) {
    return {
      label: "Chưa đủ dữ liệu",
      detail: "Cần target 12 tháng để xác định thiên hướng",
      tone: undefined,
    };
  }

  if (upside >= 15) {
    return {
      label: "Bullish",
      detail: "Upside hấp dẫn so với thị giá",
      tone: "up" as Tone,
    };
  }

  if (upside <= -10) {
    return {
      label: "Bearish",
      detail: "Target thấp hơn thị giá hiện tại",
      tone: "down" as Tone,
    };
  }

  return {
    label: "Trung lập",
    detail: "Biên an toàn chưa thật sự nổi bật",
    tone: undefined,
  };
}

function MetricValue({ children, tone }: { children: ReactNode; tone?: Tone }) {
  return <strong className={tone ? `metric-value ${tone}` : "metric-value"}>{children}</strong>;
}

function ValuationMetric({
  label,
  value,
  subValue,
  tone,
}: {
  label: string;
  value: string;
  subValue?: string;
  tone?: Tone;
}) {
  return (
    <div className="valuation-metric-card">
      <span>{label}</span>
      <strong className={tone ? `metric-value ${tone}` : "metric-value"}>{value}</strong>
      {subValue ? <small className={tone ? `metric-value ${tone}` : "metric-value"}>{subValue}</small> : null}
    </div>
  );
}

function BullBearGauge({
  upside,
  targetPrice,
  currentPrice,
}: {
  upside: number | null | undefined;
  targetPrice: number | null | undefined;
  currentPrice: number | null | undefined;
}) {
  const position = getGaugePosition(upside);
  const signal = getGaugeSignal(upside);

  return (
    <section className="bull-bear-gauge-card" aria-label="Thang đo xu hướng cổ phiếu">
      <img className="bull-bear-gauge-art" src="/assets/bull-bear-scale.png" alt="" aria-hidden="true" />
      <div className="bull-bear-gauge-content">
        <div className="bull-bear-gauge-header">
          <div>
            <span>Thang đo cổ phiếu</span>
            <strong className={signal.tone ? `metric-value ${signal.tone}` : "metric-value"}>{signal.label}</strong>
          </div>
          <p>{signal.detail}</p>
        </div>

        <div className="bull-bear-track-wrap">
          <div className="bull-bear-track">
            <span className="bull-bear-zone bear">Bear</span>
            <span className="bull-bear-zone neutral">Neutral</span>
            <span className="bull-bear-zone bull">Bull</span>
            <i className="bull-bear-pointer" style={{ left: `${position}%` }} />
          </div>
          <div className="bull-bear-scale-labels">
            <span>-30%</span>
            <span>0%</span>
            <span>+30%</span>
          </div>
        </div>

        <div className="bull-bear-gauge-stats">
          <div>
            <span>Upside 12 tháng</span>
            <strong className={signal.tone ? `metric-value ${signal.tone}` : "metric-value"}>{formatChange(upside)}</strong>
          </div>
          <div>
            <span>Target / thị giá</span>
            <strong>
              {formatPrice(targetPrice)}
              <span className="metric-separator"> / </span>
              {formatPrice(currentPrice)}
            </strong>
          </div>
        </div>
      </div>
    </section>
  );
}

function ValuationBacktestData({ ticker }: { ticker: string }) {
  const [points, setPoints] = useState<ValuationBacktestPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");

    fetchValuationBacktest(ticker, 10)
      .then((payload) => {
        if (!controller.signal.aborted) setPoints(payload.points);
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        setPoints([]);
        setError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [ticker]);

  const collapsedLimit = 3;
  const rows = (expanded ? points : points.slice(-collapsedLimit)).reverse();
  const canToggle = points.length > collapsedLimit;

  return (
    <section className="valuation-backtest-card">
      <div className="stock-info-section-title">
        <div>
          <strong>Dữ liệu backtest định giá</strong>
          <span>Nhiều mốc BCTC quá khứ: target 6T/12T so với giá thực tế sau kỳ</span>
        </div>
        <div className="valuation-backtest-actions">
          <span>{loading ? "Đang tải" : `${points.length} mốc`}</span>
          {canToggle ? (
            <button type="button" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
              {expanded ? "Đóng lại" : "Mở rộng"}
            </button>
          ) : null}
        </div>
      </div>

      {error ? <div className="valuation-backtest-empty">{error}</div> : null}
      {!error && points.length === 0 && !loading ? (
        <div className="valuation-backtest-empty">Chưa có đủ dữ liệu backtest định giá.</div>
      ) : null}

      {points.length > 0 ? (
        <>
          <div className="valuation-backtest-table">
            <div className="valuation-backtest-row head">
              <span>Kỳ</span>
              <span>Giá BCTC</span>
              <span>6T: target / thực tế</span>
              <span>12T: target / thực tế</span>
              <span>Sai lệch 6T / 12T</span>
            </div>
            {rows.map((point) => (
              <div className="valuation-backtest-row" key={`${point.period}-${point.base_date}`}>
                <span>
                  <strong>{point.period}</strong>
                  <small>{formatDisplayDate(point.base_date)}</small>
                </span>
                <span>{formatPrice(point.base_price)}</span>
                <span>
                  {formatChange(point.target_return_6m)}
                  <small>{formatChange(point.actual_return_6m)}</small>
                </span>
                <span>
                  {formatChange(point.target_return_12m)}
                  <small>{formatChange(point.actual_return_12m)}</small>
                </span>
                <span>
                  <b className={toneFromChange(point.target_error_6m) ? `metric-value ${toneFromChange(point.target_error_6m)}` : "metric-value"}>
                    {formatChange(point.target_error_6m)}
                  </b>
                  <small>{formatChange(point.target_error_12m)}</small>
                </span>
              </div>
            ))}
          </div>
        </>
      ) : null}
    </section>
  );
}

export function StockValuationPanel({ info, ticker, loading = false }: Props) {
  const valuation = info?.valuation ?? null;

  if (!valuation) {
    return (
      <div className="stock-valuation-card">
        <div className="stock-valuation-empty">
          <strong>{loading ? "Đang tải định giá" : "Chưa có dữ liệu định giá"}</strong>
          <span>
            {loading
              ? "Kết quả sẽ tự hiển thị khi backend trả dữ liệu."
              : "Cần có giá, EPS/BVPS và BCTC đủ kỳ để tính giá mục tiêu."}
          </span>
        </div>
      </div>
    );
  }

  const industry = valuation.industry_comparison;
  const dcfTone = toneFromChange(valuation.dcf_upside);
  const hasDcf = valuation.dcf_target_price !== null || valuation.dcf_target_price_6m !== null;
  const hasEvEbitda =
    valuation.ev_ebitda !== null ||
    valuation.industry_ev_ebitda !== null ||
    valuation.ev_ebitda_target_price_6m !== null ||
    valuation.ev_ebitda_target_price_12m !== null;

  return (
    <div className="stock-valuation-card">
      <div className="stock-valuation-header">
        <div>
          <strong>{ticker}</strong>
          <span>
            {valuation.latest_period
              ? `Định giá từ BCTC cập nhật đến ${valuation.latest_period}`
              : "Định giá từ BCTC"}
          </span>
        </div>
      </div>

      <div className="valuation-target-grid">
        <ValuationMetric label="Thị giá" value={formatPrice(valuation.current_price ?? info?.close)} />
        <ValuationMetric
          label="Target blended 6 tháng"
          value={formatPrice(valuation.target_price_6m)}
          subValue={formatChange(valuation.upside_6m)}
          tone={toneFromChange(valuation.upside_6m)}
        />
        <ValuationMetric
          label="Target blended 12 tháng"
          value={formatPrice(valuation.target_price_12m)}
          subValue={formatChange(valuation.upside_12m)}
          tone={toneFromChange(valuation.upside_12m)}
        />
      </div>

      <BullBearGauge
        upside={valuation.upside_12m}
        targetPrice={valuation.target_price_12m}
        currentPrice={valuation.current_price ?? info?.close}
      />

      <ValuationBacktestData ticker={ticker} />

      <div className="valuation-detail-grid">
        <section className="valuation-detail-section valuation-detail-section-wide">
          <div className="stock-info-section-title">
            <strong>Cơ cấu phương pháp</strong>
          </div>
          <div className="valuation-method-breakdown">
            <div className="valuation-breakdown-item featured">
              <span>Multiples tổng hợp</span>
              <MetricValue>
                {formatPrice(valuation.multiple_target_price_6m)}
                <span className="metric-separator"> / </span>
                {formatPrice(valuation.multiple_target_price_12m)}
              </MetricValue>
            </div>
            <div className="valuation-breakdown-item">
              <span>P/E-P/B</span>
              <MetricValue>
                {formatPrice(valuation.pe_pb_target_price_6m)}
                <span className="metric-separator"> / </span>
                {formatPrice(valuation.pe_pb_target_price_12m)}
              </MetricValue>
            </div>
            {hasEvEbitda ? (
              <div className="valuation-breakdown-item">
                <span>EV/EBITDA</span>
                <MetricValue tone={toneFromValuationPremium(valuation.ev_ebitda_premium)}>
                  {formatPrice(valuation.ev_ebitda_target_price_6m)}
                  <span className="metric-separator"> / </span>
                  {formatPrice(valuation.ev_ebitda_target_price_12m)}
                </MetricValue>
              </div>
            ) : null}
            {hasDcf ? (
              <div className="valuation-breakdown-item">
                <span>DCF</span>
                <MetricValue tone={dcfTone}>
                  {formatPrice(valuation.dcf_target_price_6m)}
                  <span className="metric-separator"> / </span>
                  {formatPrice(valuation.dcf_target_price)}
                </MetricValue>
              </div>
            ) : null}
            <div className="valuation-breakdown-item weights">
              <span>Trọng số multiples / DCF</span>
              <MetricValue>
                {formatWeight(valuation.multiple_weight)}
                <span className="metric-separator"> / </span>
                {formatWeight(valuation.dcf_weight)}
              </MetricValue>
            </div>
          </div>
        </section>

        {hasDcf ? (
          <section className="valuation-detail-section">
            <div className="stock-info-section-title">
              <strong>Giả định DCF</strong>
            </div>
            <div className="stock-info-list">
              <div className="stock-info-row">
                <span>FCF chuẩn hoá</span>
                <MetricValue>{formatBillion(valuation.normalized_fcf)}</MetricValue>
              </div>
              <div className="stock-info-row">
                <span>Chiết khấu / tăng trưởng dài hạn</span>
                <MetricValue>
                  {formatRatio(valuation.discount_rate)}
                  <span className="metric-separator"> / </span>
                  {formatRatio(valuation.terminal_growth)}
                </MetricValue>
              </div>
              <div className="stock-info-row">
                <span>Upside DCF</span>
                <MetricValue tone={dcfTone}>{formatChange(valuation.dcf_upside)}</MetricValue>
              </div>
            </div>
          </section>
        ) : null}

        {hasEvEbitda ? (
          <section className="valuation-detail-section">
            <div className="stock-info-section-title">
              <strong>EV/EBITDA</strong>
            </div>
            <div className="stock-info-list">
              <div className="stock-info-row">
                <span>EV / EBITDA TTM</span>
                <MetricValue>
                  {formatBillion(valuation.enterprise_value)}
                  <span className="metric-separator"> / </span>
                  {formatBillion(valuation.trailing_ebitda)}
                </MetricValue>
              </div>
              <div className="stock-info-row">
                <span>EV/EBITDA mã / ngành</span>
                <MetricValue tone={toneFromValuationPremium(valuation.ev_ebitda_premium)}>
                  {formatDecimal(valuation.ev_ebitda)}
                  <span className="metric-separator"> / </span>
                  {formatDecimal(valuation.industry_ev_ebitda)}
                </MetricValue>
              </div>
              <div className="stock-info-row">
                <span>Nợ ròng ước tính</span>
                <MetricValue>{formatBillion(valuation.net_debt)}</MetricValue>
              </div>
            </div>
          </section>
        ) : null}

        <section className="valuation-detail-section">
          <div className="stock-info-section-title">
            <strong>Giả định từ BCTC</strong>
          </div>
          <div className="stock-info-list">
            <div className="stock-info-row">
              <span>Tăng trưởng LN 6T</span>
              <MetricValue tone={toneFromChange(valuation.profit_growth_6m)}>
                {formatRatio(valuation.profit_growth_6m)}
              </MetricValue>
            </div>
            <div className="stock-info-row">
              <span>Tăng trưởng LN 12T</span>
              <MetricValue tone={toneFromChange(valuation.profit_growth_12m)}>
                {formatRatio(valuation.profit_growth_12m)}
              </MetricValue>
            </div>
            <div className="stock-info-row">
              <span>Tăng trưởng vốn chủ 12T</span>
              <MetricValue tone={toneFromChange(valuation.equity_growth_12m)}>
                {formatRatio(valuation.equity_growth_12m)}
              </MetricValue>
            </div>
          </div>
        </section>

        <section className="valuation-detail-section">
          <div className="stock-info-section-title">
            <strong>So sánh ngành</strong>
          </div>
          <div className="stock-info-list">
            <div className="stock-info-row">
              <span>Ngành / số mã so sánh</span>
              <MetricValue>
                <span className="valuation-method">
                  {industry?.industry ?? "--"}
                  {industry?.subindustry ? ` / ${industry.subindustry}` : ""}
                  {industry ? ` · ${industry.peer_count} mã` : ""}
                </span>
              </MetricValue>
            </div>
            <div className="stock-info-row">
              <span>P/E mã / ngành</span>
              <MetricValue tone={toneFromValuationPremium(industry?.pe_premium)}>
                {formatDecimal(industry?.pe)}
                <span className="metric-separator"> / </span>
                {formatDecimal(industry?.industry_pe)}
              </MetricValue>
            </div>
            <div className="stock-info-row">
              <span>P/B mã / ngành</span>
              <MetricValue tone={toneFromValuationPremium(industry?.pb_premium)}>
                {formatDecimal(industry?.pb)}
                <span className="metric-separator"> / </span>
                {formatDecimal(industry?.industry_pb)}
              </MetricValue>
            </div>
            <div className="stock-info-row">
              <span>ROE mã / ngành</span>
              <MetricValue tone={toneFromDifference(industry?.roe, industry?.industry_roe)}>
                {formatRatio(industry?.roe)}
                <span className="metric-separator"> / </span>
                {formatRatio(industry?.industry_roe)}
              </MetricValue>
            </div>
            <div className="stock-info-row">
              <span>ROA mã / ngành</span>
              <MetricValue tone={toneFromDifference(industry?.roa, industry?.industry_roa)}>
                {formatRatio(industry?.roa)}
                <span className="metric-separator"> / </span>
                {formatRatio(industry?.industry_roa)}
              </MetricValue>
            </div>
            <div className="stock-info-row">
              <span>ROS mã / ngành</span>
              <MetricValue tone={toneFromDifference(industry?.ros, industry?.industry_ros)}>
                {formatRatio(industry?.ros)}
                <span className="metric-separator"> / </span>
                {formatRatio(industry?.industry_ros)}
              </MetricValue>
            </div>
          </div>
        </section>
      </div>

      <div className="valuation-method-note">{valuation.method}</div>
    </div>
  );
}
