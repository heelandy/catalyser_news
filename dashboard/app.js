const DATA_PATHS = {
  signals: "../macro_live_signal_adjusted.csv",
  performance: "../macro_signal_performance.csv",
  trust: "../macro_signal_trust_weights.csv",
  status: "../macro_pipeline_status.json",
  alerts: "../macro_pipeline_alert_summary.json",
};

const state = {
  signals: [],
  performance: [],
  trust: [],
  status: null,
  alertSummary: null,
  activeTab: "signals",
  selectedId: "",
  sortKey: "release_time",
  sortDir: "asc",
  filters: {
    search: "",
    category: "all",
    status: "all",
    direction: "all",
  },
};

const els = {
  dataStamp: document.querySelector("#dataStamp"),
  reloadBtn: document.querySelector("#reloadBtn"),
  metrics: document.querySelector("#metrics"),
  componentRanges: document.querySelector("#componentRanges"),
  alertPanel: document.querySelector("#alertPanel"),
  searchInput: document.querySelector("#searchInput"),
  categorySelect: document.querySelector("#categorySelect"),
  signalFilters: document.querySelector("#signalFilters"),
  signalsBody: document.querySelector("#signalsBody"),
  performanceBody: document.querySelector("#performanceBody"),
  trustBody: document.querySelector("#trustBody"),
  probabilityChart: document.querySelector("#probabilityChart"),
  performanceChart: document.querySelector("#performanceChart"),
  trustChart: document.querySelector("#trustChart"),
  probabilityRange: document.querySelector("#probabilityRange"),
  performanceRange: document.querySelector("#performanceRange"),
  trustRange: document.querySelector("#trustRange"),
  detailPanel: document.querySelector("#detailPanel"),
  tabs: Array.from(document.querySelectorAll(".tab")),
  views: Array.from(document.querySelectorAll(".view")),
  segments: Array.from(document.querySelectorAll(".segment")),
  sortableHeaders: Array.from(document.querySelectorAll("th[data-sort]")),
};

function parseCsv(text) {
  const rows = [];
  let row = [];
  let value = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];

    if (char === '"' && inQuotes && next === '"') {
      value += '"';
      i += 1;
    } else if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === "," && !inQuotes) {
      row.push(value);
      value = "";
    } else if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") {
        i += 1;
      }
      row.push(value);
      if (row.some((cell) => cell !== "")) {
        rows.push(row);
      }
      row = [];
      value = "";
    } else {
      value += char;
    }
  }

  if (value || row.length) {
    row.push(value);
    rows.push(row);
  }

  if (!rows.length) {
    return [];
  }

  const headers = rows[0].map((h) => h.trim());
  return rows.slice(1).map((cells) => {
    const out = {};
    headers.forEach((header, index) => {
      out[header] = cells[index] || "";
    });
    return out;
  });
}

async function fetchCsv(path) {
  const response = await fetch(`${path}?v=${Date.now()}`);
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
  return parseCsv(await response.text());
}

async function fetchJson(path) {
  const response = await fetch(`${path}?v=${Date.now()}`);
  if (!response.ok) {
    return null;
  }
  return response.json();
}

function numberValue(value, fallback = NaN) {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function percent(value, digits = 1) {
  const n = numberValue(value);
  if (!Number.isFinite(n)) {
    return "--";
  }
  return `${(n * 100).toFixed(digits)}%`;
}

function points(value, digits = 1) {
  const n = numberValue(value);
  if (!Number.isFinite(n)) {
    return "--";
  }
  return n.toFixed(digits);
}

function clean(value, fallback = "--") {
  const text = String(value || "").trim();
  return text || fallback;
}

function minMax(rows, getter) {
  const values = rows
    .map(getter)
    .map((value) => numberValue(value))
    .filter((value) => Number.isFinite(value));
  if (!values.length) {
    return { min: NaN, max: NaN };
  }
  return {
    min: Math.min(...values),
    max: Math.max(...values),
  };
}

function rangeText(range, formatter) {
  if (!Number.isFinite(range.min) || !Number.isFinite(range.max)) {
    return "--";
  }
  return `${formatter(range.min)} / ${formatter(range.max)}`;
}

function rangeChip(label, range, formatter) {
  return `<span class="range-chip">${label}<strong>${rangeText(range, formatter)}</strong></span>`;
}

function plainNumber(value) {
  const n = numberValue(value);
  if (!Number.isFinite(n)) {
    return "--";
  }
  return Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(2);
}

function formatTime(value) {
  const text = clean(value, "");
  if (!text) {
    return "--";
  }
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!match) {
    return text;
  }
  const [, year, month, day, hour, minute] = match;
  return `${month}/${day} ${hour}:${minute}`;
}

