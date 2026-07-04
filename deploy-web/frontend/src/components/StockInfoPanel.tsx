import { useEffect, useMemo, useState } from "react";

import type { StockInfo } from "../types";

type Props = {
  info: StockInfo | null;
  ticker: string;
  loading?: boolean;
};

type InfoRow = {
  label: string;
  value: string;
  tone?: "reference" | "up" | "down";
  extraValue?: string;
  extraTone?: "up" | "down";
};

type RawShareholder = {
  name: string;
  ownership_percentage: number;
  ownership_quantity?: number | null;
};

type RawCompanyShareholders = {
  ticker: string;
  shareholders: RawShareholder[];
};

const DATA_URL = "/assets/vn30_shareholders.json";
const MIN_MAJOR_SHAREHOLDER_PERCENT = 0.1;
const MOJIBAKE_PATTERN = /[ÃÄÂÆ]|á[º»]/;

const PRICE_FORMATTER = new Intl.NumberFormat("vi-VN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

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

function repairMojibake(value: string) {
  if (!MOJIBAKE_PATTERN.test(value)) return value;

  try {
    const bytes = Uint8Array.from(value, (char) => char.charCodeAt(0));
    const decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    return decoded.includes("�") ? value : decoded;
  } catch {
    return value;
  }
}

function formatPrice(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : PRICE_FORMATTER.format(value);
}

function formatNumber(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : NUMBER_FORMATTER.format(value);
}

function formatDecimal(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : DECIMAL_FORMATTER.format(value);
}

function formatMarketCap(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : `${DECIMAL_FORMATTER.format(value)} tỷ`;
}

function formatChange(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : `${CHANGE_FORMATTER.format(value)}%`;
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined) return "--";
  return `${value.toLocaleString("vi-VN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: value % 1 === 0 ? 0 : 1,
  })}%`;
}

function formatOwnershipPercent(value: number | null | undefined) {
  if (value === null || value === undefined) return "--";
  const percentage = value * 100;
  return `${percentage.toLocaleString("vi-VN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: percentage % 1 === 0 ? 0 : 1,
  })}%`;
}

function formatShareQuantity(value: number | null | undefined) {
  if (value === null || value === undefined) return "";
  return `${NUMBER_FORMATTER.format(value)} cp`;
}

function formatShareholderQuantity(value: number | null | undefined) {
  if (value === null || value === undefined) return "";
  return formatShareQuantity(value * 1_000_000);
}

