/* Dora dashboard — source loader + renderers.
 *
 * Source priority: ?url= > file input > localStorage > fixtures/sample.json
 */

const LS_KEY = "dora:lastUrl";

const urlInput  = document.getElementById("url-input");
const urlBtn    = document.getElementById("url-load");
const fileInput = document.getElementById("file-input");
const srcInfo   = document.getElementById("source-info");
const repoPicker = document.getElementById("repo-picker");
const repoSel   = document.getElementById("repo-select");

const loading  = document.getElementById("loading");
const errorEl  = document.getElementById("error");
const errorMsg = document.getElementById("error-msg");
const dash     = document.getElementById("dashboard");

let currentReport  = null;
let currentMetrics = null;       // byMetric(currentReport) — kept so we can re-render on range change
let currentRepo    = null;
let charts         = [];

// Date range state.
// weeksAxis is the sorted union of `week` values across all metrics.
let weeksAxis    = [];
let currentFrom  = null;         // ISO week string, e.g. "2025-W42"
let currentTo    = null;         // ISO week string

const PRESETS = [
  { id: "4",   weeks: 4,    label: "4w"  },
  { id: "12",  weeks: 12,   label: "12w" },
  { id: "26",  weeks: 26,   label: "26w" },
  { id: "all", weeks: null, label: "All" },
];
const DEFAULT_PRESET_ID = "12";

// --------- source loading ---------

function showState({ load = false, err = null }) {
  loading.hidden = !load;
  errorEl.hidden = !err;
  if (err) errorMsg.textContent = err;
  if (load || err) dash.hidden = true;
}

async function loadFromUrl(url, label) {
  showState({ load: true });
  srcInfo.textContent = `Loading ${label || url}…`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const report = await res.json();
    currentReport  = report;
    currentMetrics = byMetric(report);
    weeksAxis      = computeWeeksAxis(report);
    initRangeFromData();
    localStorage.setItem(LS_KEY, url);
    urlInput.value = url;
    srcInfo.textContent = `Source: ${label || url}`;
    render();
  } catch (err) {
    console.error(err);
    showState({ err: `${label || url}: ${err.message}` });
    srcInfo.textContent = "";
  }
}

async function loadFromFile(file) {
  showState({ load: true });
  try {
    const text = await file.text();
    currentReport  = JSON.parse(text);
    currentMetrics = byMetric(currentReport);
    weeksAxis      = computeWeeksAxis(currentReport);
    initRangeFromData();
    srcInfo.textContent = `Source: ${file.name} (local file)`;
    render();
  } catch (err) {
    console.error(err);
    showState({ err: `${file.name}: ${err.message}` });
  }
}

function decideInitialSource() {
  const params = new URLSearchParams(window.location.search);
  const qsUrl = params.get("url") || params.get("data");  // ?data= legacy
  if (qsUrl) return { url: qsUrl, label: qsUrl };

  const remembered = localStorage.getItem(LS_KEY);
  if (remembered) return { url: remembered, label: `${remembered} (remembered)` };

  return { url: "fixtures/sample.json", label: "sample (demo data)" };
}

// --------- helpers ---------

function byMetric(report) {
  const out = {};
  for (const m of report.metrics || []) out[m.metric] = m.data || [];
  return out;
}

function uniqueRepos(metrics) {
  const s = new Set();
  for (const rows of Object.values(metrics)) {
    for (const r of rows) if (r.repo) s.add(r.repo);
  }
  return [...s].sort();
}

function filterByRepo(rows, repo) {
  return repo ? rows.filter(r => r.repo === repo) : rows;
}

function recentN(rows, n, keyFn = r => r.week) {
  // Rows keyed by ISO week string like "2026-W14" — sorts lexicographically.
  return [...rows].sort((a, b) => (keyFn(a) < keyFn(b) ? 1 : -1)).slice(0, n);
}

// DORA tier bands (approximate — simplified from the official report).
function deployFreqTier(perWeek) {
  if (perWeek == null) return "na";
  if (perWeek >= 7) return "elite";    // >1/day
  if (perWeek >= 1) return "high";     // >=1/week
  if (perWeek >= 0.25) return "medium"; // >=1/month
  return "low";
}
function leadTimeTier(hours) {
  if (hours == null) return "na";
  if (hours < 24) return "elite";
  if (hours < 168) return "high";
  if (hours < 720) return "medium";
  return "low";
}
function cfrTier(pct) {
  if (pct == null) return "na";
  if (pct <= 15) return "elite";
  if (pct <= 30) return "high";
  if (pct <= 45) return "medium";
  return "low";
}

