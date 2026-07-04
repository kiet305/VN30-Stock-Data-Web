import { useEffect, useMemo, useState, type CSSProperties, type FormEvent, type ReactNode } from "react";

import { fetchAnalysisRunStatus, fetchLlmConfig, startAnalysisReportRun, updateLlmConfig } from "../api";
import type {
  AnalysisReportSection,
  AnalysisReportsResponse,
  AnalysisRunStatusResponse,
  LlmConfigResponse,
} from "../types";

type Props = {
  reports: AnalysisReportsResponse | null;
  ticker: string;
  loading?: boolean;
  error?: string;
  onRefresh?: () => void;
};

const REPORT_COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000;

function formatDateTime(value: string | null | undefined) {
  if (!value) return "--";
  return new Date(value).toLocaleString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return "--";
  return new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(value);
}

function getFileName(path: string) {
  return path.split(/[\\/]/).pop() ?? path;
}

function getRunStorageKey(ticker: string) {
  return `analysis-report-run-v3:${ticker.trim().toUpperCase()}`;
}

function formatRemainingCooldown(ms: number) {
  if (ms <= 0) return "";
  const days = Math.floor(ms / (24 * 60 * 60 * 1000));
  const hours = Math.ceil((ms % (24 * 60 * 60 * 1000)) / (60 * 60 * 1000));
  if (days <= 0) return `${hours} giờ`;
  return `${days} ngày ${hours} giờ`;
}

function stripReportMarkup(content: string) {
  return content
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

function stripMarkdownTokens(content: string) {
  return stripReportMarkup(content)
    .replace(/!\[[^\]]*]\([^)]+\)/g, " ")
    .replace(/\[([^\]]+)]\([^)]+\)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^\s*[-*]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/\|/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function getReportPreview(content: string) {
  return stripMarkdownTokens(content)
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#") && !line.startsWith("|") && !/^[-*:]{3,}$/.test(line))
    .slice(0, 2)
    .join(" ");
}

function getSummarySentences(content: string, limit = 3) {
  const plainText = stripMarkdownTokens(content);
  return plainText
    .split(/(?<=[.!?。])\s+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean)
    .slice(0, limit);
}

function getSectionPriority(section: AnalysisReportSection) {
  const priorities: Record<string, number> = {
    research: 0,
    market: 1,
    sentiment: 2,
    news: 3,
    fundamentals: 4,
  };
  return priorities[section.key] ?? 10;
}

function renderInline(text: string): ReactNode[] {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\(https?:\/\/[^)]+\))/g);

  return parts.map((part, index) => {
    if (!part) return null;

    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }

    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{renderInline(part.slice(2, -2))}</strong>;
    }

    const linkMatch = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/);
    if (linkMatch) {
      return (
        <a key={index} href={linkMatch[2]} target="_blank" rel="noreferrer">
          {linkMatch[1]}
        </a>
      );
    }

    return part;
  });
}

function parseTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isTableSeparator(line: string) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function parseInlineStyle(value: string | null): CSSProperties {
  if (!value) return {};

  const allowed = new Set([
    "background",
    "border-radius",
    "color",
    "height",
    "min-width",
    "overflow",
    "width",
  ]);
  const style: Record<string, string> = {};

  value.split(";").forEach((declaration) => {
    const [rawName, ...rawValue] = declaration.split(":");
    const name = rawName?.trim().toLowerCase();
    const propertyValue = rawValue.join(":").trim();
    if (!name || !propertyValue || !allowed.has(name)) return;

    const reactName = name.replace(/-([a-z])/g, (_, letter: string) => letter.toUpperCase());
    style[reactName] = propertyValue;
  });

  return style as CSSProperties;
}