function normalizePosition(value: string | null | undefined) {
  return (value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function normalizePersonKey(value: string | null | undefined) {
  return normalizePosition(repairMojibake(value ?? ""))
    .replace(/\s+/g, " ")
    .trim();
}

function getPositionRank(position: string | null | undefined) {
  const normalized = normalizePosition(position);
  if (normalized.includes("pho chu tich") || normalized.includes("vice chairman")) return 2;
  if (normalized.includes("chu tich") || normalized.includes("chairman")) return 1;
  if (normalized.includes("pho tong giam doc") || normalized.includes("deputy ceo")) return 4;
  if (normalized.includes("tong giam doc") || normalized.includes("ceo")) return 3;
  if (normalized.includes("giam doc") || normalized.includes("director")) return 5;
  if (normalized.includes("hoi dong quan tri") || normalized.includes("hdqt") || normalized.includes("board")) return 6;
  if (normalized.includes("ban kiem soat") || normalized.includes("kiem soat") || normalized.includes("bks")) return 7;
  if (normalized.includes("ke toan truong") || normalized.includes("chief accountant") || normalized.includes("cfo")) return 8;
  return 99;
}

function formatDisplayDate(value: string | null | undefined) {
  if (!value) return "--";
  const [year, month, day] = value.split("-");
  if (!year || !month || !day) return value;
  return `${day}/${month}/${year}`;
}

function toneAgainstReference(value: number | null | undefined, reference: number | null | undefined): InfoRow["tone"] {
  if (value === null || value === undefined || reference === null || reference === undefined || value === reference) {
    return undefined;
  }

  return value > reference ? "up" : "down";
}

function toneFromChange(value: number | null | undefined): "up" | "down" | undefined {
  if (value === null || value === undefined || value === 0) return undefined;
  return value > 0 ? "up" : "down";
}

function renderRows(rows: InfoRow[]) {
  return rows.map((row) => (
    <div className="stock-info-row" key={row.label}>
      <span>{row.label}</span>
      <strong className={row.tone ? `metric-value ${row.tone}` : "metric-value"}>
        {row.value}
        {row.extraValue ? (
          <>
            <span className="metric-separator"> - </span>
            <span className={row.extraTone ? `metric-value ${row.extraTone}` : "metric-value"}>{row.extraValue}</span>
          </>
        ) : null}
      </strong>
    </div>
  ));
}

function getTradingRows(info: StockInfo | null): InfoRow[] {
  return [
    {
      label: "Tham chiếu",
      value: formatPrice(info?.reference),
      tone: "reference",
    },
    {
      label: "Mở cửa",
      value: formatPrice(info?.open),
      tone: toneAgainstReference(info?.open, info?.reference),
    },
    {
      label: "Đóng cửa",
      value: formatPrice(info?.close),
      tone: toneAgainstReference(info?.close, info?.reference),
    },
    {
      label: "Thấp - Cao",
      value: formatPrice(info?.low),
      tone: "down",
      extraValue: formatPrice(info?.high),
      extraTone: "up",
    },
    {
      label: "Khối lượng",
      value: formatNumber(info?.volume),
    },
    {
      label: "KLTB 10 ngày",
      value: formatNumber(info?.average_volume_10d),
    },
    {
      label: "Beta (VNINDEX)",
      value: formatDecimal(info?.beta),
    },
    {
      label: "Biến động 1 ngày",
      value: formatChange(info?.change_1d),
      tone: toneFromChange(info?.change_1d),
    },
    {
      label: "Biến động 3 ngày",
      value: formatChange(info?.change_3d),
      tone: toneFromChange(info?.change_3d),
    },
    {
      label: "Biến động 1 tuần",
      value: formatChange(info?.change_1w),
      tone: toneFromChange(info?.change_1w),
    },
    {
      label: "Biến động 1 tháng",
      value: formatChange(info?.change_1m),
      tone: toneFromChange(info?.change_1m),
    },
    {
      label: "Biến động 3 tháng",
      value: formatChange(info?.change_3m),
      tone: toneFromChange(info?.change_3m),
    },
    {
      label: "Biến động 6 tháng",
      value: formatChange(info?.change_6m),
      tone: toneFromChange(info?.change_6m),
    },
    {
      label: "Biến động 1 năm",
      value: formatChange(info?.change_1y),
      tone: toneFromChange(info?.change_1y),
    },
  ];
}

function getBasicMetricRows(info: StockInfo | null): InfoRow[] {
  return [
    {
      label: "Thị giá",
      value: formatPrice(info?.close),
      tone: toneAgainstReference(info?.close, info?.reference),
    },
    {
      label: "Thị giá vốn",
      value: formatMarketCap(info?.market_cap),
    },
    {
      label: "Tỉ lệ sở hữu nước ngoài",
      value: formatOwnershipPercent(info?.overview?.foreign_percentage),
    },
    {
      label: "Tỉ lệ free float",
      value: formatOwnershipPercent(info?.overview?.free_float_percentage),
    },
    {
      label: "P/E",
      value: formatDecimal(info?.pe),
    },
    {
      label: "P/B",
      value: formatDecimal(info?.pb),
    },
    {
      label: "EPS",
      value: formatNumber(info?.eps),
    },
    {
      label: "BVPS",
      value: formatNumber(info?.bvps),
    },
    {
      label: "Số lượng CPLH",
      value: formatNumber(info?.issue_share ?? info?.overview?.issue_share),
    },
  ];
}

function useShareholders(ticker: string) {
  const [shareholders, setShareholders] = useState<RawShareholder[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");

    fetch(DATA_URL, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("Không tải được dữ liệu cổ đông");
        return response.json() as Promise<RawCompanyShareholders[]>;
      })
      .then((payload) => {
        const selected = payload.find((item) => item.ticker.trim().toUpperCase() === ticker.toUpperCase());
        const rows = (selected?.shareholders ?? [])
          .map((shareholder) => ({
            name: repairMojibake(shareholder.name).replace(/\s+/g, " ").trim(),
            ownership_percentage: Number(shareholder.ownership_percentage),
            ownership_quantity:
              shareholder.ownership_quantity === null || shareholder.ownership_quantity === undefined
                ? null
                : Number(shareholder.ownership_quantity),
          }))
          .filter((shareholder) => shareholder.name && Number.isFinite(shareholder.ownership_percentage))
          .sort((first, second) => second.ownership_percentage - first.ownership_percentage);

        setShareholders(rows);
        setLoading(false);
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        setShareholders([]);
        setError(err.message);
        setLoading(false);
      });

    return () => controller.abort();
  }, [ticker]);

  return { shareholders, loading, error };
}