function largePrsTier(perWeek) {
  if (perWeek == null) return "na";
  if (perWeek < 2) return "elite";   // <2/wk: healthy churn
  if (perWeek <= 4) return "medium"; // 2-4/wk: caution
  return "low";                      // >4/wk: too many big PRs
}

function hotfixTier(perWeek) {
  if (perWeek == null) return "na";
  if (perWeek < 1) return "elite";   // 0/wk
  if (perWeek <= 2) return "medium"; // 1-2/wk
  return "low";                      // 3+/wk
}

const TIER_LABEL = { elite: "Elite", high: "High", medium: "Medium", low: "Low", na: "N/A" };

function kpiCard({ label, value, unit, subText, tier, info }) {
  const infoIcon = info
    ? `<span class="info-icon" tabindex="0" role="img" aria-label="About ${escapeHtml(label)}" data-tip="${escapeHtml(info)}">i</span>`
    : "";
  return `
    <div class="kpi">
      <span class="kpi-label">${escapeHtml(label)}${infoIcon}</span>
      <span class="kpi-value">${escapeHtml(value)}<span class="kpi-unit">${escapeHtml(unit || "")}</span></span>
      <span class="kpi-sub"><span class="tier tier-${tier}">${TIER_LABEL[tier]}</span>${escapeHtml(subText)}</span>
    </div>
  `;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function readVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// --------- rendering ---------

function resetCharts() {
  for (const c of charts) c.destroy();
  charts = [];
}

function render() {
  showState({});
  dash.hidden = false;

  const metrics = currentMetrics;
  const repos = uniqueRepos(metrics);

  document.getElementById("since").textContent = currentReport.since || "—";
  document.getElementById("scope").textContent =
    repos.length === 1 ? repos[0]
    : repos.length > 1 ? `${repos.length} repositories`
    : "No data yet";

  if (repos.length > 1) {
    repoPicker.hidden = false;
    repoSel.innerHTML = "";
    for (const r of repos) {
      const opt = document.createElement("option");
      opt.value = opt.textContent = r;
      repoSel.append(opt);
    }
    repoSel.value = currentRepo && repos.includes(currentRepo) ? currentRepo : repos[0];
    currentRepo = repoSel.value;
    repoSel.onchange = () => {
      currentRepo = repoSel.value;
      renderForRepo(metrics, currentRepo);
    };
    renderForRepo(metrics, currentRepo);
  } else {
    repoPicker.hidden = true;
    currentRepo = repos[0] || null;
    renderForRepo(metrics, currentRepo);
  }
}

function renderForRepo(metrics, repo) {
  resetCharts();

  const freqPrs        = inRange(filterByRepo(metrics["deploy-freq-prs"]     || [], repo));
  const freqDeploys    = inRange(filterByRepo(metrics["deploy-freq"]         || [], repo));
  const leadTime       = inRange(filterByRepo(metrics["lead-time"]           || [], repo));
  const cfr            = inRange(filterByRepo(metrics["change-failure-rate"] || [], repo));
  const cfrPrs         = inRange(filterByRepo(metrics["change-failure-prs"]  || [], repo));
  const hotfixes       = inRangeHotfixes(filterByRepo(metrics["hotfixes"]    || [], repo));
  const reviewLatency  = inRange(filterByRepo(metrics["review-latency"]      || [], repo));
  const largePrs       = inRange(filterByRepo(metrics["large-prs"]           || [], repo));
  const hotfixCount    = inRange(filterByRepo(metrics["hotfix-count"]        || [], repo));
  const weekendMerges  = inRangeWeekendMerges(filterByRepo(metrics["weekend-merges"] || [], repo));
  // summary is not date-filterable; renderKPIs uses it only as a fallback,
  // and that fallback is dropped when filtering is active (see renderKPIs).
  const summary        = filterByRepo(metrics["summary"] || [], repo);

  renderKPIs(summary, freqPrs, freqDeploys, leadTime, cfr, largePrs, hotfixCount);
  renderFreqChart(freqPrs, freqDeploys);
  renderLeadChart(leadTime);
  renderCFRChart(cfr);
  renderCfrPrs(cfrPrs);
  renderHotfixes(hotfixes);
  renderReviewLatencyChart(reviewLatency);
  renderWeekendMerges(weekendMerges);
}

function renderKPIs(summary, freqPrs, freqDeploys, leadTime, cfr, largePrs, hotfixCount) {
  const filtering = currentFrom !== null && currentTo !== null;
  const s = filtering ? null : summary[0];

  // Deploy frequency.
  // Filtering: average across the selected range (rows already filtered).
  // Otherwise: last 4 weeks proxy.
  const dRows = filtering ? freqDeploys : recentN(freqDeploys, 4);
  const pRows = filtering ? freqPrs     : recentN(freqPrs, 4);
  const denomDeploys = filtering ? Math.max(1, dRows.length) : 4;
  const denomPrs     = filtering ? Math.max(1, pRows.length) : 4;
  const deployPerWk =
    dRows.length
      ? dRows.reduce((a, r) => a + (r.deploys || 0), 0) / denomDeploys
      : pRows.length
      ? pRows.reduce((a, r) => a + (r.deploys || 0), 0) / denomPrs
      : s?.prs_per_week ?? null;
  const deployUnit = dRows.length ? " deploys/wk" : " merges/wk";

  // Lead time.
  const lRows = filtering ? leadTime : recentN(leadTime, 4);
  const leadMedian =
    lRows.length
      ? lRows.reduce((a, r) => a + (r.median_h || 0), 0) / lRows.length
      : s?.median_lead_h ?? null;

  // CFR — totals across the (filtered) cfr rows.
  const totals = cfr.reduce(
    (acc, r) => ({ d: acc.d + (r.deploys || 0), f: acc.f + (r.failures || 0) }),
    { d: 0, f: 0 }
  );
  const cfrPct =
    totals.d > 0 ? (100 * totals.f) / totals.d
    : (s?.cfr != null ? parseFloat(String(s.cfr).replace("%", "")) : null);

  // Large PRs / wk and Hotfixes / wk: average per week.
  // Unfiltered → last 4 weeks; filtered → range avg.
  // Empty + filtering → 0 (the metric only emits weeks with non-zero counts,
  // so an empty filtered range legitimately means "none in this window").
  // Empty + unfiltered → "—" (metric likely absent from the report entirely).
  const lpRows = filtering ? (largePrs || []) : recentN(largePrs || [], 4);
  const lpDenom = filtering ? Math.max(1, lpRows.length) : 4;
  const largePerWk = (largePrs && largePrs.length)
    ? lpRows.reduce((a, r) => a + (r.large_prs || 0), 0) / lpDenom
    : (filtering ? 0 : null);

  const hcRows = filtering ? (hotfixCount || []) : recentN(hotfixCount || [], 4);
  const hcDenom = filtering ? Math.max(1, hcRows.length) : 4;
  const hotfixPerWk = (hotfixCount && hotfixCount.length)
    ? hcRows.reduce((a, r) => a + (r.hotfix_count || 0), 0) / hcDenom
    : (filtering ? 0 : null);

  const subText     = filtering ? "in selected range"            : "last 4 weeks";
  const leadSubText = filtering ? "median, in selected range"    : "median, last 4 wk";
  const cfrSubText  = filtering ? "in selected range"            : "across window";

  document.getElementById("kpis").innerHTML = [
    kpiCard({
      label: "Deploy frequency",
      value: deployPerWk != null ? deployPerWk.toFixed(1) : "—",
      unit: deployUnit,
      subText,
      tier: deployFreqTier(deployPerWk),
      info: dRows.length
        ? "Average successful deploys per week. Source: GitHub Deployments API for the configured environment (success + inactive statuses)."
        : "Average merged PRs per week (proxy for shipped changes). Source: PRs merged into the base branch — used because no Deployments are recorded.",
    }),
    kpiCard({
      label: "Lead time",
      value: leadMedian != null ? Math.round(leadMedian).toString() : "—",
      unit: " h",
      subText: leadSubText,
      tier: leadTimeTier(leadMedian),
      info: "Median hours from first commit on a PR's branch to its merge into the base branch, averaged across the window. Source: PR commits + merge timestamp from the GitHub API.",
    }),
    kpiCard({
      label: "Change failure rate",
      value: cfrPct != null ? cfrPct.toFixed(0) : "—",
      unit: " %",
      subText: cfrSubText,
      tier: cfrTier(cfrPct),
      info: "PRs labelled `caused-incident` ÷ all merged PRs across the window. Apply the label to the PR that SHIPPED the defect (not the PR that fixed it). See the drill-down list below the chart.",
    }),
    kpiCard({
      label: "Large PRs / wk",
      value: largePerWk != null ? largePerWk.toFixed(1) : "—",
      unit: "",
      subText,
      tier: largePrsTier(largePerWk),
      info: "Average per-week count of merged PRs with 10 or more changed files. Large PRs are slower to review and more failure-prone — a sustained rate above ~2/wk is a smell.",
    }),
    kpiCard({
      label: "Hotfixes / wk",
      value: hotfixPerWk != null ? hotfixPerWk.toFixed(1) : "—",
      unit: "",
      subText,
      tier: hotfixTier(hotfixPerWk),
      info: "Average per-week count of merged PRs labelled `hotfix`. The `hotfix` label marks the PR that FIXED a prior defect; consistently nonzero rates point to upstream quality issues.",
    }),
    kpiCard({
      label: "Mean time to restore",
      value: "—",
      unit: "",
      subText: "needs incident log",
      tier: "na",
      info: "Not automated. Computing MTTR requires an incident log with detected/restored timestamps, which GitHub data alone can't provide.",
    }),
  ].join("");
}

// Align two series by week, producing one sorted label axis.
function alignByWeek(seriesA, seriesB, valFn = r => r.deploys) {
  const weeks = [...new Set([
    ...seriesA.map(r => r.week),
    ...(seriesB || []).map(r => r.week),
  ])].sort();
  const mapA = Object.fromEntries(seriesA.map(r => [r.week, valFn(r)]));
  const mapB = Object.fromEntries((seriesB || []).map(r => [r.week, valFn(r)]));
  return {
    labels: weeks,
    a: weeks.map(w => (mapA[w] == null ? null : mapA[w])),
    b: weeks.map(w => (mapB[w] == null ? null : mapB[w])),
  };
}

function baseOpts() {
  const tick = readVar("--chart-tick");
  const grid = readVar("--chart-grid");
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { enabled: true } },
    scales: {
      x: { grid: { color: grid }, ticks: { color: tick, font: { size: 11 } } },
      y: { grid: { color: grid }, ticks: { color: tick, font: { size: 11 } }, beginAtZero: true },
    },
  };
}

