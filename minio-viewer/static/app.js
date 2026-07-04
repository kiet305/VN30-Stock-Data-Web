const state = {
  currentPath: "",
  includeSystem: false,
  selectedPath: null,
  previewRows: 25,
  previewColumns: "12",
  previewOrder: "head",
  tickerSearch: "",
  listCache: new Map(),
};

const els = {
  rootPath: document.querySelector("#rootPath"),
  refreshButton: document.querySelector("#refreshButton"),
  includeSystem: document.querySelector("#includeSystem"),
  bucketCount: document.querySelector("#bucketCount"),
  fileCount: document.querySelector("#fileCount"),
  dirCount: document.querySelector("#dirCount"),
  totalSize: document.querySelector("#totalSize"),
  bucketList: document.querySelector("#bucketList"),
  breadcrumbs: document.querySelector("#breadcrumbs"),
  treeDepth: document.querySelector("#treeDepth"),
  expandDepthButton: document.querySelector("#expandDepthButton"),
  searchInput: document.querySelector("#searchInput"),
  treeArea: document.querySelector("#treeArea"),
  detailsContent: document.querySelector("#detailsContent"),
};

function apiUrl(path, params = {}) {
  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  });
  if (state.includeSystem) {
    url.searchParams.set("includeSystem", "1");
  }
  return url;
}

