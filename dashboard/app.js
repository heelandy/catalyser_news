const DATA_PATHS = {
  signals: "../macro_live_signal_current.csv",
  performance: "../macro_signal_performance.csv",
  trust: "../macro_signal_trust_weights.csv",
  status: "../macro_pipeline_status.json",
  alerts: "../macro_pipeline_alert_summary.json",
  news: "../macro_news_feed.csv",
  newsSummary: "../macro_news_feed_summary.json",
};

const API_PATHS = {
  emailStatus: "../api/email-status",
  testEmail: "../api/test-email",
};

const DISPLAY_TIME_ZONE = "America/New_York";
const DISPLAY_TIME_ZONE_LABEL = "ET";
const TIME_FORMATTER = new Intl.DateTimeFormat("en-US", {
  timeZone: DISPLAY_TIME_ZONE,
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const UTC_TIME_FORMATTER = new Intl.DateTimeFormat("en-US", {
  timeZone: "UTC",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const state = {
  signals: [],
  performance: [],
  trust: [],
  news: [],
  newsSummary: null,
  status: null,
  alertSummary: null,
  visibleAlerts: [],
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
  staleBanner: document.querySelector("#staleBanner"),
  alertPopupLayer: document.querySelector("#alertPopupLayer"),
  reloadBtn: document.querySelector("#reloadBtn"),
  emailBtn: document.querySelector("#emailBtn"),
  emailDialog: document.querySelector("#emailDialog"),
  emailConfigSummary: document.querySelector("#emailConfigSummary"),
  emailRecipient: document.querySelector("#emailRecipient"),
  emailConfigGrid: document.querySelector("#emailConfigGrid"),
  emailTestResult: document.querySelector("#emailTestResult"),
  sendTestEmailBtn: document.querySelector("#sendTestEmailBtn"),
  metrics: document.querySelector("#metrics"),
  componentRanges: document.querySelector("#componentRanges"),
  alertPanel: document.querySelector("#alertPanel"),
  newsPanel: document.querySelector("#newsPanel"),
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

function surpriseText(value) {
  const n = numberValue(value);
  if (!Number.isFinite(n)) {
    return clean(value);
  }
  const sign = n > 0 ? "+" : "";
  return sign + n.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function parseReleaseDate(value) {
  const text = clean(value, "");
  if (!text) {
    return null;
  }
  const looksIso = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(text);
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(text);
  const normalized = looksIso && !hasTimezone ? `${text}Z` : text;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function timeParts(formatter, date) {
  return Object.fromEntries(formatter.formatToParts(date).map((part) => [part.type, part.value]));
}

function formatTime(value, options = {}) {
  const text = clean(value, "");
  const date = parseReleaseDate(text);
  if (!date) {
    return text || "--";
  }
  const parts = timeParts(TIME_FORMATTER, date);
  const base = `${parts.month}/${parts.day} ${parts.hour}:${parts.minute}`;
  return options.withZone === false ? base : `${base} ${DISPLAY_TIME_ZONE_LABEL}`;
}

function formatTimeTitle(value) {
  const text = clean(value, "");
  const date = parseReleaseDate(text);
  if (!date) {
    return text || "--";
  }
  const local = formatTime(text);
  const utc = timeParts(UTC_TIME_FORMATTER, date);
  return `${local} / ${utc.month}/${utc.day} ${utc.hour}:${utc.minute} UTC`;
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
    const releaseRuleDirection = clean(row.release_rule_direction, "unknown").toLowerCase();
    const releaseRuleLabel = clean(row.release_rule_label, titleCase(row.market_bias_side || "release rule"));
    const regimeDirection = clean(row.live_market_regime_direction, "mixed").toLowerCase();
    const tradeState = clean(row.trade_state, "watch_only").toLowerCase();
    const regimeConflict = clean(row.market_regime_conflict, "none").toLowerCase();
    const regimeWarning = regimeConflict !== "none" ? clean(row.trade_state_reason || row.live_market_regime_reason, "") : "";
    return {
      ...row,
      id: signalId(row, index),
      direction,
      status,
      bull,
      bear,
      confidence,
      releaseRuleDirection,
      releaseRuleLabel,
      regimeDirection,
      tradeState,
      regimeConflict,
      warningText: clean(row.final_warning || row.trust_warning || row.warning, ""),
      regimeWarning,
      searchText: [
        row.title,
        row.event_family,
        row.catalyst_category,
        row.source,
        row.market_bias_side,
        row.release_rule_label,
        row.live_market_regime,
        row.live_market_regime_reason,
        row.trade_state,
        row.trade_state_reason,
        row.market_regime_conflict,
        row.final_warning,
        row.trust_warning,
        row.daily_confirmation_match,
        row.daily_confirmation_group_key,
      ].join(" ").toLowerCase(),
    };
  });
}

function normalizeNews(rows) {
  return rows
    .map((row) => {
      const direction = clean(row.direction, "mixed").toLowerCase();
      const confidence = numberValue(row.confidence, 0);
      const published = parseReleaseDate(row.published_at);
      return {
        ...row,
        direction: ["bullish", "bearish", "mixed"].includes(direction) ? direction : "mixed",
        confidence,
        published,
        validUntil: parseReleaseDate(row.valid_until),
        themes: clean(row.themes || row.categories, "").split(";").map((part) => part.trim()).filter(Boolean),
        riskFlags: clean(row.risk_flags, "").split(";").map((part) => part.trim()).filter(Boolean),
      };
    })
    .sort((a, b) => (b.published?.getTime() || 0) - (a.published?.getTime() || 0));
}

function setDataStamp() {
  const count = state.signals.length;
  const statusText = state.status && state.status.finished_at
    ? `status ${state.status.finished_at}`
    : `loaded ${new Date().toLocaleTimeString()}`;
  els.dataStamp.textContent = `${count} signals, ${statusText}`;
}

function renderStaleBanner() {
  const finishedAt = clean(state.status?.finished_at, "");
  const age = ageSeconds(finishedAt);
  const loopSeconds = numberValue(state.status?.loop_seconds, 60);
  const watchMinutes = state.status?.watch_releases ? 35 : 0;
  const staleThreshold = Math.max(300, loopSeconds * 3 + watchMinutes * 60);
  const warnings = [];

  if (!state.status) {
    warnings.push("Pipeline status file could not be loaded. The live runner may not be running.");
  } else if (!Number.isFinite(age)) {
    warnings.push("Pipeline status has no finish time yet.");
  } else if (age > staleThreshold) {
    warnings.push(`Pipeline data is stale: last cycle finished ${ageLabel(age)}. The live runner may be stopped or outside its 7:00-18:00 window.`);
  }
  if (state.status?.failed_stage) {
    warnings.push(`Last cycle failed: ${clean(state.status.failed_stage)}`);
  }

  els.staleBanner.hidden = !warnings.length;
  els.staleBanner.innerHTML = warnings.map((warning) => `<div>${escapeHtml(warning)}</div>`).join("");
}

function renderMetrics() {
  const total = state.signals.length;
  const waiting = state.signals.filter((row) => row.status === "waiting_actual").length;
  const released = state.signals.filter((row) => row.status === "released").length;
  const bearish = state.signals.filter((row) => row.direction === "bearish").length;
  const bullish = state.signals.filter((row) => row.direction === "bullish").length;
  const conflicts = state.signals.filter((row) => row.regimeConflict !== "none").length;
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
    { label: "Conflicts", value: conflicts, note: "rule vs regime" },
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
  state.visibleAlerts = alerts;
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
      <span>${alerts.length} shown${checkedAt ? `, checked ${escapeHtml(checkedAt)}` : ""}, click an alert for details</span>
    </div>
    <div class="alert-list">
      ${alerts.map((alert, index) => {
        const severity = clean(alert.severity, "info").toLowerCase();
        const label = ["high", "medium", "info"].includes(severity) ? severity : "info";
        const title = clean(alert.title || alert.alert_type, "Pipeline Alert");
        const message = clean(alert.message, "");
        const time = formatTime(alert.release_time || alert.alert_time);
        return `
          <button class="alert-item" type="button" data-alert-index="${index}">
            <span class="alert-severity ${escapeHtml(label)}">${escapeHtml(label)}</span>
            <span class="alert-copy">
              <strong title="${escapeHtml(title)}">${escapeHtml(title)}</strong>
              <span title="${escapeHtml(message)}">${escapeHtml(message)}</span>
            </span>
            <em>${escapeHtml(time)}</em>
          </button>
        `;
      }).join("")}
    </div>
  `;
}

function openAlertDetails(alert) {
  const row = state.signals.find((item) => clean(item.title, "") === clean(alert.title, ""));
  if (row) {
    state.selectedId = row.id;
    setActiveTab("signals");
    renderSignals();
  }
  popupState.queue.unshift(alert);
  showNextAlertPopup();
}

const ALERT_SEEN_KEY = "nqCatalystSeenAlerts";
const ALERT_POPUP_MAX_AGE_MINUTES = 30;
const popupState = {
  queue: [],
  current: null,
  seen: loadSeenAlerts(),
};

function loadSeenAlerts() {
  try {
    const raw = JSON.parse(localStorage.getItem(ALERT_SEEN_KEY) || "[]");
    return new Set(Array.isArray(raw) ? raw : []);
  } catch {
    return new Set();
  }
}

function saveSeenAlerts(seen) {
  try {
    localStorage.setItem(ALERT_SEEN_KEY, JSON.stringify(Array.from(seen).slice(-200)));
  } catch {
    /* storage unavailable; popups may repeat after reload */
  }
}

function alertKey(alert) {
  return [alert.alert_time, alert.alert_type, alert.title].map((part) => clean(part, "")).join("|");
}

function popupDirection(direction) {
  if (direction === "bullish") {
    return { label: "Long", cls: "bullish", arrow: "↗" };
  }
  if (direction === "bearish") {
    return { label: "Short", cls: "bearish", arrow: "↘" };
  }
  return { label: "Mixed", cls: "mixed", arrow: "→" };
}

function popupTile(label, value, direction) {
  const cls = ["bullish", "bearish"].includes(direction) ? direction : "mixed";
  return `
    <div class="popup-tile ${escapeHtml(cls)}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `;
}

function tradeStateTone(row) {
  if (!row) {
    return "mixed";
  }
  if (row.regimeConflict !== "none" || row.tradeState.includes("wait")) {
    return "mixed";
  }
  if (row.tradeState.includes("long")) {
    return "bullish";
  }
  if (row.tradeState.includes("short")) {
    return "bearish";
  }
  return "mixed";
}

function renderAlertPopupCard(alert) {
  const row = state.signals.find((item) => clean(item.title, "") === clean(alert.title, "")) || null;
  const direction = clean(alert.current_direction, row?.direction || "mixed").toLowerCase();
  const dir = popupDirection(direction);
  const probability = numberValue(alert.current_bullish_probability, row ? row.bull : NaN);
  const severity = clean(alert.severity, "info").toLowerCase();
  const severityCls = ["high", "medium", "info"].includes(severity) ? severity : "info";
  const alertType = titleCase(alert.alert_type, "Pipeline Alert");
  const title = clean(alert.title, "Pipeline Alert");
  const category = titleCase(alert.catalyst_category || row?.catalyst_category, "");
  const message = clean(alert.message, "");
  const conflict = row ? row.regimeConflict !== "none" : false;
  const showCaution = conflict || severityCls === "high" || direction === "mixed";
  const rawCaution = clean(row?.regimeWarning || row?.warningText, "");
  const cautionDetail = rawCaution && !rawCaution.includes(" ")
    ? rawCaution.split(";").map((part) => titleCase(part, "")).filter(Boolean).join(" · ")
    : rawCaution || "Signal is active, but higher-level bias is mixed. Wait for clean confirmation and manage risk.";
  const releaseRule = row ? displayRuleLabel(row).replace(/^Rule\s+/i, "") : "Unknown";
  const regime = row ? titleCase(row.regimeDirection) : "Mixed";
  const tradeState = row ? displayTradeState(row) : "Watch";

  return `
    <div class="alert-popup-backdrop" data-popup-dismiss="true"></div>
    <article class="alert-popup ${escapeHtml(dir.cls)}" role="alertdialog" aria-label="New pipeline alert">
      <header class="alert-popup-top">
        <div class="alert-popup-id">
          <span class="popup-direction ${escapeHtml(dir.cls)}">${dir.arrow} ${escapeHtml(dir.label)}</span>
          <span class="popup-pill">${escapeHtml(alertType)}</span>
          <div class="alert-popup-chips">
            ${category && category !== "--" ? `<span class="popup-chip">${escapeHtml(category)}</span>` : ""}
            <strong class="popup-symbol" title="${escapeHtml(title)}">${escapeHtml(title)}</strong>
          </div>
        </div>
        <div class="alert-popup-price">
          <span>Bull Probability</span>
          <strong>${percent(probability, 1)}</strong>
          <em title="${escapeHtml(formatTimeTitle(alert.release_time))}">${escapeHtml(formatTime(alert.alert_time))}</em>
        </div>
      </header>
      ${showCaution ? `
        <div class="popup-caution">
          <strong>Mixed Bias — Use Caution</strong>
          <span>${escapeHtml(cautionDetail)}</span>
        </div>
      ` : ""}
      ${message ? `<div class="popup-message">${escapeHtml(message)}</div>` : ""}
      <div class="alert-popup-tiles">
        ${popupTile("Release Rule", releaseRule, row?.releaseRuleDirection || "mixed")}
        ${popupTile("Live Regime", regime, row?.regimeDirection || "mixed")}
        ${popupTile("Trade State", tradeState, tradeStateTone(row))}
      </div>
      <footer class="alert-popup-foot">
        <span class="alert-severity ${escapeHtml(severityCls)}">${escapeHtml(severityCls)}</span>
        <span class="popup-release">Release ${escapeHtml(formatTime(alert.release_time))}</span>
        <button class="button popup-dismiss" type="button" data-popup-dismiss="true">Dismiss</button>
      </footer>
    </article>
  `;
}

function showNextAlertPopup() {
  const alert = popupState.queue.shift();
  popupState.current = alert || null;
  if (!alert) {
    els.alertPopupLayer.hidden = true;
    els.alertPopupLayer.innerHTML = "";
    return;
  }
  els.alertPopupLayer.hidden = false;
  els.alertPopupLayer.innerHTML = renderAlertPopupCard(alert);
  els.alertPopupLayer.querySelectorAll("[data-popup-dismiss]").forEach((element) => {
    element.addEventListener("click", showNextAlertPopup);
  });
}

function maybeShowAlertPopups() {
  const summary = state.alertSummary || {};
  const alerts = Array.isArray(summary.latest_alerts) ? summary.latest_alerts : [];
  if (new URLSearchParams(window.location.search).has("popupPreview")) {
    if (alerts.length && !popupState.current) {
      popupState.queue.push(alerts[alerts.length - 1]);
      showNextAlertPopup();
    }
    return;
  }
  const severityRank = { high: 0, medium: 1, info: 2 };
  const fresh = [];
  let seenChanged = false;

  alerts.forEach((alert) => {
    const key = alertKey(alert);
    if (popupState.seen.has(key)) {
      return;
    }
    popupState.seen.add(key);
    seenChanged = true;
    const age = ageSeconds(alert.alert_time);
    if (Number.isFinite(age) && age <= ALERT_POPUP_MAX_AGE_MINUTES * 60) {
      fresh.push(alert);
    }
  });

  if (seenChanged) {
    saveSeenAlerts(popupState.seen);
  }
  if (!fresh.length) {
    return;
  }

  fresh.sort((a, b) => {
    const bySeverity = (severityRank[clean(a.severity, "info").toLowerCase()] ?? 2)
      - (severityRank[clean(b.severity, "info").toLowerCase()] ?? 2);
    if (bySeverity !== 0) {
      return bySeverity;
    }
    return String(b.alert_time || "").localeCompare(String(a.alert_time || ""));
  });
  popupState.queue.push(...fresh.slice(0, 6));
  if (!popupState.current) {
    showNextAlertPopup();
  }
}

function ageSeconds(value) {
  const date = parseReleaseDate(value);
  if (!date) {
    return NaN;
  }
  return Math.max(0, (Date.now() - date.getTime()) / 1000);
}

function ageLabel(seconds) {
  if (!Number.isFinite(seconds)) {
    return "unknown age";
  }
  if (seconds < 90) {
    return `${Math.round(seconds)}s ago`;
  }
  const minutes = seconds / 60;
  if (minutes < 90) {
    return `${Math.round(minutes)}m ago`;
  }
  return `${(minutes / 60).toFixed(1)}h ago`;
}

function renderNews() {
  const rows = state.news.slice(0, 8);
  const summary = state.newsSummary || {};
  const counts = rows.reduce((out, row) => {
    out[row.direction] = (out[row.direction] || 0) + 1;
    return out;
  }, {});
  const checkedAt = clean(summary.checked_at, "");
  const checkedAge = ageSeconds(checkedAt);
  const loopSeconds = numberValue(state.status?.loop_seconds, 60);
  const staleThreshold = Math.max(180, loopSeconds * 3);
  const sourceUsed = clean(summary.source_used || state.status?.news_feed_provider, "unknown");
  const bias = clean(summary.news_bias, rows[0]?.direction || "mixed").toLowerCase();
  const biasClass = ["bullish", "bearish", "mixed"].includes(bias) ? bias : "mixed";
  const biasConfidence = numberValue(summary.news_bias_confidence, NaN);
  const themes = Array.isArray(summary.themes) && summary.themes.length
    ? summary.themes
    : Array.from(new Set(rows.flatMap((row) => row.themes))).slice(0, 6);
  const riskFlags = Array.isArray(summary.risk_flags) && summary.risk_flags.length
    ? summary.risk_flags
    : Array.from(new Set(rows.flatMap((row) => row.riskFlags))).slice(0, 6);
  const warnings = [];
  if (!state.newsSummary) {
    warnings.push("News summary JSON could not be loaded.");
  } else if (summary.load_error) {
    warnings.push(`News summary JSON could not be loaded: ${summary.load_error}`);
  }
  if (Number.isFinite(checkedAge) && checkedAge > staleThreshold) {
    warnings.push(`News feed stale: last checked ${ageLabel(checkedAge)}.`);
  }
  if (!Number.isFinite(checkedAge)) {
    warnings.push("News feed check time is unavailable.");
  }
  if (!rows.length) {
    warnings.push("No interpreted headlines are available.");
  }
  if (Array.isArray(summary.errors)) {
    warnings.push(...summary.errors.filter(Boolean).slice(0, 3));
  }

  els.newsPanel.classList.add("active");
  els.newsPanel.innerHTML = `
    <div class="news-head">
      <div>
        <h2>Interpreted News</h2>
        <span>${rows.length} latest, ${counts.bearish || 0} bearish / ${counts.bullish || 0} bullish / source ${escapeHtml(sourceUsed)} / checked ${escapeHtml(ageLabel(checkedAge))}</span>
      </div>
      <div class="news-actions">
        <span class="badge ${escapeHtml(biasClass)}">${escapeHtml(titleCase(bias))}${Number.isFinite(biasConfidence) ? ` ${percent(biasConfidence, 0)}` : ""}</span>
        <a class="button ghost" href="../macro_news_feed.csv">News CSV</a>
      </div>
    </div>
    ${warnings.length ? `
      <div class="news-warning">
        ${warnings.map((warning) => `<div>${escapeHtml(warning)}</div>`).join("")}
      </div>
    ` : ""}
    <div class="news-meta">
      ${themes.slice(0, 6).map((theme) => `<span>${escapeHtml(titleCase(theme))}</span>`).join("")}
      ${riskFlags.slice(0, 6).map((flag) => `<span class="risk">${escapeHtml(titleCase(flag))}</span>`).join("")}
    </div>
    <div class="news-list">
      ${rows.length ? rows.map((row) => {
        const url = clean(row.url, "");
        const title = clean(row.title, "Untitled news");
        const source = clean(row.source || row.provider, "news");
        const reason = clean(row.reason, "");
        const time = row.published ? formatTime(row.published_at) : "--";
        const rowMeta = [
          source,
          time,
          `confidence ${percent(row.confidence, 0)}`,
          row.themes.length ? `themes ${row.themes.slice(0, 3).join(", ")}` : "",
        ].filter(Boolean).join(" / ");
        const content = `
          <span class="badge ${escapeHtml(row.direction)}">${escapeHtml(titleCase(row.direction))}</span>
          <div class="news-copy">
            <strong title="${escapeHtml(title)}">${escapeHtml(title)}</strong>
            <span title="${escapeHtml(reason)}">${escapeHtml(rowMeta)}</span>
            ${reason ? `<em title="${escapeHtml(reason)}">${escapeHtml(reason)}</em>` : ""}
          </div>
        `;
        return url
          ? `<a class="news-item" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${content}</a>`
          : `<div class="news-item">${content}</div>`;
      }).join("") : '<div class="news-empty">Waiting for the next successful news pull.</div>'}
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

function displayRuleLabel(row) {
  const source = clean(row.release_rule_side || row.market_bias_side || "", "").toLowerCase();
  if (source.includes("positive")) {
    return "Rule Positive";
  }
  if (source.includes("negative")) {
    return "Rule Negative";
  }
  if (source.includes("neutral")) {
    return "Rule Neutral";
  }
  if (source.includes("unknown")) {
    return "Rule Unknown";
  }
  return clean(row.releaseRuleLabel, "Rule Unknown").replace(/^Release-rule\s+/i, "Rule ");
}

function ruleBadge(row) {
  const cls = ["bullish", "bearish", "mixed"].includes(row.releaseRuleDirection) ? row.releaseRuleDirection : "unknown";
  return `<span class="badge ${escapeHtml(cls)}" title="${escapeHtml(row.releaseRuleLabel)}">${escapeHtml(displayRuleLabel(row))}</span>`;
}

function displayTradeState(row) {
  const stateLabel = clean(row.tradeState, "watch_only");
  const labels = {
    no_long_wait_for_reclaim: "No Long",
    no_short_wait_for_breakdown: "No Short",
    short_only_after_confirmation: "Short Confirm",
    long_only_after_confirmation: "Long Confirm",
    wait_for_bearish_confirmation: "Wait Bearish",
    wait_for_bullish_confirmation: "Wait Bullish",
    wait_for_actual: "Wait Actual",
    watch_only: "Watch",
  };
  return labels[stateLabel] || titleCase(stateLabel);
}

function tradeStateBadge(row) {
  const conflict = row.regimeConflict !== "none";
  const cls = conflict ? "bearish" : row.tradeState.includes("wait") ? "waiting" : row.tradeState.includes("long") ? "bullish" : row.tradeState.includes("short") ? "bearish" : "mixed";
  return `<span class="badge ${escapeHtml(cls)}" title="${escapeHtml(clean(row.trade_state_reason))}">${escapeHtml(displayTradeState(row))}</span>`;
}

function regimePill(row) {
  const cls = ["bullish", "bearish", "mixed"].includes(row.regimeDirection) ? row.regimeDirection : "mixed";
  return `<span class="pill ${escapeHtml(cls)}" title="${escapeHtml(clean(row.live_market_regime_reason))}">${escapeHtml(titleCase(row.live_market_regime || row.regimeDirection))}</span>`;
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
        return `<text class="chart-label" x="${point.x.toFixed(1)}" y="${height - 16}" text-anchor="middle">${escapeHtml(formatTime(point.row.release_time, { withZone: false }))}</text>`;
      }).join("")}
    </svg>
  `;
}

function rowSummaryTitle(row) {
  return [
    clean(row.title),
    `${titleCase(row.direction)} ${percent(row.bull, 0)} bull`,
    `confidence ${percent(row.confidence, 0)}`,
    displayTradeState(row),
    titleCase(row.status),
  ].join(" | ");
}

function renderSignals() {
  const rows = sortRows(filteredSignals());
  if (!state.selectedId && rows.length) {
    state.selectedId = rows[0].id;
  }

  const wrap = els.signalsBody.closest(".table-wrap");
  const scrollTop = wrap ? wrap.scrollTop : 0;
  const scrollLeft = wrap ? wrap.scrollLeft : 0;

  els.signalsBody.innerHTML = rows.length
    ? rows.map((row) => `
      <tr data-id="${escapeHtml(row.id)}" class="${row.id === state.selectedId ? "selected" : ""}" title="${escapeHtml(rowSummaryTitle(row))}">
        <td title="${escapeHtml(formatTimeTitle(row.release_time))}">${formatTime(row.release_time)}</td>
        <td>
          <div class="title-cell">
            <strong title="${escapeHtml(clean(row.title))}">${escapeHtml(clean(row.title))}</strong>
            <span>${escapeHtml(titleCase(row.event_family))} / ${escapeHtml(titleCase(row.catalyst_category))} / ${escapeHtml(titleCase(row.live_market_regime || "neutral_mixed"))}</span>
          </div>
        </td>
        <td>${directionBadge(row.direction)}</td>
        <td>${ruleBadge(row)}</td>
        <td>${probabilityCell(row)}</td>
        <td>${percent(row.confidence, 0)}</td>
        <td>${points(row.trust_weight, 2)}</td>
        <td>${tradeStateBadge(row)}</td>
        <td>${statusBadge(row.status)}</td>
      </tr>
    `).join("")
    : '<tr><td colspan="9"><div class="empty">No matching signals</div></td></tr>';

  if (wrap) {
    wrap.scrollTop = scrollTop;
    wrap.scrollLeft = scrollLeft;
  }

  renderDetail();
}

function selectSignalRow(id, options = {}) {
  if (!id || id === state.selectedId) {
    if (options.refreshDetail) {
      renderDetail();
    }
    return;
  }
  state.selectedId = id;
  els.signalsBody.querySelectorAll("tr.selected").forEach((tr) => tr.classList.remove("selected"));
  const row = Array.from(els.signalsBody.querySelectorAll("tr[data-id]")).find((tr) => tr.dataset.id === id);
  if (row) {
    row.classList.add("selected");
    if (options.scrollIntoView) {
      row.scrollIntoView({ block: "nearest" });
    }
  }
  renderDetail();
}

function openSignalPopup(row) {
  if (!row) {
    return;
  }
  const detailParts = [
    `Actual ${clean(row.actual)} vs forecast ${clean(row.forecast)} (previous ${clean(row.previous)}), surprise ${surpriseText(row.surprise)}.`,
    clean(row.trade_state_reason || row.live_market_regime_reason, ""),
  ].filter(Boolean);
  popupState.queue.unshift({
    alert_time: new Date().toISOString(),
    alert_type: "signal_detail",
    severity: row.regimeConflict !== "none" ? "high" : "info",
    title: clean(row.title),
    release_time: row.release_time,
    catalyst_category: row.catalyst_category,
    current_direction: row.direction,
    current_bullish_probability: row.bull,
    current_confidence: row.confidence,
    current_status: row.status,
    message: detailParts.join(" "),
  });
  showNextAlertPopup();
}

function moveSelection(step) {
  const rows = sortRows(filteredSignals());
  if (!rows.length) {
    return;
  }
  const index = rows.findIndex((row) => row.id === state.selectedId);
  const next = rows[Math.max(0, Math.min(rows.length - 1, (index === -1 ? 0 : index + step)))];
  selectSignalRow(next.id, { scrollIntoView: true });
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
  const regimeWarningText = clean(row.regimeWarning, "");
  const regimeWarning = regimeWarningText ? `<div class="note warning">${escapeHtml(regimeWarningText)}</div>` : "";
  const ruleNote = clean(row.market_rule_note, "");
  const trustNote = clean(row.trust_note, "");
  const regimeReason = clean(row.live_market_regime_reason, "");
  const tradeReason = clean(row.trade_state_reason, "");
  const tradeReasonNote = tradeReason && tradeReason !== regimeWarningText
    ? `<div class="note">${escapeHtml(tradeReason)}</div>`
    : "";

  els.detailPanel.innerHTML = `
    <div class="detail-head">
      <div class="pill-row">
        ${directionBadge(row.direction)}
        ${statusBadge(row.status)}
        <span class="pill ${escapeHtml(row.releaseRuleDirection)}" title="${escapeHtml(row.releaseRuleLabel)}">${escapeHtml(displayRuleLabel(row))}</span>
        ${regimePill(row)}
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
      ${detailDatum("Surprise", surpriseText(row.surprise))}
      ${detailDatum("Release Rule", row.releaseRuleLabel)}
      ${detailDatum("Live Regime", titleCase(row.live_market_regime))}
      ${detailDatum("Trade State", titleCase(row.tradeState))}
      ${detailDatum("Trust Weight", points(row.trust_weight, 3))}
      ${detailDatum("Trust Samples", row.trust_sample_size)}
      ${detailDatum("Daily Confirm", titleCase(row.daily_confirmation_match))}
      ${detailDatum("Daily Bull", percent(numberValue(row.daily_confirmation_bullish_probability, 0.5), 0))}
    </div>
    ${regimeWarning}
    ${regimeReason ? `<div class="note">${escapeHtml(regimeReason)}</div>` : ""}
    ${tradeReasonNote}
    ${ruleNote ? `<div class="note">${escapeHtml(ruleNote)}</div>` : ""}
    ${trustNote ? `<div class="note">${escapeHtml(trustNote)}</div>` : ""}
    ${row.daily_confirmation_note ? `<div class="note">${escapeHtml(row.daily_confirmation_note)}</div>` : ""}
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
  renderStaleBanner();
  renderMetrics();
  renderComponentRanges();
  renderAlerts();
  renderNews();
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

function setEmailResult(message, type = "") {
  els.emailTestResult.hidden = !message;
  els.emailTestResult.className = `email-test-result ${type}`.trim();
  els.emailTestResult.textContent = message;
}

function renderEmailConfig(status) {
  const rows = [
    ["Recipient", status.recipient || "Not set"],
    ["Sender", status.sender || "Not set"],
    ["SMTP", status.smtp_host ? `${status.smtp_host}:${status.smtp_port}` : "Not set"],
    ["Password", status.password_present ? `Stored in ${status.password_env}` : "Not stored"],
    ["Automatic", status.automatic_enabled ? "Enabled" : "Disabled"],
    ["Alert filter", status.min_severity || "info"],
  ];
  els.emailConfigGrid.innerHTML = rows
    .map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`)
    .join("");
}

async function loadEmailStatus() {
  els.emailConfigSummary.textContent = "Checking configuration";
  els.sendTestEmailBtn.disabled = true;
  setEmailResult("");
  try {
    const response = await fetch(`${API_PATHS.emailStatus}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Email status returned ${response.status}`);
    }
    const status = await response.json();
    if (status.recipient && !els.emailRecipient.value) {
      els.emailRecipient.value = status.recipient;
    }
    renderEmailConfig(status);
    els.emailConfigSummary.textContent = status.configured && status.mirrors_dashboard_alerts
      ? "Automatic popup-to-email delivery is enabled."
      : status.configured
        ? "SMTP works, but automatic delivery is not fully enabled."
        : "Email is not configured yet.";
    els.sendTestEmailBtn.disabled = !status.configured;
    if (!status.configured) {
      setEmailResult("Run tools\\setup_email_alert.ps1, then restart the dashboard.", "error");
    } else if (!status.mirrors_dashboard_alerts) {
      setEmailResult("Add email to notification targets and set min_severity to info to mirror every dashboard popup.", "error");
    }
  } catch (error) {
    els.emailConfigSummary.textContent = "Local email API is unavailable.";
    els.emailConfigGrid.innerHTML = "";
    setEmailResult("Restart the dashboard with START.bat so the local API server is active.", "error");
  }
}

async function openEmailDialog() {
  if (typeof els.emailDialog.showModal === "function") {
    els.emailDialog.showModal();
  } else {
    els.emailDialog.setAttribute("open", "");
  }
  await loadEmailStatus();
}

async function sendTestEmail() {
  const recipient = els.emailRecipient.value.trim();
  if (!els.emailRecipient.checkValidity()) {
    els.emailRecipient.reportValidity();
    return;
  }
  els.sendTestEmailBtn.disabled = true;
  els.sendTestEmailBtn.textContent = "Sending";
  setEmailResult(`Sending test email to ${recipient}...`);
  try {
    const response = await fetch(API_PATHS.testEmail, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recipient }),
    });
    const result = await response.json().catch(() => ({}));
    const message = result.message || result.error || `Email test returned ${response.status}.`;
    setEmailResult(message, response.ok && result.ok ? "success" : "error");
  } catch (error) {
    setEmailResult(`Email test failed: ${error.message}`, "error");
  } finally {
    els.sendTestEmailBtn.disabled = false;
    els.sendTestEmailBtn.textContent = "Send Test";
  }
}