function renderFreqChart(freqPrs, freqDeploys) {
  const { labels, a, b } = alignByWeek(freqPrs, freqDeploys, r => r.deploys);
  const primary = readVar("--chart-primary");
  const secondary = readVar("--chart-secondary");
  const ctx = document.getElementById("freqChart");
  if (!labels.length) {
    ctx.parentElement.innerHTML = '<div class="empty">No data yet</div>';
    return;
  }
  charts.push(new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Merged PRs", data: a, borderColor: primary, backgroundColor: primary,
          borderWidth: 2, pointRadius: 2.5, tension: 0.25 },
        { label: "Deploys", data: b, borderColor: secondary, backgroundColor: secondary,
          borderWidth: 2, pointRadius: 2.5, tension: 0.25, borderDash: [4, 3] },
      ],
    },
    options: baseOpts(),
  }));
}

function renderLeadChart(leadTime) {
  if (!leadTime.length) {
    document.getElementById("leadChart").parentElement.innerHTML = '<div class="empty">No data yet</div>';
    return;
  }
  const rows = [...leadTime].sort((a, b) => (a.week < b.week ? -1 : 1));
  const labels = rows.map(r => r.week);
  const primary = readVar("--chart-primary");
  const secondary = readVar("--chart-secondary");
  const accent = readVar("--chart-accent");
  const opts = baseOpts();
  opts.scales.y.title = { display: true, text: "hours", color: readVar("--chart-tick"), font: { size: 11 } };
  charts.push(new Chart(document.getElementById("leadChart"), {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Median", data: rows.map(r => r.median_h), borderColor: primary, backgroundColor: primary,
          borderWidth: 2, pointRadius: 2.5, tension: 0.25 },
        { label: "Mean",   data: rows.map(r => r.mean_h),   borderColor: secondary, backgroundColor: secondary,
          borderWidth: 1.5, pointRadius: 2, tension: 0.25, borderDash: [4, 3] },
        { label: "P90",    data: rows.map(r => r.p90_h),    borderColor: accent, backgroundColor: accent,
          borderWidth: 1.5, pointRadius: 2, tension: 0.25, borderDash: [2, 2] },
      ],
    },
    options: opts,
  }));
}