async function fetchJson(path, params) {
  const response = await fetch(apiUrl(path, params));
  const payload = await response.json();
  if (!response.ok || payload.error) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function formatBytes(value) {
  if (value === null || value === undefined) return "";
  if (value === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const amount = value / 1024 ** index;
  return `${amount >= 10 || index === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
}

function formatNumber(value) {
  return new Intl.NumberFormat("vi-VN").format(value || 0);
}

function formatDate(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

function isPreviewable(entry) {
  const name = (entry?.name || "").toLowerCase();
  return (
    name.endsWith(".parquet") ||
    name.endsWith(".csv") ||
    name.endsWith(".json") ||
    name.endsWith(".jsonl") ||
    name.endsWith(".ndjson")
  );
}

function cacheKey(path) {
  return `${state.includeSystem ? "1" : "0"}:${path}`;
}

function setLoading(message = "Đang tải...") {
  els.treeArea.innerHTML = `<div class="empty-state">${message}</div>`;
}

function setError(message) {
  els.treeArea.innerHTML = `<div class="error-state">${escapeHtml(message)}</div>`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function loadOverview() {
  const overview = await fetchJson("/api/overview");
  els.rootPath.textContent = overview.root;
  els.bucketCount.textContent = formatNumber(overview.bucketCount);
  els.fileCount.textContent = formatNumber(overview.fileCount);
  els.dirCount.textContent = formatNumber(overview.directoryCount);
  els.totalSize.textContent = formatBytes(overview.totalSize);
  renderBuckets(overview.buckets);

  if (!overview.exists) {
    setError("Không tìm thấy thư mục MinIO.");
  }
}

function renderBuckets(buckets) {
  if (!buckets.length) {
    els.bucketList.innerHTML = '<div class="empty-state">Chưa có bucket để hiển thị.</div>';
    return;
  }

  els.bucketList.innerHTML = "";
  buckets.forEach((bucket) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `bucket-card${state.currentPath === bucket.path ? " active" : ""}`;
    button.innerHTML = `
      <div class="bucket-name">
        <span class="folder-icon"></span>
        <span>${escapeHtml(bucket.name)}</span>
      </div>
      <div class="bucket-meta">
        ${formatNumber(bucket.fileCount)} file · ${formatNumber(bucket.directoryCount)} thư mục · ${formatBytes(bucket.totalSize)}
        ${bucket.truncated ? '<span class="warning-text"> · giới hạn quét</span>' : ""}
      </div>
    `;
    button.addEventListener("click", () => openDirectory(bucket.path));
    els.bucketList.append(button);
  });
}

async function openDirectory(path = "") {
  state.currentPath = path;
  state.selectedPath = null;
  els.searchInput.value = "";
  setLoading("Đang tải cấu trúc...");

  try {
    const payload = await getDirectory(path);
    renderBreadcrumbs(payload.breadcrumbs);
    renderList(payload.entries);
    renderDetails(null);
    await loadOverview();
  } catch (error) {
    setError(error.message);
  }
}

async function getDirectory(path) {
  const key = cacheKey(path);
  if (state.listCache.has(key)) {
    return state.listCache.get(key);
  }
  const payload = await fetchJson("/api/list", { path });
  state.listCache.set(key, payload);
  return payload;
}

function renderBreadcrumbs(crumbs) {
  els.breadcrumbs.innerHTML = "";
  crumbs.forEach((crumb, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `crumb${index === crumbs.length - 1 ? " current" : ""}`;
    button.textContent = crumb.name;
    button.addEventListener("click", () => openDirectory(crumb.path));
    els.breadcrumbs.append(button);
  });
}

function renderList(entries) {
  if (!entries.length) {
    els.treeArea.innerHTML = '<div class="empty-state">Thư mục này đang trống.</div>';
    return;
  }

  els.treeArea.innerHTML = "";
  const root = document.createElement("div");
  root.className = "tree-root";
  entries.forEach((entry) => root.append(renderNode(entry, 0)));
  els.treeArea.append(root);
}

function renderNode(entry, level) {
  const wrapper = document.createElement("div");
  wrapper.className = "tree-node";
  wrapper.dataset.path = entry.path;

  const row = document.createElement("div");
  row.className = "tree-row";
  row.style.paddingLeft = `${8 + level * 14}px`;

  const canExpand = entry.type === "directory" && entry.childrenCount !== 0;
  const disclosure = document.createElement(canExpand ? "button" : "span");
  disclosure.className = canExpand ? "disclosure" : "disclosure placeholder";
  if (canExpand) {
    disclosure.type = "button";
    disclosure.title = "Mở thư mục";
  } else {
    disclosure.setAttribute("aria-hidden", "true");
  }

  const icon = document.createElement("span");
  icon.className = entry.type === "directory" ? "folder-icon" : "file-icon";

  const name = document.createElement("div");
  name.className = "node-name";
  name.textContent = entry.name;
  name.title = entry.path;

  const size = document.createElement("div");
  size.className = "node-size";
  size.textContent =
    entry.type === "directory"
      ? entry.childrenCount === null || entry.childrenCount === undefined
        ? "thư mục"
        : `${formatNumber(entry.childrenCount)} item`
      : formatBytes(entry.size);

  const date = document.createElement("div");
  date.className = "node-date";
  date.textContent = formatDate(entry.modified);

  row.append(disclosure, icon, name, size, date);
  wrapper.append(row);

  row.addEventListener("click", () => {
    document.querySelectorAll(".tree-row.selected").forEach((node) => {
      node.classList.remove("selected");
    });
    row.classList.add("selected");
    state.selectedPath = entry.path;
    renderDetails(entry);
    if (isPreviewable(entry)) {
      loadPreview(entry.path);
    }
  });

  if (canExpand) {
    disclosure.addEventListener("click", async (event) => {
      event.stopPropagation();
      await toggleDirectory(wrapper, entry, level + 1, disclosure);
    });
  }

  return wrapper;
}

async function toggleDirectory(wrapper, entry, level, disclosure) {
  const existing = wrapper.querySelector(":scope > .children");
  if (existing) {
    existing.hidden = !existing.hidden;
    disclosure.classList.toggle("open", !existing.hidden);
    return;
  }

  disclosure.classList.add("open");
  const children = document.createElement("div");
  children.className = "children";
  children.innerHTML = '<div class="empty-state">Đang tải...</div>';
  wrapper.append(children);

  try {
    const payload = await getDirectory(entry.path);
    children.innerHTML = "";
    if (!payload.entries.length) {
      children.innerHTML = '<div class="empty-state">Trống</div>';
      return;
    }
    payload.entries.forEach((child) => children.append(renderNode(child, level)));
  } catch (error) {
    children.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
  }
}

function renderDetails(entry) {
  if (!entry) {
    els.detailsContent.innerHTML = '<div class="empty-state">Chọn một item để xem thông tin.</div>';
    return;
  }

  els.detailsContent.innerHTML = `
    <div class="detail-item">
      <label>Tên</label>
      <code>${escapeHtml(entry.name)}</code>
    </div>
    <div class="detail-item">
      <label>Loại</label>
      <code>${entry.type === "directory" ? "Thư mục" : "File"}</code>
    </div>
    <div class="detail-item">
      <label>Path</label>
      <code>${escapeHtml(entry.path || "/")}</code>
    </div>
    <div class="detail-item">
      <label>Kích thước</label>
      <code>${
        entry.type === "directory"
          ? entry.childrenCount === null || entry.childrenCount === undefined
            ? "thư mục"
            : `${formatNumber(entry.childrenCount)} item`
          : formatBytes(entry.size)
      }</code>
    </div>
    <div class="detail-item">
      <label>Cập nhật</label>
      <code>${formatDate(entry.modified)}</code>
    </div>
    ${
      isPreviewable(entry)
        ? `
          <div class="preview-controls">
            <div>
              <label for="previewRowsSelect">Dòng preview</label>
              <select id="previewRowsSelect">
                <option value="10">10 dòng</option>
                <option value="25">25 dòng</option>
                <option value="50">50 dòng</option>
                <option value="100">100 dòng</option>
                <option value="all">Tất cả dòng</option>
              </select>
            </div>
            <div>
              <label for="previewColumnsSelect">Cột hiển thị</label>
              <select id="previewColumnsSelect">
                <option value="12">12 cột đầu</option>
                <option value="25">25 cột đầu</option>
                <option value="all">Tất cả cột</option>
              </select>
            </div>
            <div>
              <label for="previewOrderSelect">Hướng xem</label>
              <select id="previewOrderSelect">
                <option value="head">Từ trên xuống</option>
                <option value="tail">Từ dưới lên</option>
              </select>
            </div>
            <div>
              <label for="previewTickerInput">Ticker</label>
              <input id="previewTickerInput" type="search" placeholder="AAA, FPT..." />
            </div>
          </div>
          <div id="previewContent" class="preview-content"><div class="empty-state">Đang tải preview dataframe...</div></div>
        `
        : '<div class="empty-state compact-empty">Không có preview dataframe cho item này.</div>'
    }
  `;

  const previewRowsSelect = document.querySelector("#previewRowsSelect");
  if (previewRowsSelect) {
    previewRowsSelect.value = String(state.previewRows);
    previewRowsSelect.addEventListener("change", () => {
      state.previewRows =
        previewRowsSelect.value === "all" ? "all" : Number(previewRowsSelect.value);
      loadPreview(entry.path);
    });
  }

  const previewColumnsSelect = document.querySelector("#previewColumnsSelect");
  if (previewColumnsSelect) {
    previewColumnsSelect.value = state.previewColumns;
    previewColumnsSelect.addEventListener("change", () => {
      state.previewColumns = previewColumnsSelect.value;
      loadPreview(entry.path);
    });
  }

  const previewOrderSelect = document.querySelector("#previewOrderSelect");
  if (previewOrderSelect) {
    previewOrderSelect.value = state.previewOrder;
    previewOrderSelect.addEventListener("change", () => {
      state.previewOrder = previewOrderSelect.value;
      loadPreview(entry.path);
    });
  }

  const previewTickerInput = document.querySelector("#previewTickerInput");
  if (previewTickerInput) {
    previewTickerInput.value = state.tickerSearch;
    previewTickerInput.addEventListener(
      "input",
      debounce(() => {
        state.tickerSearch = previewTickerInput.value.trim().toUpperCase();
        loadPreview(entry.path);
      }, 300),
    );
  }
}

async function loadPreview(path) {
  const selectedPath = path;
  const target = document.querySelector("#previewContent");
  if (!target) return;

  try {
    const payload = await fetchJson("/api/preview", {
      path,
      rows: state.previewRows,
      order: state.previewOrder,
      ticker: state.tickerSearch,
    });
    if (state.selectedPath !== selectedPath) return;
    renderPreview(payload, target);
  } catch (error) {
    if (state.selectedPath !== selectedPath) return;
    target.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
  }
}

function renderPreview(payload, target) {
  const columns = payload.columns || [];
  const rows = payload.rows || [];
  const dtypes = payload.dtypes || {};
  const tickerLabel =
    payload.ticker && payload.tickerColumn
      ? `${escapeHtml(payload.ticker)} / ${escapeHtml(payload.tickerColumn)}`
      : payload.ticker
        ? `${escapeHtml(payload.ticker)} / no column`
        : "all";
  const visibleColumns =
    state.previewColumns === "all"
      ? columns
      : columns.slice(0, Number(state.previewColumns));

  target.innerHTML = `
    <div class="preview-summary">
      <div>
        <span>${escapeHtml(payload.format || "")}</span>
        <label>format</label>
      </div>
      <div>
        <span>${payload.rowCount === null || payload.rowCount === undefined ? "?" : formatNumber(payload.rowCount)}</span>
        <label>dòng</label>
      </div>
      <div>
        <span>${formatNumber(payload.columnCount)}</span>
        <label>cột</label>
      </div>
      <div>
        <span>${formatNumber(rows.length)}</span>
        <label>preview</label>
      </div>
      <div>
        <span>${payload.order === "tail" ? "dưới lên" : "trên xuống"}</span>
        <label>hướng</label>
      </div>
      <div>
        <span>${tickerLabel}</span>
        <label>ticker</label>
      </div>
      <div>
        <span>${
          payload.filteredRowCount === null || payload.filteredRowCount === undefined
            ? "-"
            : formatNumber(payload.filteredRowCount)
        }</span>
        <label>match</label>
      </div>
    </div>
    <div class="column-section">
      <label>Tên cột</label>
      <div class="column-list">
        ${columns.map((column) => `<span title="${escapeHtml(dtypes[column] || "")}">${escapeHtml(column)}</span>`).join("")}
      </div>
    </div>
    <div class="table-wrap">
      ${renderPreviewTable(visibleColumns, rows, columns.length)}
    </div>
  `;
}

function renderPreviewTable(columns, rows, totalColumns) {
  if (!columns.length) {
    return '<div class="empty-state compact-empty">Không có cột để hiển thị.</div>';
  }
  if (!rows.length) {
    return '<div class="empty-state compact-empty">Không có dòng preview.</div>';
  }

  const header = columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("");
  const body = rows
    .map((row) => {
      const cells = columns
        .map((column) => `<td title="${escapeHtml(row[column] ?? "")}">${escapeHtml(row[column] ?? "")}</td>`)
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  const note =
    totalColumns > columns.length
      ? `<div class="preview-note">Đang hiển thị ${columns.length}/${totalColumns} cột đầu tiên.</div>`
      : "";

  return `
    ${note}
    <table class="preview-table">
      <thead><tr>${header}</tr></thead>
      <tbody>${body}</tbody>
    </table>
  `;
}

async function expandToDepth() {
  setLoading("Đang mở cây...");
  try {
    const payload = await fetchJson("/api/tree", {
      path: state.currentPath,
      depth: els.treeDepth.value,
    });
    renderTreePayload(payload.tree);
  } catch (error) {
    setError(error.message);
  }
}

function renderTreePayload(tree) {
  els.treeArea.innerHTML = "";
  const root = document.createElement("div");
  root.className = "tree-root";
  (tree.children || []).forEach((entry) => root.append(renderTreeNode(entry, 0)));
  els.treeArea.append(root);
}

function renderTreeNode(entry, level) {
  const wrapper = renderNode(entry, level);
  if (entry.children && entry.children.length) {
    const disclosure = wrapper.querySelector(".disclosure");
    disclosure.classList.add("open");
    const children = document.createElement("div");
    children.className = "children";
    entry.children.forEach((child) => children.append(renderTreeNode(child, level + 1)));
    wrapper.append(children);
  }
  return wrapper;
}

async function runSearch(query) {
  const term = query.trim();
  if (!term) {
    const payload = await getDirectory(state.currentPath);
    renderList(payload.entries);
    return;
  }

  setLoading("Đang tìm...");
  try {
    const payload = await fetchJson("/api/search", { q: term, limit: 250 });
    if (!payload.results.length) {
      els.treeArea.innerHTML = '<div class="empty-state">Không tìm thấy kết quả.</div>';
      return;
    }
    renderList(payload.results);
    if (payload.truncated) {
      const note = document.createElement("div");
      note.className = "warning-text";
      note.textContent = "Kết quả đã được giới hạn ở 250 item.";
      els.treeArea.prepend(note);
    }
  } catch (error) {
    setError(error.message);
  }
}

function debounce(fn, delay) {
  let timer;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
}

async function refreshAll() {
  state.listCache.clear();
  await openDirectory(state.currentPath);
}

els.refreshButton.addEventListener("click", refreshAll);
els.includeSystem.addEventListener("change", async () => {
  state.includeSystem = els.includeSystem.checked;
  state.listCache.clear();
  await openDirectory("");
});
els.expandDepthButton.addEventListener("click", expandToDepth);
els.searchInput.addEventListener(
  "input",
  debounce((event) => runSearch(event.target.value), 250),
);

openDirectory("").catch((error) => setError(error.message));