function titleCase(value, fallback = "--") {
  return clean(value, fallback)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function signalId(row, index) {
  return `${row.release_time || "time"}::${row.title || "title"}::${index}`;
}

function normalizeSignals(rows) {
  return rows.map((row, index) => {
    const direction = clean(row.final_expected_direction || row.trust_adjusted_direction || row.expected_direction, "mixed").toLowerCase();
    const status = clean(row.release_status, "unknown").toLowerCase();
    const bull = numberValue(row.final_bullish_probability || row.trust_adjusted_bullish_probability || row.calibrated_bullish_probability, 0.5);
    const bear = numberValue(row.final_bearish_probability || row.trust_adjusted_bearish_probability || row.calibrated_bearish_probability, 1 - bull);
    const confidence = numberValue(row.final_confidence || row.trust_adjusted_confidence || row.confidence, 0);
    return {
      ...row,
      id: signalId(row, index),
      direction,
      status,
      bull,
      bear,
      confidence,
      warningText: clean(row.final_warning || row.trust_warning || row.warning, ""),
      searchText: [
        row.title,
        row.event_family,
        row.catalyst_category,
        row.source,
        row.market_bias_side,
        row.final_warning,
        row.trust_warning,
      ].join(" ").toLowerCase(),
    };
  });
}

function setDataStamp() {
  const count = state.signals.length;
  const statusText = state.status && state.status.finished_at
    ? `status ${state.status.finished_at}`
    : `loaded ${new Date().toLocaleTimeString()}`;
  els.dataStamp.textContent = `${count} signals, ${statusText}`;
}

function renderMetrics() {
  const total = state.signals.length;
  const waiting = state.signals.filter((row) => row.status === "waiting_actual").length;
  const released = state.signals.filter((row) => row.status === "released").length;
  const bearish = state.signals.filter((row) => row.direction === "bearish").length;
  const bullish = state.signals.filter((row) => row.direction === "bullish").length;
  const avgConfidence = total
    ? state.signals.reduce((sum, row) => sum + row.confidence, 0) / total
    : 0;
  const next = state.signals
    .filter((row) => row.status !== "released")
    .sort((a, b) => String(a.release_time).localeCompare(String(b.release_time)))[0];

  const metrics = [
    { label: "Signals", value: total, note: `${released} released, ${waiting} waiting` },
    { label: "Bullish", value: bullish, note: "final direction" },
    { label: "Bearish", value: bearish, note: "final direction" },
    { label: "Avg Confidence", value: percent(avgConfidence, 0), note: "trust adjusted" },
    { label: "Next", value: next ? formatTime(next.release_time) : "--", note: next ? clean(next.title) : "No pending release" },
  ];

  els.metrics.innerHTML = metrics
    .map((item) => `
      <article class="metric">
        <span>${item.label}</span>
        <strong>${item.value}</strong>
        <em title="${item.note}">${item.note}</em>
      </article>
    `)
    .join("");
}

function rangeItem(label, range, formatter) {
  return `
    <div class="range-item">
      <span>${label}</span>
      <strong>${rangeText(range, formatter)}</strong>
    </div>
  `;
}

function renderComponentRanges() {
  const signalRows = state.signals;
  const performanceRows = state.performance.filter((row) =>
    ["overall", "event_family_market_bias", "catalyst_category", "market_bias_side"].includes(row.group_type)
  );
  const trustRows = state.trust.filter((row) =>
    row.usable_for_live_signal === "True" || row.usable_for_live_signal === "true" || row.usable_for_live_signal === true
  );

  const sections = [
    {
      title: "Signal Range",
      items: [
        rangeItem("Bullish Prob.", minMax(signalRows, (row) => row.bull), (v) => percent(v, 0)),
        rangeItem("Confidence", minMax(signalRows, (row) => row.confidence), (v) => percent(v, 0)),
        rangeItem("Trust Weight", minMax(signalRows, (row) => row.trust_weight), (v) => points(v, 2)),
        rangeItem("Surprise", minMax(signalRows, (row) => row.surprise), (v) => plainNumber(v)),
      ],
    },
    {
      title: "Performance Range",
      items: [
        rangeItem("Accuracy", minMax(performanceRows, (row) => row.primary_accuracy), (v) => percent(v, 0)),
        rangeItem("Whipsaw", minMax(performanceRows, (row) => row.whipsaw_rate), (v) => percent(v, 0)),
        rangeItem("Avg Return", minMax(performanceRows, (row) => row.avg_primary_return_pts), (v) => points(v, 1)),
        rangeItem("Samples", minMax(performanceRows, (row) => row.sample_size), (v) => points(v, 0)),
      ],
    },
    {
      title: "Trust Range",
      items: [
        rangeItem("Weight", minMax(trustRows, (row) => row.trust_weight), (v) => points(v, 2)),
        rangeItem("Smoothed Acc.", minMax(trustRows, (row) => row.smoothed_primary_accuracy), (v) => percent(v, 0)),
        rangeItem("Reliability", minMax(trustRows, (row) => row.sample_reliability), (v) => percent(v, 0)),
        rangeItem("Samples", minMax(trustRows, (row) => row.sample_size), (v) => points(v, 0)),
      ],
    },
  ];

  els.componentRanges.innerHTML = sections
    .map((section) => `
      <article class="range-card">
        <h2>${section.title}</h2>
        <div class="range-list">${section.items.join("")}</div>
      </article>
    `)
    .join("");
}

function renderAlerts() {
  const summary = state.alertSummary || {};
  const alerts = Array.isArray(summary.latest_alerts) ? summary.latest_alerts.slice(-5).reverse() : [];
  if (!alerts.length) {
    els.alertPanel.classList.remove("active");
    els.alertPanel.innerHTML = "";
    return;
  }

  const checkedAt = clean(summary.checked_at, "");
  els.alertPanel.classList.add("active");
  els.alertPanel.innerHTML = `
    <div class="alert-head">
      <h2>Latest Alerts</h2>
      <span>${alerts.length} shown${checkedAt ? `, checked ${escapeHtml(checkedAt)}` : ""}</span>
    </div>
    <div class="alert-list">
      ${alerts.map((alert) => {
        const severity = clean(alert.severity, "info").toLowerCase();
        const label = ["high", "medium", "info"].includes(severity) ? severity : "info";
        const title = clean(alert.title || alert.alert_type, "Pipeline Alert");
        const message = clean(alert.message, "");
        const time = formatTime(alert.release_time || alert.alert_time);
        return `
          <div class="alert-item">
            <span class="alert-severity ${escapeHtml(label)}">${escapeHtml(label)}</span>
            <div>
              <strong title="${escapeHtml(title)}">${escapeHtml(title)}</strong>
              <span title="${escapeHtml(message)}">${escapeHtml(message)}</span>
            </div>
            <em>${escapeHtml(time)}</em>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderCategories() {
  const categories = Array.from(new Set(state.signals.map((row) => clean(row.catalyst_category, "")).filter(Boolean))).sort();
  const current = state.filters.category;
  els.categorySelect.innerHTML = [
    '<option value="all">All categories</option>',
    ...categories.map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(titleCase(category))}</option>`),
  ].join("");
  els.categorySelect.value = categories.includes(current) ? current : "all";
  state.filters.category = els.categorySelect.value;
}

function filteredSignals() {
  const query = state.filters.search.trim().toLowerCase();
  return state.signals.filter((row) => {
    if (query && !row.searchText.includes(query)) {
      return false;
    }
    if (state.filters.category !== "all" && clean(row.catalyst_category, "") !== state.filters.category) {
      return false;
    }
    if (state.filters.status !== "all" && row.status !== state.filters.status) {
      return false;
    }
    if (state.filters.direction !== "all" && row.direction !== state.filters.direction) {
      return false;
    }
    return true;
  });
}

function sortRows(rows) {
  const key = state.sortKey;
  const dir = state.sortDir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const numericKeys = new Set(["final_bullish_probability", "final_confidence", "trust_weight"]);
    if (numericKeys.has(key)) {
      return (numberValue(a[key], 0) - numberValue(b[key], 0)) * dir;
    }
    return String(a[key] || "").localeCompare(String(b[key] || "")) * dir;
  });
}

function directionBadge(direction) {
  return `<span class="badge ${escapeHtml(direction)}">${escapeHtml(titleCase(direction))}</span>`;
}

function statusBadge(status) {
  const cls = status === "waiting_actual" ? "waiting" : status === "released" ? "neutral" : "mixed";
  return `<span class="badge ${cls}">${escapeHtml(titleCase(status))}</span>`;
}

function probabilityCell(row) {
  const value = Math.max(0, Math.min(100, row.bull * 100));
  const barClass = row.direction === "bearish" ? "bar bear" : "bar";
  return `
    <div class="prob">
      <span>${percent(row.bull, 0)}</span>
      <div class="${barClass}"><span style="--value:${value}%"></span></div>
    </div>
  `;
}

function boundedPercent(value) {
  return Math.max(0, Math.min(100, numberValue(value, 0) * 100));
}

function renderProbabilityChart() {
  const rows = [...state.signals].sort((a, b) => String(a.release_time).localeCompare(String(b.release_time)));
  if (!rows.length) {
    els.probabilityChart.innerHTML = '<div class="empty">No signal probabilities loaded</div>';
    els.probabilityRange.innerHTML = "";
    return;
  }

  els.probabilityRange.innerHTML = [
    rangeChip("Bull", minMax(rows, (row) => row.bull), (v) => percent(v, 0)),
    rangeChip("Confidence", minMax(rows, (row) => row.confidence), (v) => percent(v, 0)),
    rangeChip("Trust", minMax(rows, (row) => row.trust_weight), (v) => points(v, 2)),
  ].join("");

  const width = 980;
  const height = 248;
  const left = 52;
  const right = 28;
  const top = 26;
  const bottom = 44;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const xStep = rows.length > 1 ? plotWidth / (rows.length - 1) : 0;
  const plotPoints = rows.map((row, index) => {
    const x = left + index * xStep;
    const y = top + (1 - row.bull) * plotHeight;
    return { row, x, y };
  });
  const path = plotPoints.map((point, index) => `${index ? "L" : "M"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
  const midY = top + 0.5 * plotHeight;

  els.probabilityChart.innerHTML = `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Final bullish probability timeline">
      <line class="chart-axis" x1="${left}" y1="${top}" x2="${left}" y2="${height - bottom}"></line>
      <line class="chart-axis" x1="${left}" y1="${height - bottom}" x2="${width - right}" y2="${height - bottom}"></line>
      <line class="chart-midline" x1="${left}" y1="${midY}" x2="${width - right}" y2="${midY}"></line>
      <text class="chart-label" x="12" y="${top + 4}">100%</text>
      <text class="chart-label" x="20" y="${midY + 4}">50%</text>
      <text class="chart-label" x="26" y="${height - bottom + 4}">0%</text>
      <path class="chart-line" d="${path}"></path>
      ${plotPoints.map((point) => `
        <circle class="chart-point ${escapeHtml(point.row.direction)}" cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="5">
          <title>${escapeHtml(clean(point.row.title))}: ${percent(point.row.bull, 1)}</title>
        </circle>
      `).join("")}
      ${plotPoints.map((point, index) => {
        if (index % Math.ceil(plotPoints.length / 6) !== 0 && index !== plotPoints.length - 1) {
          return "";
        }
        return `<text class="chart-label" x="${point.x.toFixed(1)}" y="${height - 16}" text-anchor="middle">${escapeHtml(formatTime(point.row.release_time))}</text>`;
      }).join("")}
    </svg>
  `;
}

function renderSignals() {
  const rows = sortRows(filteredSignals());
  if (!state.selectedId && rows.length) {
    state.selectedId = rows[0].id;
  }

  els.signalsBody.innerHTML = rows.length
    ? rows.map((row) => `
      <tr data-id="${escapeHtml(row.id)}" class="${row.id === state.selectedId ? "selected" : ""}">
        <td>${formatTime(row.release_time)}</td>
        <td>
          <div class="title-cell">
            <strong title="${escapeHtml(clean(row.title))}">${escapeHtml(clean(row.title))}</strong>
            <span>${escapeHtml(titleCase(row.event_family))} / ${escapeHtml(titleCase(row.catalyst_category))}</span>
          </div>
        </td>
        <td>${directionBadge(row.direction)}</td>
        <td>${probabilityCell(row)}</td>
        <td>${percent(row.confidence, 0)}</td>
        <td>${points(row.trust_weight, 2)}</td>
        <td>${statusBadge(row.status)}</td>
      </tr>
    `).join("")
    : '<tr><td colspan="7"><div class="empty">No matching signals</div></td></tr>';

  renderDetail();
}

function detailDatum(label, value) {
  return `
    <div class="datum">
      <span>${label}</span>
      <strong>${escapeHtml(clean(value))}</strong>
    </div>
  `;
}

function renderDetail() {
  const row = state.signals.find((item) => item.id === state.selectedId) || filteredSignals()[0];
  if (!row) {
    els.detailPanel.innerHTML = '<div class="empty">No signal selected</div>';
    return;
  }

  state.selectedId = row.id;
  const warning = row.warningText ? `<div class="note">${escapeHtml(row.warningText)}</div>` : "";
  const ruleNote = clean(row.market_rule_note, "");
  const trustNote = clean(row.trust_note, "");

  els.detailPanel.innerHTML = `
    <div class="detail-head">
      <div class="pill-row">
        ${directionBadge(row.direction)}
        ${statusBadge(row.status)}
        <span class="pill ${escapeHtml(row.market_bias_label || row.direction)}">${escapeHtml(titleCase(row.market_bias_side))}</span>
      </div>
      <h2>${escapeHtml(clean(row.title))}</h2>
      <div class="prob">
        <span>${percent(row.bull, 1)}</span>
        <div class="${row.direction === "bearish" ? "bar bear" : "bar"}"><span style="--value:${Math.max(0, Math.min(100, row.bull * 100))}%"></span></div>
      </div>
    </div>
    <div class="detail-grid">
      ${detailDatum("Time", formatTime(row.release_time))}
      ${detailDatum("Confidence", `${percent(row.confidence, 0)} ${titleCase(row.final_confidence_label || row.trust_adjusted_confidence_label || row.confidence_label)}`)}
      ${detailDatum("Actual", row.actual)}
      ${detailDatum("Forecast", row.forecast)}
      ${detailDatum("Previous", row.previous)}
      ${detailDatum("Surprise", points(row.surprise, 2))}
      ${detailDatum("Trust Weight", points(row.trust_weight, 3))}
      ${detailDatum("Trust Samples", row.trust_sample_size)}
    </div>
    ${ruleNote ? `<div class="note">${escapeHtml(ruleNote)}</div>` : ""}
    ${trustNote ? `<div class="note">${escapeHtml(trustNote)}</div>` : ""}
    ${warning}
  `;
}

function renderPerformance() {
  const preferred = state.performance
    .filter((row) => ["overall", "event_family_market_bias", "catalyst_category", "market_bias_side"].includes(row.group_type))
    .sort((a, b) => numberValue(b.sample_size, 0) - numberValue(a.sample_size, 0));

  els.performanceBody.innerHTML = preferred.length
    ? preferred.map((row) => `
      <tr>
        <td>${escapeHtml(titleCase(row.group_type))}</td>
        <td>${escapeHtml(titleCase(row.event_family))}</td>
        <td>${escapeHtml(titleCase(row.catalyst_category))}</td>
        <td>${escapeHtml(titleCase(row.market_bias_side))}</td>
        <td>${escapeHtml(clean(row.sample_size))}</td>
        <td>${percent(row.primary_accuracy, 0)}</td>
        <td>${percent(row.whipsaw_rate, 0)}</td>
        <td>${points(row.avg_return_60m_pts || row.avg_primary_return_pts, 1)}</td>
      </tr>
    `).join("")
    : '<tr><td colspan="8"><div class="empty">No performance rows loaded</div></td></tr>';
}

function renderPerformanceChart() {
  const rows = state.performance
    .filter((row) => row.group_type === "event_family_market_bias")
    .sort((a, b) => numberValue(b.sample_size, 0) - numberValue(a.sample_size, 0))
    .slice(0, 10);

  els.performanceRange.innerHTML = [
    rangeChip("Accuracy", minMax(rows, (row) => row.primary_accuracy), (v) => percent(v, 0)),
    rangeChip("Whipsaw", minMax(rows, (row) => row.whipsaw_rate), (v) => percent(v, 0)),
    rangeChip("Return", minMax(rows, (row) => row.avg_primary_return_pts), (v) => points(v, 1)),
  ].join("");

  els.performanceChart.innerHTML = rows.length
    ? rows.map((row) => {
      const accuracy = boundedPercent(row.primary_accuracy);
      const whipsaw = boundedPercent(row.whipsaw_rate);
      const fillClass = accuracy >= 60 ? "" : accuracy >= 40 ? "warn" : "fade";
      const label = `${titleCase(row.event_family)} / ${titleCase(row.market_bias_side)}`;
      return `
        <div class="chart-row-item">
          <div class="chart-row-label">
            <strong title="${escapeHtml(label)}">${escapeHtml(label)}</strong>
            <span>${escapeHtml(clean(row.sample_size))} samples, ${points(row.avg_primary_return_pts, 1)} pts avg</span>
          </div>
          <div class="chart-track" title="Accuracy ${percent(row.primary_accuracy, 0)}, whipsaw ${percent(row.whipsaw_rate, 0)}">
            <span class="chart-fill ${fillClass}" style="--value:${accuracy}%"></span>
            <span class="chart-marker" style="--value:${whipsaw}%"></span>
          </div>
          <div class="chart-value">${percent(row.primary_accuracy, 0)}</div>
        </div>
      `;
    }).join("")
    : '<div class="empty">No event-family performance rows loaded</div>';
}

function renderTrust() {
  const rows = state.trust
    .filter((row) => row.usable_for_live_signal === "True" || row.usable_for_live_signal === "true" || row.usable_for_live_signal === true)
    .sort((a, b) => numberValue(a.trust_weight, 0) - numberValue(b.trust_weight, 0));

  els.trustBody.innerHTML = rows.length
    ? rows.map((row) => `
      <tr>
        <td>${escapeHtml(titleCase(row.group_type))}</td>
        <td>${escapeHtml(titleCase(row.event_family))}</td>
        <td>${escapeHtml(titleCase(row.market_bias_side))}</td>
        <td>${escapeHtml(clean(row.sample_size))}</td>
        <td>${percent(row.smoothed_primary_accuracy, 0)}</td>
        <td>${percent(row.whipsaw_rate, 0)}</td>
        <td>${points(row.trust_weight, 2)}</td>
        <td>${escapeHtml(titleCase(row.trust_label))}</td>
      </tr>
    `).join("")
    : '<tr><td colspan="8"><div class="empty">No trust rows loaded</div></td></tr>';
}

function renderTrustChart() {
  const rows = state.trust
    .filter((row) => row.usable_for_live_signal === "True" || row.usable_for_live_signal === "true" || row.usable_for_live_signal === true)
    .sort((a, b) => numberValue(a.trust_weight, 0) - numberValue(b.trust_weight, 0))
    .slice(0, 12);

  els.trustRange.innerHTML = [
    rangeChip("Weight", minMax(rows, (row) => row.trust_weight), (v) => points(v, 2)),
    rangeChip("Accuracy", minMax(rows, (row) => row.smoothed_primary_accuracy), (v) => percent(v, 0)),
    rangeChip("Reliability", minMax(rows, (row) => row.sample_reliability), (v) => percent(v, 0)),
  ].join("");

  els.trustChart.innerHTML = rows.length
    ? rows.map((row) => {
      const weight = numberValue(row.trust_weight, 1);
      const scaled = Math.max(0, Math.min(100, ((weight - 0.25) / 1.10) * 100));
      const fillClass = weight >= 1.05 ? "" : weight >= 0.75 ? "warn" : "fade";
      const label = [
        titleCase(row.event_family, ""),
        titleCase(row.catalyst_category, ""),
        titleCase(row.market_bias_side, ""),
        titleCase(row.confidence_label, ""),
      ].filter((part) => part && part !== "--").join(" / ") || titleCase(row.group_type);
      return `
        <div class="chart-row-item">
          <div class="chart-row-label">
            <strong title="${escapeHtml(label)}">${escapeHtml(label)}</strong>
            <span>${escapeHtml(titleCase(row.group_type))}, ${escapeHtml(clean(row.sample_size))} samples</span>
          </div>
          <div class="chart-track" title="${escapeHtml(clean(row.trust_note))}">
            <span class="chart-fill ${fillClass}" style="--value:${scaled}%"></span>
          </div>
          <div class="chart-value">${points(row.trust_weight, 2)}</div>
        </div>
      `;
    }).join("")
    : '<div class="empty">No trust weights loaded</div>';
}

function renderAll() {
  setDataStamp();
  renderMetrics();
  renderComponentRanges();
  renderAlerts();
  renderCategories();
  renderProbabilityChart();
  renderSignals();
  renderPerformanceChart();
  renderPerformance();
  renderTrustChart();
  renderTrust();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadAll() {
  els.dataStamp.textContent = "Loading data";
  try {
    const [signals, performance, trust, status, alertSummary] = await Promise.all([
      fetchCsv(DATA_PATHS.signals),
      fetchCsv(DATA_PATHS.performance),
      fetchCsv(DATA_PATHS.trust),
      fetchJson(DATA_PATHS.status).catch(() => null),
      fetchJson(DATA_PATHS.alerts).catch(() => null),
    ]);
    state.signals = normalizeSignals(signals);
    state.performance = performance;
    state.trust = trust;
    state.status = status;
    state.alertSummary = alertSummary;
    state.selectedId = state.signals[0]?.id || "";
    renderAll();
  } catch (error) {
    els.dataStamp.textContent = `Data load failed: ${error.message}`;
    els.signalsBody.innerHTML = '<tr><td colspan="7"><div class="empty">Unable to load dashboard data</div></td></tr>';
    els.detailPanel.innerHTML = '<div class="empty">CSV files unavailable</div>';
  }
}

function setActiveTab(tab) {
  state.activeTab = tab;
  els.tabs.forEach((button) => button.classList.toggle("active", button.dataset.tab === tab));
  els.views.forEach((view) => view.classList.toggle("active", view.id === `${tab}View`));
  els.signalFilters.style.display = tab === "signals" ? "" : "none";
}

function bindEvents() {
  els.reloadBtn.addEventListener("click", loadAll);

  els.tabs.forEach((button) => {
    button.addEventListener("click", () => setActiveTab(button.dataset.tab));
  });

  els.searchInput.addEventListener("input", (event) => {
    state.filters.search = event.target.value;
    renderSignals();
  });

  els.categorySelect.addEventListener("change", (event) => {
    state.filters.category = event.target.value;
    renderSignals();
  });

  els.segments.forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.filter;
      state.filters[key] = button.dataset.value;
      els.segments
        .filter((item) => item.dataset.filter === key)
        .forEach((item) => item.classList.toggle("active", item === button));
      renderSignals();
    });
  });

  els.signalsBody.addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-id]");
    if (!row) {
      return;
    }
    state.selectedId = row.dataset.id;
    renderSignals();
  });

  els.sortableHeaders.forEach((header) => {
    header.addEventListener("click", () => {
      const nextKey = header.dataset.sort;
      if (state.sortKey === nextKey) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = nextKey;
        state.sortDir = nextKey === "release_time" ? "asc" : "desc";
      }
      renderSignals();
    });
  });
}

bindEvents();
loadAll();