function renderCFRChart(cfr) {
  if (!cfr.length) {
    document.getElementById("cfrChart").parentElement.innerHTML = '<div class="empty">No data yet</div>';
    return;
  }
  const rows = [...cfr].sort((a, b) => (a.week < b.week ? -1 : 1));
  const accent = readVar("--chart-accent");
  const opts = baseOpts();
  opts.scales.y.ticks.callback = v => v + "%";
  charts.push(new Chart(document.getElementById("cfrChart"), {
    type: "bar",
    data: {
      labels: rows.map(r => r.week),
      datasets: [{ label: "CFR %", data: rows.map(r => r.failure_pct), backgroundColor: accent, borderRadius: 2 }],
    },
    options: opts,
  }));
}

const REVIEW_LATENCY_BUCKETS = [
  { label: "XS", color: "#2d5a8e" },
  { label: "S",  color: "#4a86c7" },
  { label: "M",  color: "#b4450a" },
  { label: "L+", color: "#6a3d9a" },
];

function renderReviewLatencyChart(rows) {
  const ctx = document.getElementById("reviewLatencyChart");
  if (!rows.length) {
    ctx.parentElement.innerHTML = '<div class="empty">No data yet</div>';
    return;
  }

  // One sorted week axis spanning all buckets.
  const weeks = [...new Set(rows.map(r => r.week))].sort();

  // Per-bucket map: week → median_h.
  const byBucket = {};
  for (const r of rows) {
    (byBucket[r.bucket] = byBucket[r.bucket] || {})[r.week] = r.median_h;
  }

  const datasets = REVIEW_LATENCY_BUCKETS.map(({ label, color }) => ({
    label,
    data: weeks.map(w => {
      const v = byBucket[label]?.[w];
      return v == null ? null : v;
    }),
    borderColor: color,
    backgroundColor: color,
    borderWidth: 2,
    pointRadius: 2.5,
    tension: 0.25,
    spanGaps: false,
  }));

  const opts = baseOpts();
  opts.scales.y.title = {
    display: true,
    text: "hours",
    color: readVar("--chart-tick"),
    font: { size: 11 },
  };

  charts.push(new Chart(ctx, {
    type: "line",
    data: { labels: weeks, datasets },
    options: opts,
  }));
}

