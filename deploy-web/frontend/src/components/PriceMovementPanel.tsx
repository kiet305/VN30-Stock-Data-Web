import { CandlestickChart } from "./CandlestickChart";
import { TradingSummaryPanel } from "./StockInfoPanel";
import type { Candle, ChartAnnotation, StockInfo } from "../types";

type Props = {
  annotations?: ChartAnnotation[];
  candles: Candle[];
  info: StockInfo | null;
  loading?: boolean;
  showTradingSummary?: boolean;
  ticker: string;
};

export function PriceMovementPanel({
  annotations = [],
  candles,
  info,
  loading = false,
  showTradingSummary = true,
  ticker,
}: Props) {
  return (
    <div className={showTradingSummary ? "price-movement-panel" : "price-movement-panel chart-only"}>
      <div className="price-movement-chart">
        <CandlestickChart annotations={annotations} candles={candles} ticker={ticker} loading={loading} />
      </div>
      {showTradingSummary ? <TradingSummaryPanel info={info} loading={loading} /> : null}
    </div>
  );
}