function normalizeReportLabel(value: string | null | undefined) {
  return (value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function createTableCell(doc: Document, tagName: "td" | "th", text: string) {
  const cell = doc.createElement(tagName);
  cell.textContent = text;
  return cell;
}

function replaceRowCells(row: HTMLTableRowElement, cells: Array<{ tag: "td" | "th"; text: string }>) {
  while (row.firstChild) {
    row.removeChild(row.firstChild);
  }

  cells.forEach((cell) => row.appendChild(createTableCell(row.ownerDocument, cell.tag, cell.text)));
}

function getSignalDescription(rating: string) {
  const normalized = normalizeReportLabel(rating);

  if (normalized.includes("strong bull")) return "T\u00edn hi\u1ec7u thu\u1eadn l\u1ee3i chi\u1ebfm \u01b0u th\u1ebf r\u00f5 r\u00e0ng.";
  if (normalized.includes("slightly bull")) return "T\u00edn hi\u1ec7u t\u00edch c\u1ef1c nh\u1ec9nh h\u01a1n, c\u1ea7n x\u00e1c nh\u1eadn th\u00eam.";
  if (normalized.includes("strong bear")) return "T\u00edn hi\u1ec7u b\u1ea5t l\u1ee3i chi\u1ebfm \u01b0u th\u1ebf r\u00f5 r\u00e0ng.";
  if (normalized.includes("slightly bear")) return "R\u1ee7i ro nh\u1ec9nh h\u01a1n c\u01a1 h\u1ed9i, n\u00ean th\u1eadn tr\u1ecdng.";
  if (normalized.includes("neutral")) return "T\u00edn hi\u1ec7u hai chi\u1ec1u c\u00f2n c\u00e2n b\u1eb1ng ho\u1eb7c ch\u01b0a \u0111\u1ee7 m\u1ea1nh.";

  return "T\u00edn hi\u1ec7u c\u1ea7n \u0111\u01b0\u1ee3c \u0111\u1ed1i chi\u1ebfu th\u00eam t\u1eeb c\u00e1c ngu\u1ed3n ph\u00e2n t\u00edch.";
}

function getDirectTableRows(section: HTMLTableSectionElement) {
  return Array.from(section.children).filter(
    (child): child is HTMLTableRowElement => child.tagName.toLowerCase() === "tr",
  );
}

function getConclusionValues(doc: Document) {
  const tables = Array.from(doc.querySelectorAll("table"));
  const conclusionTable = tables.find((table) =>
    normalizeReportLabel(table.querySelector("caption")?.textContent).includes("ket luan tong quan"),
  );
  const values = { rating: "", explanation: "" };

  if (!conclusionTable) return values;

  Array.from(conclusionTable.querySelectorAll("tr")).forEach((row) => {
    const label = normalizeReportLabel(row.children[0]?.textContent);
    const value = row.children[1]?.textContent?.trim() ?? "";

    if (label.includes("muc do tong")) values.rating = value;
    if (label.includes("dien giai")) values.explanation = value;
    if (label.includes("score")) row.remove();
  });

  return values;
}

function normalizeLegacyDashboardTables(doc: Document) {
  const tables = Array.from(doc.querySelectorAll("table"));
  const signalTable = tables.find((table) =>
    normalizeReportLabel(table.querySelector("caption")?.textContent).includes("bang tin hieu tong hop"),
  );
  const conclusion = getConclusionValues(doc);

  if (!signalTable) return;

  const headerText = normalizeReportLabel(signalTable.querySelector("thead")?.textContent);
  const hasLegacyColumns =
    headerText.includes("score") || headerText.includes("truc quan") || headerText.includes("report rieng");

  let thead = signalTable.querySelector("thead");
  if (!thead) {
    thead = doc.createElement("thead");
    signalTable.insertBefore(thead, signalTable.firstChild);
  }

  let headerRow = thead.querySelector("tr");
  if (!headerRow) {
    headerRow = doc.createElement("tr");
    thead.appendChild(headerRow);
  }

  replaceRowCells(headerRow, [
    { tag: "th", text: "Agent" },
    { tag: "th", text: "Nghi\u00eang v\u1ec1" },
    { tag: "th", text: "T\u00edn hi\u1ec7u t\u1ed5ng h\u1ee3p" },
  ]);

  let tbody = signalTable.querySelector("tbody");
  if (!tbody) {
    tbody = doc.createElement("tbody");
    signalTable.appendChild(tbody);
  }

  const rows = getDirectTableRows(tbody);
  if (hasLegacyColumns) {
    rows.forEach((row) => {
      const agent = row.children[0]?.textContent?.trim() ?? "";
      const rating = row.children[1]?.textContent?.trim() ?? "";
      replaceRowCells(row, [
        { tag: "td", text: agent },
        { tag: "td", text: rating },
        { tag: "td", text: getSignalDescription(rating) },
      ]);
    });
  }

  const hasAggregateRow = getDirectTableRows(tbody).some((row) =>
    normalizeReportLabel(row.children[0]?.textContent).includes("tong hop"),
  );

  if (!hasAggregateRow && conclusion.rating) {
    const aggregateRow = doc.createElement("tr");
    replaceRowCells(aggregateRow, [
      { tag: "td", text: "T\u1ed5ng h\u1ee3p" },
      { tag: "td", text: conclusion.rating },
      { tag: "td", text: conclusion.explanation || getSignalDescription(conclusion.rating) },
    ]);
    tbody.appendChild(aggregateRow);
  }
}

function renderAllowedHtmlNode(node: ChildNode, key: string): ReactNode {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.textContent;
  }

  if (node.nodeType !== Node.ELEMENT_NODE) {
    return null;
  }

  const element = node as HTMLElement;
  const tagName = element.tagName.toLowerCase();
  const children = Array.from(element.childNodes).map((child, index) =>
    renderAllowedHtmlNode(child, `${key}-${index}`),
  );

  if (tagName === "a") {
    const href = element.getAttribute("href") ?? "";
    const safeHref = href.startsWith("#") || href.startsWith("http://") || href.startsWith("https://") ? href : "#";
    return (
      <a key={key} href={safeHref} target={safeHref.startsWith("#") ? undefined : "_blank"} rel="noreferrer">
        {children}
      </a>
    );
  }

  const className = element.getAttribute("class") ?? undefined;
  const id = element.getAttribute("id") ?? undefined;
  const style = parseInlineStyle(element.getAttribute("style"));
  const commonProps = { key, className, id, style };

  switch (tagName) {
    case "section":
      return <section {...commonProps}>{children}</section>;
    case "h1":
      return <h3 {...commonProps}>{children}</h3>;
    case "h2":
      return <h3 {...commonProps}>{children}</h3>;
    case "h3":
      return <h4 {...commonProps}>{children}</h4>;
    case "p":
      return <p {...commonProps}>{children}</p>;
    case "strong":
      return <strong key={key}>{children}</strong>;
    case "table":
      return (
        <div className="analysis-markdown-table-wrap analysis-html-table-wrap" key={key}>
          <table>{children}</table>
        </div>
      );
    case "caption":
      return <caption key={key}>{children}</caption>;
    case "thead":
      return <thead key={key}>{children}</thead>;
    case "tbody":
      return <tbody key={key}>{children}</tbody>;
    case "tr":
      return <tr key={key}>{children}</tr>;
    case "th":
      return <th key={key}>{children}</th>;
    case "td":
      return <td key={key}>{children}</td>;
    case "code":
      return <code key={key}>{children}</code>;
    case "div":
      return <div {...commonProps}>{children}</div>;
    default:
      return <span key={key}>{children}</span>;
  }
}

function renderHtmlFragment(fragment: string, keyPrefix: string) {
  if (typeof DOMParser === "undefined") return renderMarkdown(fragment);

  const doc = new DOMParser().parseFromString(`<body>${fragment}</body>`, "text/html");
  normalizeLegacyDashboardTables(doc);
  return Array.from(doc.body.childNodes).map((node, index) =>
    renderAllowedHtmlNode(node, `${keyPrefix}-${index}`),
  );
}

function renderReportSections(content: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const sectionRegex = /<section\s+id="([^"]+)"\s*>\s*<h2>(.*?)<\/h2>\s*([\s\S]*?)<\/section>/gi;
  let cursor = 0;
  let match: RegExpExecArray | null;
  let sectionIndex = 0;

  while ((match = sectionRegex.exec(content)) !== null) {
    const before = content.slice(cursor, match.index).trim();
    if (before) {
      nodes.push(...renderMarkdown(before));
    }

    const [, id, title, body] = match;
    nodes.push(
      <section className="analysis-detail-section" id={id} key={`${keyPrefix}-section-${sectionIndex}`}>
        <h3>{title}</h3>
        {renderMarkdown(body.trim())}
      </section>,
    );
    cursor = sectionRegex.lastIndex;
    sectionIndex += 1;
  }

  const after = content.slice(cursor).trim();
  if (after) {
    nodes.push(...renderMarkdown(after));
  }

  return nodes;
}