function renderCfrPrs(rows) {
  const el = document.getElementById("cfr-prs");
  if (!rows.length) { el.innerHTML = ""; return; }

  // Rows already arrive ORDER BY repo, week DESC, number DESC — preserve that.
  // Group consecutive runs of the same week.
  const groups = [];
  for (const r of rows) {
    const last = groups[groups.length - 1];
    if (last && last.week === r.week) last.prs.push(r);
    else groups.push({ week: r.week, prs: [r] });
  }

  const body = groups.map(g => `
    <div class="cfr-week-head">${escapeHtml(g.week)}</div>
    ${g.prs.map(p => `
      <div class="cfr-pr">
        <a href="https://github.com/${escapeHtml(p.repo)}/pull/${encodeURIComponent(p.pr)}"
           target="_blank" rel="noopener noreferrer">#${escapeHtml(p.pr)}</a>
        <span>${escapeHtml(p.title || "")} <span class="cfr-pr-author">· ${escapeHtml(p.author || "")}</span></span>
        <span class="cfr-pr-date">${escapeHtml(p.merged || "")}</span>
      </div>
    `).join("")}
  `).join("");

  const noun = rows.length === 1 ? "PR" : "PRs";
  el.innerHTML = `
    <details class="cfr-details">
      <summary>${rows.length} incident-causing ${noun}</summary>
      ${body}
    </details>
  `;
}