export function TradingSummaryPanel({ info, loading = false }: { info: StockInfo | null; loading?: boolean }) {
  return (
    <section className="stock-info-section trading-section price-movement-trading-card">
      <div className="stock-info-section-title">
        <div className="trading-title-copy">
          <strong>Thông tin giao dịch</strong>
          <span>{info?.date ? `Cập nhật ${formatDisplayDate(info.date)}` : loading ? "Đang tải" : "Chưa có dữ liệu"}</span>
        </div>
      </div>
      <div className="stock-info-list">{renderRows(getTradingRows(info))}</div>
    </section>
  );
}

export function BasicMetricsPanel({ info }: { info: StockInfo | null }) {
  return (
    <section className="stock-info-section valuation-section">
      <div className="stock-info-section-title">
        <strong>Các chỉ số</strong>
        <span>{info?.date ? `Cập nhật ${formatDisplayDate(info.date)}` : "Dữ liệu cơ bản"}</span>
      </div>
      <div className="stock-info-list">{renderRows(getBasicMetricRows(info))}</div>
    </section>
  );
}

export function StockInfoPanel({ info, ticker, loading = false }: Props) {
  const overview = info?.overview;

  return (
    <div className="stock-info-card">
      <div className="stock-info-header">
        <div>
          <strong>{ticker}</strong>
          <span>{loading ? "Đang tải thông tin chung" : overview?.name ?? "Lịch sử và các chỉ số"}</span>
        </div>
      </div>

      <div className="stock-general-layout">
        <section className="stock-info-section company-history-section">
          <div className="stock-info-section-title">
            <strong>Lịch sử</strong>
            <span>Hồ sơ doanh nghiệp</span>
          </div>
          <div className="company-history-content">
            {overview?.company_profile || "Chưa có company profile cho mã này."}
          </div>
        </section>

        <BasicMetricsPanel info={info} />
      </div>
    </div>
  );
}