function renderAgentReportText(content: string) {
  const normalized = content.replace(/>\s+</g, ">\n<");
  const dashboardMatch = normalized.match(/<section\s+class="report-dashboard"\s*>[\s\S]*?<\/section>/i);

  if (!dashboardMatch || dashboardMatch.index === undefined) {
    return renderReportSections(normalized, "agent-report");
  }

  const before = normalized.slice(0, dashboardMatch.index).trim();
  const dashboard = dashboardMatch[0];
  const after = normalized.slice(dashboardMatch.index + dashboard.length).trim();

  return [
    ...renderMarkdown(before),
    ...renderHtmlFragment(dashboard, "dashboard"),
    ...renderReportSections(after, "agent-report-after-dashboard"),
  ];
}

function getAgentTone(section: AnalysisReportSection) {
  const normalized = normalizeReportLabel(`${section.title} ${section.agent} ${section.content.slice(0, 1200)}`);
  if (normalized.includes("bear") || normalized.includes("rui ro") || normalized.includes("tieu cuc")) return "bear";
  if (normalized.includes("bull") || normalized.includes("tich cuc") || normalized.includes("co hoi")) return "bull";
  return "neutral";
}

function getWorkflowStatus(index: number, activeStep: number, activated: boolean) {
  if (!activated) return "waiting";
  if (index < activeStep) return "done";
  if (index === activeStep) return "running";
  return "waiting";
}

function getRunStepTone(status: string, preview: string | null | undefined) {
  if (status === "error") return "bear";
  const normalized = normalizeReportLabel(preview);
  if (normalized.includes("rui ro") || normalized.includes("bear") || normalized.includes("tieu cuc")) return "bear";
  if (normalized.includes("co hoi") || normalized.includes("bull") || normalized.includes("tich cuc")) return "bull";
  return "neutral";
}