function renderHotfixes(rows) {
  const el = document.getElementById("hotfixes");
  if (!rows.length) {
    el.innerHTML = '<div class="empty">No hotfixes in the current window</div>';
    return;
  }
  let html = "";
  let groupIdx = -1;
  for (const r of rows) {
    if (r.relation === "hotfix") {
      groupIdx += 1;
      html += `${groupIdx > 0 ? '<div class="hotfix-group"></div>' : ""}
        <div class="hx-row">
          <span class="hx-tag hx-hotfix">hotfix</span>
          <span><span class="hx-pr">${escapeHtml(r.pr)}</span> ${escapeHtml(r.title)} <span class="hx-author">· ${escapeHtml(r.author || "")}</span></span>
          <span class="hx-date">${escapeHtml(r.merged || "")}</span>
        </div>`;
    } else {
      html += `<div class="hx-row prev">
        <span class="hx-tag hx-prev">prev</span>
        <span><span class="hx-pr">${escapeHtml(r.pr)}</span> ${escapeHtml(r.title)} <span class="hx-author">· ${escapeHtml(r.author || "")}</span></span>
        <span class="hx-date">${escapeHtml(r.merged || "")}</span>
      </div>`;
    }
  }
  el.innerHTML = html;
}

function renderWeekendMerges(rows) {
  const el = document.getElementById("weekend-merges");
  if (!rows.length) {
    el.innerHTML = '<div class="empty">No weekend merges in the current range</div>';
    return;
  }

  // Per-author tally for the selected range.
  const byAuthor = new Map();
  for (const r of rows) {
    const a = r.author || "(unknown)";
    if (!byAuthor.has(a)) byAuthor.set(a, []);
    byAuthor.get(a).push(r);
  }
  const authors = [...byAuthor.entries()].sort((a, b) => b[1].length - a[1].length);

  const total = rows.length;
  const noun  = total === 1 ? "merge" : "merges";
  const summary =
    `<div class="wk-summary">${total} weekend ${noun} · ${authors.length} author${authors.length === 1 ? "" : "s"}</div>`;

  const list = authors.map(([author, prs]) => {
    const prList = prs
      .sort((a, b) => (a.merged < b.merged ? 1 : -1))
      .map(p => `
        <div class="wk-pr">
          <span class="wk-tag wk-${escapeHtml((p.dow || "").toLowerCase())}">${escapeHtml(p.dow || "")}</span>
          <a href="https://github.com/${escapeHtml(p.repo)}/pull/${encodeURIComponent(p.pr)}"
             target="_blank" rel="noopener noreferrer">#${escapeHtml(p.pr)}</a>
          <span>${escapeHtml(p.title || "")}</span>
          <span class="wk-date">${escapeHtml(p.merged || "")}</span>
        </div>
      `).join("");
    return `
      <details class="wk-author">
        <summary><span class="wk-author-name">${escapeHtml(author)}</span><span class="wk-author-count">${prs.length}</span></summary>
        ${prList}
      </details>
    `;
  }).join("");

  el.innerHTML = summary + list;
}

// --------- date range helpers ---------

/** Sorted unique week values across all metrics that have a `week` field. */
function computeWeeksAxis(report) {
  const s = new Set();
  for (const m of report.metrics || []) {
    for (const r of (m.data || [])) {
      if (r.week) s.add(r.week);
    }
  }
  return [...s].sort();
}

/** Filter rows to those whose `week` is in [currentFrom, currentTo]. */
function inRange(rows) {
  if (!currentFrom || !currentTo) return rows;
  return rows.filter(r => {
    if (!r.week) return true;
    return r.week >= currentFrom && r.week <= currentTo;
  });
}

/** Convert an ISO week ("2025-W42") to its Monday's date string ("2025-10-13").
 *  Used for hotfix rows which carry `merged` (date) instead of `week`. */
function weekToMondayDate(weekStr) {
  const m = /^(\d{4})-W(\d{2})$/.exec(weekStr);
  if (!m) return null;
  const year = parseInt(m[1], 10);
  // SQLite strftime('%W'): week 00 = days before first Monday; week N starts
  // on the Nth Monday after week 00. So "2025-W42" Monday = first Monday of 2025
  // + 41 weeks. JS month is 0-indexed.
  const jan1 = new Date(Date.UTC(year, 0, 1));
  const jan1Day = jan1.getUTCDay();             // 0 = Sun, 1 = Mon, ...
  const daysToFirstMonday = (jan1Day === 1) ? 0 : (8 - jan1Day) % 7;
  const firstMonday = new Date(jan1);
  firstMonday.setUTCDate(jan1.getUTCDate() + daysToFirstMonday);
  const target = new Date(firstMonday);
  target.setUTCDate(firstMonday.getUTCDate() + (parseInt(m[2], 10) - 1) * 7);
  return target.toISOString().slice(0, 10);
}