export function ShareholdersOfficersPanel({ info, ticker, loading = false }: Props) {
  const { shareholders: fallbackShareholders, loading: shareholdersLoading, error: shareholdersError } = useShareholders(ticker);
  const officers = useMemo(() => {
    const deduped = new Map<string, NonNullable<StockInfo["officers"]>[number]>();

    (info?.officers ?? []).forEach((officer) => {
      const nameKey = normalizePersonKey(officer.name);
      if (!nameKey) return;

      const current = deduped.get(nameKey);
      if (!current) {
        deduped.set(nameKey, officer);
        return;
      }

      const currentScore =
        (current.ownership_quantity == null ? 0 : 4) +
        (current.ownership_percentage == null ? 0 : 2) +
        (current.position ? 1 : 0);
      const nextScore =
        (officer.ownership_quantity == null ? 0 : 4) +
        (officer.ownership_percentage == null ? 0 : 2) +
        (officer.position ? 1 : 0);

      deduped.set(nameKey, nextScore >= currentScore ? officer : current);
    });

    return [...deduped.values()].sort((first, second) => {
        const rankDiff = getPositionRank(first.position) - getPositionRank(second.position);
        if (rankDiff !== 0) return rankDiff;
        const positionDiff = (first.position ?? "").localeCompare(second.position ?? "", "vi");
        if (positionDiff !== 0) return positionDiff;
        return (first.name ?? "").localeCompare(second.name ?? "", "vi");
      });
    },
    [info?.officers],
  );
  const shareholders = useMemo(() => {
    const rows = new Map<string, RawShareholder>();
    const hasBackendShareholders = (info?.shareholders ?? []).length > 0;
    const sourceShareholders =
      hasBackendShareholders
        ? (info?.shareholders ?? []).map((shareholder) => ({
            name: repairMojibake(shareholder.name ?? "").replace(/\s+/g, " ").trim(),
            ownership_percentage:
              shareholder.ownership_percentage === null || shareholder.ownership_percentage === undefined
                ? NaN
                : shareholder.ownership_percentage * 100,
            ownership_quantity: shareholder.ownership_quantity,
          }))
        : fallbackShareholders;

    sourceShareholders.forEach((shareholder) => {
      const key = normalizePersonKey(shareholder.name);
      if (!key || !Number.isFinite(shareholder.ownership_percentage)) return;
      if (shareholder.ownership_percentage < MIN_MAJOR_SHAREHOLDER_PERCENT) return;
      const current = rows.get(key);
      if (
        !current ||
        (current.ownership_quantity == null && shareholder.ownership_quantity != null) ||
        Number(shareholder.ownership_percentage) > Number(current.ownership_percentage)
      ) {
        rows.set(key, shareholder);
      }
    });

    officers.forEach((officer) => {
      const key = normalizePersonKey(officer.name);
      if (!key || officer.ownership_percentage == null || !Number.isFinite(officer.ownership_percentage)) return;
      const officerOwnershipPercent = officer.ownership_percentage * 100;
      if (officerOwnershipPercent < MIN_MAJOR_SHAREHOLDER_PERCENT) return;
      const current = rows.get(key);
      if (current) {
        rows.set(key, {
          ...current,
          ownership_percentage:
            current.ownership_percentage ?? officerOwnershipPercent,
          ownership_quantity:
            current.ownership_quantity == null && officer.ownership_quantity != null
              ? officer.ownership_quantity / 1_000_000
              : current.ownership_quantity,
        });
        return;
      }

      rows.set(key, {
        name: repairMojibake(officer.name ?? "").replace(/\s+/g, " ").trim(),
        ownership_percentage: officerOwnershipPercent,
        ownership_quantity:
          officer.ownership_quantity == null ? null : officer.ownership_quantity / 1_000_000,
      });
    });

    return [...rows.values()].sort(
      (first, second) => Number(second.ownership_percentage) - Number(first.ownership_percentage),
    );
  }, [fallbackShareholders, info?.shareholders, officers]);

  return (
    <div className="stock-info-card">
      <div className="stock-info-header">
        <div>
          <strong>{ticker}</strong>
          <span>{loading ? "Đang tải cổ đông và lãnh đạo" : "Danh sách cổ đông lớn và ban lãnh đạo"}</span>
        </div>
      </div>

      <div className="shareholders-officers-layout">
        <section className="stock-info-section shareholders-section">
          <div className="stock-info-section-title">
            <strong>Cổ đông lớn</strong>
            <span>{shareholders.length > 0 ? `${shareholders.length.toLocaleString("vi-VN")} cổ đông` : ""}</span>
          </div>
          {shareholders.length > 0 ? (
            <div className="shareholder-list">
              <div className="shareholder-list-header">
                <span>Họ tên</span>
                <span>Cổ phần sở hữu</span>
              </div>
              {shareholders.map((shareholder) => (
                <div className="shareholder-row" key={`${shareholder.name}-${shareholder.ownership_percentage}`}>
                  <span>{shareholder.name}</span>
                  <em>
                    <strong>{formatPercent(shareholder.ownership_percentage)}</strong>
                    {formatShareholderQuantity(shareholder.ownership_quantity) ? (
                      <span>{formatShareholderQuantity(shareholder.ownership_quantity)}</span>
                    ) : null}
                  </em>
                </div>
              ))}
            </div>
          ) : (
            <div className="shareholder-empty">
              {shareholdersLoading
                ? "Đang tải dữ liệu cổ đông..."
                : shareholdersError || `Chưa có dữ liệu cổ đông cho ${ticker}.`}
            </div>
          )}
        </section>

        <section className="stock-info-section officers-section">
          <div className="stock-info-section-title">
            <strong>Lãnh đạo</strong>
            <span>{officers.length > 0 ? `${officers.length.toLocaleString("vi-VN")} người` : ""}</span>
          </div>
          {officers.length > 0 ? (
            <div className="officer-list">
              <div className="officer-list-header">
                <span>Họ tên / Chức vụ</span>
                <span>Cổ phần sở hữu</span>
              </div>
              {officers.map((officer, index) => (
                <div className="officer-row" key={`${officer.name ?? "officer"}-${officer.position ?? index}`}>
                  <div>
                    <strong>{officer.name ?? "--"}</strong>
                    <span>{officer.position ?? "--"}</span>
                  </div>
                  <em>
                    <strong>{formatOwnershipPercent(officer.ownership_percentage)}</strong>
                    {formatShareQuantity(officer.ownership_quantity) ? (
                      <span>{formatShareQuantity(officer.ownership_quantity)}</span>
                    ) : null}
                  </em>
                </div>
              ))}
            </div>
          ) : (
            <div className="shareholder-empty">
              {loading ? "Đang tải dữ liệu lãnh đạo..." : `Chưa có dữ liệu lãnh đạo cho ${ticker}.`}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