async function loadAll() {
  els.dataStamp.textContent = "Loading data";
  try {
    const [signals, performance, trust, status, alertSummary, news, newsSummary] = await Promise.all([
      fetchCsv(DATA_PATHS.signals),
      fetchCsv(DATA_PATHS.performance),
      fetchCsv(DATA_PATHS.trust),
      fetchJson(DATA_PATHS.status).catch(() => null),
      fetchJson(DATA_PATHS.alerts).catch(() => null),
      fetchCsv(DATA_PATHS.news).catch(() => []),
      fetchJson(DATA_PATHS.newsSummary).catch((error) => ({ load_error: error.message })),
    ]);
    state.signals = normalizeSignals(signals);
    state.performance = performance;
    state.trust = trust;
    state.status = status;
    state.alertSummary = alertSummary;
    state.news = normalizeNews(news);
    state.newsSummary = newsSummary;
    const stillExists = state.signals.some((row) => row.id === state.selectedId);
    state.selectedId = stillExists ? state.selectedId : (state.signals[0]?.id || "");
    renderAll();
    maybeShowAlertPopups();
  } catch (error) {
    els.dataStamp.textContent = `Data load failed: ${error.message}`;
    els.signalsBody.innerHTML = '<tr><td colspan="9"><div class="empty">Unable to load dashboard data</div></td></tr>';
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
  els.emailBtn.addEventListener("click", openEmailDialog);
  els.sendTestEmailBtn.addEventListener("click", sendTestEmail);

  els.alertPanel.addEventListener("click", (event) => {
    const item = event.target.closest("[data-alert-index]");
    if (!item) {
      return;
    }
    const alert = (state.visibleAlerts || [])[Number(item.dataset.alertIndex)];
    if (alert) {
      openAlertDetails(alert);
    }
  });

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
    selectSignalRow(row.dataset.id);
    if (window.matchMedia("(max-width: 1100px)").matches) {
      els.detailPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });

  els.signalsBody.addEventListener("dblclick", (event) => {
    const row = event.target.closest("tr[data-id]");
    if (!row) {
      return;
    }
    selectSignalRow(row.dataset.id);
    openSignalPopup(state.signals.find((item) => item.id === row.dataset.id));
  });

  document.addEventListener("keydown", (event) => {
    if (state.activeTab !== "signals") {
      return;
    }
    const target = event.target;
    if (target && (target.tagName === "INPUT" || target.tagName === "SELECT" || target.tagName === "TEXTAREA")) {
      return;
    }
    if (!els.alertPopupLayer.hidden && event.key === "Escape") {
      event.preventDefault();
      showNextAlertPopup();
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveSelection(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveSelection(-1);
    } else if (event.key === "Enter" && state.selectedId) {
      event.preventDefault();
      openSignalPopup(state.signals.find((item) => item.id === state.selectedId));
    }
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
setInterval(() => {
  if (!document.hidden) {
    loadAll();
  }
}, 30000);