/** Convert a Monday-of-week date string ("YYYY-MM-DD") to the date string for
 *  that week's Sunday (i.e. Monday + 6 days), keeping everything in UTC. */
function weekEndDate(mondayDate) {
  const d = new Date(mondayDate + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + 6);
  return d.toISOString().slice(0, 10);
}

/** Resolve `[currentFrom, currentTo]` ISO weeks into a closed `[fromDate, toEnd]`
 *  date span (Monday-of-from to Sunday-of-to). Returns null if no range is
 *  active or the week strings can't be parsed. */
function currentRangeDates() {
  if (!currentFrom || !currentTo) return null;
  const fromDate = weekToMondayDate(currentFrom);
  const toDate   = weekToMondayDate(currentTo);
  if (!fromDate || !toDate) return null;
  return { fromDate, toEnd: weekEndDate(toDate) };
}

/** Filter hotfix rows: keep each `hotfix` row in range AND its trailing
 *  `preceded-by` rows (groups stay intact even if the prev row's date
 *  is technically outside the window). */
function inRangeHotfixes(rows) {
  const span = currentRangeDates();
  if (!span) return rows;
  const out = [];
  let keepGroup = false;
  for (const r of rows) {
    if (r.relation === "hotfix") {
      keepGroup = r.merged >= span.fromDate && r.merged <= span.toEnd;
      if (keepGroup) out.push(r);
    } else if (keepGroup) {
      out.push(r);
    }
  }
  return out;
}

/** Filter weekend-merges rows by the date covered by [currentFrom, currentTo].
 *  Each row carries `merged` (YYYY-MM-DD); we keep rows whose `merged` falls
 *  inside the Monday-of-from to Sunday-of-to span. */
function inRangeWeekendMerges(rows) {
  const span = currentRangeDates();
  if (!span) return rows;
  return rows.filter(r => r.merged && r.merged >= span.fromDate && r.merged <= span.toEnd);
}

/** Compute [from, to] for a preset clicked on the current data.
 *  Preset "all" → full data extent; numeric → last N weeks ending at latestWeek. */
function computePresetRange(presetId) {
  if (!weeksAxis.length) return [null, null];
  const earliest = weeksAxis[0];
  const latest   = weeksAxis[weeksAxis.length - 1];
  if (presetId === "all") return [earliest, latest];
  const n = parseInt(presetId, 10);
  if (!Number.isFinite(n) || n <= 0) return [earliest, latest];
  const startIdx = Math.max(0, weeksAxis.length - n);
  return [weeksAxis[startIdx], latest];
}

/** Find the preset whose [from, to] matches the current selection (if any). */
function rangeMatchesPreset(from, to) {
  for (const p of PRESETS) {
    const [pFrom, pTo] = computePresetRange(p.id);
    if (pFrom === from && pTo === to) return p.id;
  }
  return null;
}

/** Read ?from=&to= from the URL, clamped/validated against weeksAxis.
 *  Returns [from, to] or [null, null] if no params and no fallback wanted. */
function parseRangeFromUrl() {
  const params = new URLSearchParams(window.location.search);
  let from = params.get("from");
  let to   = params.get("to");
  const valid = w => /^\d{4}-W\d{2}$/.test(w);
  from = valid(from) ? from : null;
  to   = valid(to)   ? to   : null;
  if (!from && !to) return [null, null];
  if (!weeksAxis.length) return [null, null];
  const earliest = weeksAxis[0];
  const latest   = weeksAxis[weeksAxis.length - 1];
  if (!from) from = earliest;
  if (!to)   to   = latest;
  if (from > to) [from, to] = [to, from];
  if (from < earliest) from = earliest;
  if (to   > latest)   to   = latest;
  return [from, to];
}

/** Update the URL's ?from=&to= to match the current range. Drops both params
 *  when the range covers the full data extent (clean URLs stay clean). */
function writeRangeToUrl() {
  if (!weeksAxis.length) return;
  const params = new URLSearchParams(window.location.search);
  const earliest = weeksAxis[0];
  const latest   = weeksAxis[weeksAxis.length - 1];
  if (currentFrom === earliest && currentTo === latest) {
    params.delete("from");
    params.delete("to");
  } else {
    params.set("from", currentFrom);
    params.set("to",   currentTo);
  }
  const qs = params.toString();
  const newUrl = window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash;
  history.replaceState({}, "", newUrl);
}