function getRunStepStatusLabel(status: string) {
  if (status === "done") return "Xong";
  if (status === "running") return "Đang chạy";
  if (status === "error") return "Lỗi";
  return "Chờ";
}

function LlmConfigPanel({
  config,
  loading,
  saving,
  error,
  savedMessage,
  onSave,
}: {
  config: LlmConfigResponse | null;
  loading: boolean;
  saving: boolean;
  error: string;
  savedMessage: string;
  onSave: (payload: { provider: string; model: string; api_key?: string; clear_api_key?: boolean }) => Promise<void>;
}) {
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("gpt-4.1");
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const providerOptions = config?.providers.length
    ? config.providers
    : [{ provider: "openai", label: "OpenAI", key_env: "OPENAI_API_KEY", default_model: "gpt-4.1" }];

  useEffect(() => {
    if (!config) return;
    setProvider(config.provider);
    setModel(config.model);
    setApiKey("");
    setClearKey(false);
  }, [config]);

  const selectedProvider = providerOptions.find((item) => item.provider === provider);
  const hasKey = selectedProvider?.key_env ? Boolean(config?.has_api_key && config.provider === provider) : true;
  const keyLabel = selectedProvider?.key_env ?? "Không cần API key";
  const statusText = selectedProvider?.key_env
    ? hasKey
      ? `Đã lưu ${config?.api_key_preview ?? "API key"}`
      : "Chưa có API key"
    : "Provider local";

  const handleProviderChange = (nextProvider: string) => {
    const option = providerOptions.find((item) => item.provider === nextProvider);
    setProvider(nextProvider);
    if (option) setModel(option.default_model);
    setApiKey("");
    setClearKey(false);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await onSave({
      provider,
      model,
      api_key: apiKey.trim() || undefined,
      clear_api_key: clearKey,
    });
    setApiKey("");
    setClearKey(false);
  };

  return (
    <form className="llm-config-panel" onSubmit={handleSubmit}>
      <div className="llm-config-head">
        <div>
          <span>Cấu hình LLM</span>
          <strong>Provider dùng cho báo cáo AI</strong>
        </div>
        <b className={hasKey ? "ready" : "missing"}>{loading ? "Đang tải" : statusText}</b>
      </div>

      <div className="llm-config-grid">
        <label>
          <span>Provider</span>
          <select value={provider} onChange={(event) => handleProviderChange(event.target.value)} disabled={loading || saving}>
            {providerOptions.map((item) => (
              <option value={item.provider} key={item.provider}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Model</span>
          <input value={model} onChange={(event) => setModel(event.target.value)} disabled={loading || saving} />
        </label>
        <label className="llm-config-key">
          <span>{keyLabel}</span>
          <input
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={hasKey ? "Để trống nếu không đổi key" : "Nhập API key"}
            disabled={loading || saving || !selectedProvider?.key_env || clearKey}
            autoComplete="off"
          />
        </label>
        <div className="llm-config-actions">
          {selectedProvider?.key_env ? (
            <label className="llm-clear-key">
              <input type="checkbox" checked={clearKey} onChange={(event) => setClearKey(event.target.checked)} disabled={saving} />
              <span>Xóa key đã lưu</span>
            </label>
          ) : null}
          <button type="submit" disabled={loading || saving || !model.trim()}>
            {saving ? "Đang lưu" : "Lưu cấu hình"}
          </button>
        </div>
      </div>

      {savedMessage ? <small className="llm-config-note success">{savedMessage}</small> : null}
      {error ? <small className="llm-config-note error">{error}</small> : null}
    </form>
  );
}

function AnalysisRunPanel({
  ticker,
  sections,
  synthesisReport,
  activated,
  activeStep,
  canRun,
  cooldownText,
  lastRunAt,
  onRun,
  onOpenSummary,
  runStatus,
  runError,
}: {
  ticker: string;
  sections: AnalysisReportSection[];
  synthesisReport: AnalysisReportSection | undefined;
  activated: boolean;
  activeStep: number;
  canRun: boolean;
  cooldownText: string;
  lastRunAt: number | null;
  onRun: () => void;
  onOpenSummary: () => void;
  runStatus: AnalysisRunStatusResponse | null;
  runError: string;
}) {
  const debateSections = sections.filter((section) => section.key !== "research").slice(0, 5);
  const fallbackWorkflowSteps = [
    { label: "Chuẩn bị dữ liệu", detail: "Đọc báo cáo nền, tin tức, thị giá và định giá." },
    ...debateSections.map((section) => ({
      label: section.agent,
      detail: getSummarySentences(section.content, 1)[0] ?? section.title,
      tone: getAgentTone(section),
    })),
    { label: "Kết luận sơ bộ", detail: getSummarySentences(synthesisReport?.content ?? "", 1)[0] ?? "Tổng hợp quan điểm Bull/Bear." },
  ];

  const workflowSteps =
    runStatus?.steps.map((step) => ({
      label: step.agent,
      detail: step.preview || step.detail,
      status: step.status,
      tone: getRunStepTone(step.status, step.preview),
      meta: [
        getRunStepStatusLabel(step.status),
        step.word_count ? `${formatNumber(step.word_count)} từ` : null,
        step.last_modified ? formatDateTime(step.last_modified) : null,
      ]
        .filter(Boolean)
        .join(" · "),
    })) ?? fallbackWorkflowSteps;

  const conclusion = getSummarySentences(synthesisReport?.content ?? "", 2);
  const progressPercent = runStatus ? Math.round(runStatus.progress * 100) : null;
  const runButtonLabel = runStatus?.running ? "Đang theo dõi" : canRun ? "Kích hoạt báo cáo" : `Chờ ${cooldownText}`;

  return (
    <div className="analysis-run-panel">
      <div className="analysis-run-main">
        <div>
          <span className="analysis-run-eyebrow">Agent workflow</span>
          <strong>Kích hoạt báo cáo AI cho {ticker}</strong>
          <p>
            Mỗi mã chỉ kích hoạt một lần trong 7 ngày. Khi chạy, giao diện sẽ theo dõi tiến trình tranh luận,
            luận điểm chính và kết luận sơ bộ trước khi đọc báo cáo đầy đủ.
          </p>
        </div>
        <div className="analysis-run-actions">
          <button
            type="button"
            className="analysis-run-button"
            onClick={onRun}
            disabled={!canRun || Boolean(runStatus?.running)}
            aria-label={runButtonLabel}
            title={runButtonLabel}
          >
            {runButtonLabel}
          </button>
          <button type="button" className="analysis-summary-button" onClick={onOpenSummary} disabled={sections.length === 0}>
            Mở bản tóm tắt
          </button>
          {lastRunAt ? <small>Lần kích hoạt gần nhất: {formatDateTime(new Date(lastRunAt).toISOString())}</small> : null}
          {progressPercent !== null ? <small>Tiến trình: {progressPercent}% · {runStatus?.message}</small> : null}
        </div>
      </div>

      {runError ? <div className="message error">{runError}</div> : null}

      {activated ? (
        <div className="analysis-debate-board">
          <div className="analysis-debate-steps">
            {workflowSteps.map((step, index) => {
              const status =
                "status" in step && step.status ? String(step.status) : getWorkflowStatus(index, activeStep, activated);
              const tone = "tone" in step && step.tone ? String(step.tone) : "neutral";
              const meta = "meta" in step && step.meta ? String(step.meta) : "";
              return (
                <div className={`analysis-debate-step ${status} ${tone}`} key={`${step.label}-${index}`}>
                  <span>{index + 1}</span>
                  <div>
                    <strong>{step.label}</strong>
                    {meta ? <em>{meta}</em> : null}
                    <p>{step.detail}</p>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="analysis-debate-conclusion">
            <span>Kết luận sơ bộ</span>
            <strong>{synthesisReport?.title ?? "Tổng hợp Bull/Bear"}</strong>
            {conclusion.length > 0 ? conclusion.map((item, index) => <p key={index}>{item}</p>) : <p>Chưa có đủ báo cáo để tổng hợp.</p>}
            {runStatus?.logs.length ? (
              <div className="analysis-run-log">
                <span>Log gần nhất</span>
                {runStatus.logs.slice(0, 8).map((entry, index) => (
                  <div className="analysis-run-log-row" key={`${entry.source ?? "log"}-${index}`}>
                    <small>{entry.timestamp ? formatDateTime(entry.timestamp) : "--"}</small>
                    <strong>{entry.agent ?? "Hệ thống"}</strong>
                    <p>{entry.message}</p>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function AnalysisSummaryView({
  synthesisReport,
  supportingReports,
  onOpenReport,
}: {
  synthesisReport: AnalysisReportSection | undefined;
  supportingReports: AnalysisReportSection[];
  onOpenReport: (key: string) => void;
}) {
  const synthesisPoints = getSummarySentences(synthesisReport?.content ?? "", 4);

  return (
    <article className="analysis-report-reader analysis-summary-reader">
      <div className="analysis-report-reader-header">
        <div>
          <strong>Bản tóm tắt phân tích</strong>
          <span>Tổng hợp ngắn gọn từ báo cáo Bull/Bear và các agent nền</span>
        </div>
        {synthesisReport ? (
          <button type="button" className="analysis-reader-action" onClick={() => onOpenReport(synthesisReport.key)}>
            Mở báo cáo gốc
          </button>
        ) : null}
      </div>

      <div className="analysis-summary-grid">
        <section className="analysis-summary-card featured">
          <span>Kết luận chính</span>
          <strong>{synthesisReport?.title ?? "Chưa có tổng hợp"}</strong>
          {synthesisPoints.length > 0 ? synthesisPoints.map((point, index) => <p key={index}>{point}</p>) : <p>Chưa có đủ dữ liệu tổng hợp cho mã này.</p>}
        </section>

        {supportingReports.map((section) => (
          <section className={`analysis-summary-card ${getAgentTone(section)}`} key={section.key}>
            <span>{section.agent}</span>
            <strong>{section.title}</strong>
            <p>{getSummarySentences(section.content, 1)[0] ?? "Chưa có nội dung nổi bật."}</p>
            <button type="button" onClick={() => onOpenReport(section.key)}>
              Xem chi tiết
            </button>
          </section>
        ))}
      </div>
    </article>
  );
}

function renderMarkdown(content: string) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const nodes: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const HeadingTag = `h${Math.min(level + 2, 5)}` as keyof JSX.IntrinsicElements;
      nodes.push(<HeadingTag key={index}>{renderInline(headingMatch[2])}</HeadingTag>);
      index += 1;
      continue;
    }

    if (trimmed.includes("|") && lines[index + 1] && isTableSeparator(lines[index + 1])) {
      const headers = parseTableRow(trimmed);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].trim().includes("|")) {
        rows.push(parseTableRow(lines[index]));
        index += 1;
      }

      nodes.push(
        <div className="analysis-markdown-table-wrap" key={index}>
          <table>
            <thead>
              <tr>
                {headers.map((header, cellIndex) => (
                  <th key={`${header}-${cellIndex}`}>{renderInline(header)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={`${rowIndex}-${cellIndex}`}>{renderInline(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    if (/^[-*]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*]\s+/, ""));
        index += 1;
      }
      nodes.push(
        <ul key={index}>
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInline(item)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^\d+\.\s+/, ""));
        index += 1;
      }
      nodes.push(
        <ol key={index}>
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInline(item)}</li>
          ))}
        </ol>,
      );
      continue;
    }

    if (trimmed.startsWith(">")) {
      const quotes: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        quotes.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      nodes.push(<blockquote key={index}>{renderInline(quotes.join(" "))}</blockquote>);
      continue;
    }

    const paragraph: string[] = [];
    while (index < lines.length) {
      const current = lines[index].trim();
      const next = lines[index + 1]?.trim();
      if (
        !current ||
        /^#{1,4}\s+/.test(current) ||
        /^[-*]\s+/.test(current) ||
        /^\d+\.\s+/.test(current) ||
        current.startsWith(">") ||
        (current.includes("|") && next && isTableSeparator(next))
      ) {
        break;
      }
      paragraph.push(current);
      index += 1;
    }

    nodes.push(<p key={index}>{renderInline(paragraph.join(" "))}</p>);
  }

  return nodes;
}

function ReportButton({
  item,
  active,
  onClick,
}: {
  item: AnalysisReportSection;
  active: boolean;
  onClick: () => void;
}) {
  const preview = getReportPreview(item.content);
  const className = [
    "analysis-report-tab",
    item.key === "research" ? "synthesis" : "",
    active ? "active" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button type="button" className={className} onClick={onClick}>
      <span>{item.title}</span>
      <strong>{item.agent}</strong>
      {item.key === "research" ? <b>Bull/Bear tổng hợp</b> : null}
      <small>
        {item.trade_date ?? formatDateTime(item.last_modified)} · {formatNumber(item.word_count)} từ
      </small>
      {preview ? <em>{preview}</em> : null}
    </button>
  );
}

export function AnalysisReportsPanel({ reports, ticker, loading = false, error = "", onRefresh }: Props) {
  const [activeKey, setActiveKey] = useState<string>("");
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [lastRunAt, setLastRunAt] = useState<number | null>(null);
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null);
  const [activeWorkflowStep, setActiveWorkflowStep] = useState(0);
  const [runStatus, setRunStatus] = useState<AnalysisRunStatusResponse | null>(null);
  const [runError, setRunError] = useState("");
  const [llmConfig, setLlmConfig] = useState<LlmConfigResponse | null>(null);
  const [llmConfigLoading, setLlmConfigLoading] = useState(false);
  const [llmConfigSaving, setLlmConfigSaving] = useState(false);
  const [llmConfigError, setLlmConfigError] = useState("");
  const [llmConfigSaved, setLlmConfigSaved] = useState("");
  const sections = useMemo(
    () => [...(reports?.sections ?? [])].sort((first, second) => getSectionPriority(first) - getSectionPriority(second)),
    [reports],
  );

  useEffect(() => {
    if (sections.length === 0) {
      setActiveKey("");
      return;
    }

    if (!sections.some((section) => section.key === activeKey)) {
      setActiveKey(sections[0].key);
    }
  }, [activeKey, sections]);

  const activeReport = sections.find((section) => section.key === activeKey) ?? sections[0];
  const synthesisReport = sections.find((section) => section.key === "research");
  const supportingReports = sections.filter((section) => section.key !== "research");
  const now = Date.now();
  const cooldownRemaining = lastRunAt ? Math.max(0, lastRunAt + REPORT_COOLDOWN_MS - now) : 0;
  const canRunReport = cooldownRemaining <= 0;
  const workflowStepCount = Math.max(2, supportingReports.length + 2);

  useEffect(() => {
    let ignore = false;
    setLlmConfigLoading(true);
    setLlmConfigError("");
    fetchLlmConfig()
      .then((payload) => {
        if (ignore) return;
        setLlmConfig(payload);
        setLlmConfigLoading(false);
      })
      .catch((err) => {
        if (ignore) return;
        setLlmConfigError(err instanceof Error ? err.message : "Không tải được cấu hình LLM");
        setLlmConfigLoading(false);
      });

    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedValue = window.localStorage.getItem(getRunStorageKey(ticker));
    const parsedValue = storedValue ? Number(storedValue) : null;
    setLastRunAt(parsedValue && Number.isFinite(parsedValue) ? parsedValue : null);
    setRunStartedAt(null);
    setRunStatus(null);
    setRunError("");
    setActiveWorkflowStep(0);
    setSummaryOpen(false);
  }, [ticker]);

  useEffect(() => {
    if (!runStartedAt) return;
    setActiveWorkflowStep(0);
    const timer = window.setInterval(() => {
      setActiveWorkflowStep((current) => {
        if (current >= workflowStepCount - 1) {
          window.clearInterval(timer);
          return current;
        }
        return current + 1;
      });
    }, 900);

    return () => window.clearInterval(timer);
  }, [runStartedAt, workflowStepCount]);

  useEffect(() => {
    if (!runStartedAt) return;

    let ignore = false;
    let refreshed = false;
    let timer: number | undefined;
    const startedAt = new Date(runStartedAt).toISOString();

    const loadStatus = async () => {
      try {
        const status = await fetchAnalysisRunStatus({ ticker, startedAt });
        if (ignore) return;

        setRunStatus(status);
        setRunError("");

        if (!status.running && status.progress < 1 && typeof window !== "undefined") {
          window.localStorage.removeItem(getRunStorageKey(ticker));
          setLastRunAt(null);
        }

        if ((!status.running || status.progress >= 1) && !refreshed) {
          refreshed = true;
          onRefresh?.();
          if (timer) window.clearInterval(timer);
        }
      } catch (err) {
        if (!ignore) {
          setRunError(err instanceof Error ? err.message : "Không tải được tiến trình báo cáo AI");
        }
      }
    };

    void loadStatus();
    timer = window.setInterval(loadStatus, 4000);

    return () => {
      ignore = true;
      if (timer) window.clearInterval(timer);
    };
  }, [onRefresh, runStartedAt, ticker]);

  const handleRunReport = async () => {
    if (!canRunReport) return;
    setRunError("");
    try {
      const status = await startAnalysisReportRun(ticker);
      const timestamp = status.started_at ? new Date(status.started_at).getTime() : Date.now();
      if (typeof window !== "undefined") {
        window.localStorage.setItem(getRunStorageKey(ticker), String(timestamp));
      }
      setRunStatus(status);
      setLastRunAt(timestamp);
      setRunStartedAt(timestamp);
      setSummaryOpen(false);
    } catch (err) {
      setRunError(err instanceof Error ? err.message : "Không kích hoạt được báo cáo phân tích AI");
    }
  };

  const handleSaveLlmConfig = async (payload: {
    provider: string;
    model: string;
    api_key?: string;
    clear_api_key?: boolean;
  }) => {
    setLlmConfigSaving(true);
    setLlmConfigError("");
    setLlmConfigSaved("");
    try {
      const nextConfig = await updateLlmConfig(payload);
      setLlmConfig(nextConfig);
      setLlmConfigSaved("Đã lưu cấu hình LLM");
    } catch (err) {
      setLlmConfigError(err instanceof Error ? err.message : "Không lưu được cấu hình LLM");
    } finally {
      setLlmConfigSaving(false);
    }
  };

  const openReport = (key: string) => {
    setActiveKey(key);
    setSummaryOpen(false);
  };

  if (!reports && !loading && !error) {
    return (
      <div className="analysis-report-card">
        <LlmConfigPanel
          config={llmConfig}
          loading={llmConfigLoading}
          saving={llmConfigSaving}
          error={llmConfigError}
          savedMessage={llmConfigSaved}
          onSave={handleSaveLlmConfig}
        />
        <AnalysisRunPanel
          ticker={ticker}
          sections={sections}
          synthesisReport={synthesisReport}
          activated={Boolean(runStartedAt)}
          activeStep={activeWorkflowStep}
          canRun={canRunReport}
          cooldownText={formatRemainingCooldown(cooldownRemaining)}
          lastRunAt={lastRunAt}
          onRun={handleRunReport}
          onOpenSummary={() => setSummaryOpen(true)}
          runStatus={runStatus}
          runError={runError}
        />
        <div className="analysis-report-empty">
          <strong>Chưa có báo cáo phân tích AI</strong>
          <span>Chạy TradingAgents cho mã {ticker}, báo cáo markdown sẽ tự xuất hiện tại đây.</span>
        </div>
      </div>
    );
  }

  return (
    <section className="analysis-report-card">
      <div className="analysis-report-header">
        <div>
          <strong>Báo cáo phân tích AI</strong>
          <span>
            {reports
              ? `${reports.total} báo cáo cho ${reports.ticker} · cập nhật ${formatDateTime(reports.updated_at)}`
              : `Đang kiểm tra báo cáo cho ${ticker}`}
          </span>
        </div>
        <span className="analysis-report-badge">TradingAgents</span>
      </div>

      <LlmConfigPanel
        config={llmConfig}
        loading={llmConfigLoading}
        saving={llmConfigSaving}
        error={llmConfigError}
        savedMessage={llmConfigSaved}
        onSave={handleSaveLlmConfig}
      />

      <AnalysisRunPanel
        ticker={ticker}
        sections={sections}
        synthesisReport={synthesisReport}
        activated={Boolean(runStartedAt)}
        activeStep={activeWorkflowStep}
        canRun={canRunReport}
        cooldownText={formatRemainingCooldown(cooldownRemaining)}
        lastRunAt={lastRunAt}
        onRun={handleRunReport}
        onOpenSummary={() => setSummaryOpen(true)}
        runStatus={runStatus}
        runError={runError}
      />

      {error ? <div className="message error">{error}</div> : null}
      {loading ? <div className="message">Đang tải báo cáo phân tích AI...</div> : null}

      {sections.length > 0 && activeReport ? (
        <>
          <div className="analysis-synthesis-hero">
            <img src="/assets/bull-bear-scale.png" alt="" aria-hidden="true" />
            <div className="analysis-synthesis-copy">
              <span>Báo cáo trọng tâm</span>
              <strong>{synthesisReport?.title ?? "Tổng hợp Bull/Bear"}</strong>
              <p>Ưu tiên phần tổng hợp để nhìn nhanh luận điểm Bull/Bear, rồi mở các báo cáo nền để kiểm tra chi tiết.</p>
            </div>
            <button
              type="button"
              className="analysis-synthesis-button"
              onClick={() => openReport(synthesisReport?.key ?? activeReport.key)}
            >
              Mở tổng hợp
            </button>
          </div>

          <div className="analysis-report-layout">
          <aside className="analysis-report-tabs" aria-label="Danh sách báo cáo phân tích">
            {sections.map((section) => (
              <ReportButton
                key={section.key}
                item={section}
                active={!summaryOpen && section.key === activeReport.key}
                onClick={() => openReport(section.key)}
              />
            ))}
          </aside>

          {summaryOpen ? (
            <AnalysisSummaryView
              synthesisReport={synthesisReport}
              supportingReports={supportingReports}
              onOpenReport={openReport}
            />
          ) : (
            <article className="analysis-report-reader">
            <div className="analysis-report-reader-header">
              <div>
                <strong>{activeReport.title}</strong>
                <span>
                  {activeReport.agent} · {formatNumber(activeReport.word_count)} từ ·{" "}
                  {getFileName(activeReport.source_file)}
                </span>
              </div>
              <span>{activeReport.trade_date ?? formatDateTime(activeReport.last_modified)}</span>
            </div>
            {activeReport.key === "research" && supportingReports.length > 0 ? (
              <div className="analysis-supporting-links" aria-label="Liên kết báo cáo nền">
                <div>
                  <strong>Báo cáo nền</strong>
                  <span>Mở nhanh từng nguồn mà phần Bull/Bear đã tổng hợp</span>
                </div>
                <div className="analysis-supporting-link-list">
                  {supportingReports.map((section) => (
                    <button type="button" key={section.key} onClick={() => openReport(section.key)}>
                      {section.title}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {activeReport.key !== "research" && synthesisReport ? (
              <div className="analysis-back-to-synthesis">
                <span>Báo cáo này là nguồn chi tiết cho phần tổng hợp Bull/Bear.</span>
                <button type="button" onClick={() => openReport(synthesisReport.key)}>
                  Quay lại tổng hợp
                </button>
              </div>
            ) : null}

            <div className="analysis-markdown">{renderAgentReportText(activeReport.content)}</div>
          </article>
          )}
        </div>
        </>
      ) : !loading ? (
        <div className="analysis-report-empty">
          <strong>Chưa tìm thấy báo cáo cho {ticker}</strong>
          <span>Backend đang đọc trong thư mục TradingAgents/reports và log mặc định của TradingAgents.</span>
        </div>
      ) : null}
    </section>
  );
}
