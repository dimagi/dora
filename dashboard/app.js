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

let currentReport = null;
let currentRepo   = null;
let charts        = [];

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
    currentReport = report;
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
    currentReport = JSON.parse(text);
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

  const metrics = byMetric(currentReport);
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

  const freqPrs     = filterByRepo(metrics["deploy-freq-prs"]     || [], repo);
  const freqDeploys = filterByRepo(metrics["deploy-freq"]         || [], repo);
  const leadTime    = filterByRepo(metrics["lead-time"]           || [], repo);
  const cfr         = filterByRepo(metrics["change-failure-rate"] || [], repo);
  const cfrPrs      = filterByRepo(metrics["change-failure-prs"]  || [], repo);
  const hotfixes    = filterByRepo(metrics["hotfixes"]            || [], repo);
  const summary     = filterByRepo(metrics["summary"]             || [], repo);

  renderKPIs(summary, freqPrs, freqDeploys, leadTime, cfr);
  renderFreqChart(freqPrs, freqDeploys);
  renderLeadChart(leadTime);
  renderCFRChart(cfr);
  renderCfrPrs(cfrPrs);
  renderHotfixes(hotfixes);
}

function renderKPIs(summary, freqPrs, freqDeploys, leadTime, cfr) {
  const s = summary[0];

  // Deploy frequency: last 4 weeks of actual deploys, else PRs, else summary.
  const recentDeploys = recentN(freqDeploys, 4);
  const recentPrs     = recentN(freqPrs, 4);
  const deployPerWk =
    recentDeploys.length
      ? recentDeploys.reduce((a, r) => a + (r.deploys || 0), 0) / 4
      : recentPrs.length
      ? recentPrs.reduce((a, r) => a + (r.deploys || 0), 0) / 4
      : s?.prs_per_week ?? null;
  const deployUnit = recentDeploys.length ? " deploys/wk" : " merges/wk";

  // Lead time: last 4 weeks median, averaged. Fall back to summary.
  const recentLead = recentN(leadTime, 4);
  const leadMedian =
    recentLead.length
      ? recentLead.reduce((a, r) => a + (r.median_h || 0), 0) / recentLead.length
      : s?.median_lead_h ?? null;

  // CFR: all rows in window, total failures / total merges.
  const totals = cfr.reduce(
    (acc, r) => ({ d: acc.d + (r.deploys || 0), f: acc.f + (r.failures || 0) }),
    { d: 0, f: 0 }
  );
  const cfrPct =
    totals.d > 0 ? (100 * totals.f) / totals.d
    : s?.cfr != null ? parseFloat(String(s.cfr).replace("%", ""))
    : null;

  document.getElementById("kpis").innerHTML = [
    kpiCard({
      label: "Deploy frequency",
      value: deployPerWk != null ? deployPerWk.toFixed(1) : "—",
      unit: deployUnit,
      subText: "last 4 weeks",
      tier: deployFreqTier(deployPerWk),
      info: recentDeploys.length
        ? "Average successful deploys per week, last 4 weeks. Source: GitHub Deployments API for the configured environment (success + inactive statuses)."
        : "Average merged PRs per week (proxy for shipped changes), last 4 weeks. Source: PRs merged into the base branch — used because no Deployments are recorded.",
    }),
    kpiCard({
      label: "Lead time",
      value: leadMedian != null ? Math.round(leadMedian).toString() : "—",
      unit: " h",
      subText: "median, last 4 wk",
      tier: leadTimeTier(leadMedian),
      info: "Median hours from first commit on a PR's branch to its merge into the base branch, averaged over the last 4 weeks. Source: PR commits + merge timestamp from the GitHub API.",
    }),
    kpiCard({
      label: "Change failure rate",
      value: cfrPct != null ? cfrPct.toFixed(0) : "—",
      unit: " %",
      subText: "across window",
      tier: cfrTier(cfrPct),
      info: "Across the full window: PRs labelled `caused-incident` ÷ all merged PRs. Apply the label to the PR that SHIPPED the defect (not the PR that fixed it). See the drill-down list below the chart.",
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

const src = decideInitialSource();
loadFromUrl(src.url, src.label);