// --------- date range UI ---------

const rangeRow      = document.getElementById("range-row");
const presetsEl     = document.getElementById("presets");
const rangeFromIn   = document.getElementById("range-from");
const rangeToIn     = document.getElementById("range-to");
const rangeFromLbl  = document.getElementById("range-from-label");
const rangeToLbl    = document.getElementById("range-to-label");
const rsFill        = document.getElementById("rs-fill");

/** Update the slider DOM (input values, fill div, labels, preset highlight)
 *  to match the current state. Does NOT trigger re-render or URL sync. */
function syncRangeUI() {
  if (!weeksAxis.length) return;
  const fromIdx = weeksAxis.indexOf(currentFrom);
  const toIdx   = weeksAxis.indexOf(currentTo);
  rangeFromIn.value = String(fromIdx >= 0 ? fromIdx : 0);
  rangeToIn.value   = String(toIdx   >= 0 ? toIdx   : weeksAxis.length - 1);
  rangeFromLbl.textContent = currentFrom;
  rangeToLbl.textContent   = currentTo;

  const max = weeksAxis.length - 1;
  const fromPct = max > 0 ? (parseInt(rangeFromIn.value) / max) * 100 : 0;
  const toPct   = max > 0 ? (parseInt(rangeToIn.value)   / max) * 100 : 100;
  rsFill.style.left  = `${fromPct}%`;
  rsFill.style.width = `${toPct - fromPct}%`;

  const matched = rangeMatchesPreset(currentFrom, currentTo);
  for (const btn of presetsEl.querySelectorAll("button")) {
    btn.classList.toggle("active", btn.dataset.preset === matched);
  }
}

/** Apply a [from, to] selection: clamp, set state, sync UI, write URL, render. */
function setRange(from, to, { writeUrl = true } = {}) {
  if (!weeksAxis.length) return;
  const earliest = weeksAxis[0];
  const latest   = weeksAxis[weeksAxis.length - 1];
  if (from < earliest) from = earliest;
  if (to   > latest)   to   = latest;
  if (from > to) [from, to] = [to, from];
  currentFrom = from;
  currentTo   = to;
  syncRangeUI();
  if (writeUrl) writeRangeToUrl();
  if (currentMetrics) renderForRepo(currentMetrics, currentRepo);
}

/** Initialize the range from URL params or fall back to the default preset.
 *  Called once per data load. */
function initRangeFromData() {
  if (!weeksAxis.length) {
    rangeRow.hidden = true;
    return;
  }
  const max = weeksAxis.length - 1;
  rangeFromIn.min = "0";
  rangeFromIn.max = String(max);
  rangeToIn.min   = "0";
  rangeToIn.max   = String(max);

  const [urlFrom, urlTo] = parseRangeFromUrl();
  if (urlFrom && urlTo) {
    setRange(urlFrom, urlTo, { writeUrl: false });
  } else {
    const [pFrom, pTo] = computePresetRange(DEFAULT_PRESET_ID);
    setRange(pFrom, pTo, { writeUrl: false });
  }
  rangeRow.hidden = false;
}

// --------- wire up ---------

urlBtn.addEventListener("click", () => {
  const url = urlInput.value.trim();
  if (url) loadFromUrl(url, url);
});
urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") urlBtn.click();
});
fileInput.addEventListener("change", (e) => {
  const f = e.target.files?.[0];
  if (f) loadFromFile(f);
});

// Preset buttons.
presetsEl.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-preset]");
  if (!btn) return;
  const [from, to] = computePresetRange(btn.dataset.preset);
  if (from && to) setRange(from, to);
});

// Slider drag — enforce from <= to and re-render on input.
function onSliderInput() {
  let fromIdx = parseInt(rangeFromIn.value, 10);
  let toIdx   = parseInt(rangeToIn.value, 10);
  if (fromIdx > toIdx) {
    if (document.activeElement === rangeFromIn) toIdx = fromIdx;
    else                                        fromIdx = toIdx;
  }
  rangeFromIn.value = String(fromIdx);
  rangeToIn.value   = String(toIdx);
  setRange(weeksAxis[fromIdx], weeksAxis[toIdx]);
}
rangeFromIn.addEventListener("input", onSliderInput);
rangeToIn.addEventListener("input",   onSliderInput);

const src = decideInitialSource();
loadFromUrl(src.url, src.label);
