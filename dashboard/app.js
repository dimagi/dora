/* Dora dashboard — source loader + renderers.
 *
 * Source priority: ?url= > file input > localStorage > fixtures/sample.json
 */

const LS_KEY = "dora:lastUrl";

const urlInput  = document.getElementById("url-input");
const urlBtn    = document.getElementById("url-load");
const fileInput = document.getElementById("file-input");
const srcInfo   = document.getElementById("source-info");
const repoSel   = document.getElementById("repo-filter");
const repoLabel = document.querySelector(".repo-label");
const empty     = document.getElementById("empty-state");

let currentReport = null;
let currentSource = null;
let currentRepo   = null;

// --------- source loading ---------

function setEmpty(show) {
  empty.hidden = !show;
}

async function loadFromUrl(url, label) {
  srcInfo.textContent = `Loading ${label || url}…`;
  const res = await fetch(url);
  if (!res.ok) {
    srcInfo.textContent = `Failed to load ${label || url}: ${res.status}`;
    setEmpty(true);
    return;
  }
  const report = await res.json();
  currentReport = report;
  currentSource = { kind: "url", url, label };
  localStorage.setItem(LS_KEY, url);
  render();
  srcInfo.textContent = `Source: ${label || url} · loaded just now`;
  setEmpty(false);
}

async function loadFromFile(file) {
  const text = await file.text();
  currentReport = JSON.parse(text);
  currentSource = { kind: "file", name: file.name };
  render();
  srcInfo.textContent = `Source: ${file.name} (local file)`;
  setEmpty(false);
}

function decideInitialSource() {
  const params = new URLSearchParams(window.location.search);
  const qsUrl = params.get("url");
  if (qsUrl) return { kind: "url", url: qsUrl, label: qsUrl };

  const remembered = localStorage.getItem(LS_KEY);
  if (remembered) return { kind: "url", url: remembered, label: `${remembered} (remembered)` };

  return { kind: "url", url: "fixtures/sample.json", label: "sample (demo data)" };
}

// --------- repo filter ---------

function rowsForRepo(data) {
  if (!currentRepo) return data;
  return data.filter(r => r.repo === currentRepo);
}

function populateRepoFilter() {
  if (!currentReport) return;
  const repos = new Set();
  for (const m of currentReport.metrics) {
    for (const row of m.data) if (row.repo) repos.add(row.repo);
  }
  if (repos.size <= 1) {
    repoSel.hidden   = true;
    repoLabel.hidden = true;
    currentRepo      = null;
    return;
  }
  repoSel.innerHTML = "";
  for (const repo of [...repos].sort()) {
    const opt = document.createElement("option");
    opt.value = opt.textContent = repo;
    repoSel.append(opt);
  }
  repoSel.hidden   = false;
  repoLabel.hidden = false;
  currentRepo      = repoSel.value;
}

// --------- render dispatch ---------

function render() {
  populateRepoFilter();
  renderSummary();
  renderCharts();
  renderDetailTables();
  renderHotfixes();
}

// --------- summary tiles ---------

function renderSummary() {
  const el = document.getElementById("summary");
  el.innerHTML = "";
  const metric = currentReport.metrics.find(m => m.metric === "summary");
  if (!metric) return;
  const rows = rowsForRepo(metric.data);
  if (rows.length === 0) return;
  const r = rows[0];
  const tiles = [
    { label: "PRs",             value: r.prs ?? "—" },
    { label: "PRs / week",      value: r.prs_per_week ?? "—" },
    { label: "Median lead (h)", value: r.median_lead_h ?? "—" },
    { label: "CFR",             value: r.cfr ?? "—" },
  ];
  for (const t of tiles) {
    const div = document.createElement("div");
    div.className = "tile";
    div.innerHTML = `<div class="label">${escapeHtml(t.label)}</div>` +
                    `<div class="value">${escapeHtml(String(t.value))}</div>`;
    el.append(div);
  }
}

// --------- charts ---------

const charts = {};

function destroyChart(id) {
  if (charts[id]) {
    charts[id].destroy();
    delete charts[id];
  }
}

function weekAxis(rows) {
  return [...new Set(rows.map(r => r.week))].sort();
}

function makeLineChart(canvasId, labels, datasets, yLabel) {
  destroyChart(canvasId);
  const ctx = document.getElementById(canvasId).getContext("2d");
  charts[canvasId] = new Chart(ctx, {
    type: "line",
    data:  { labels, datasets },
    options: {
      responsive: true,
      interaction: { mode: "index", intersect: false },
      scales: {
        y: { title: { display: true, text: yLabel }, beginAtZero: true },
      },
    },
  });
}

function renderCharts() {
  renderSimpleWeekly("deploy-freq-prs",     "chart-deploy-freq-prs", "deploys", "PRs merged");
  renderSimpleWeekly("deploy-freq",         "chart-deploy-freq",      "deploys", "Deployments");
  renderLeadTime();
  renderSimpleWeekly("change-failure-rate", "chart-cfr",              "failure_pct", "CFR (%)");
}

function renderSimpleWeekly(metricName, canvasId, yField, yLabel) {
  const metric = currentReport.metrics.find(m => m.metric === metricName);
  if (!metric) return destroyChart(canvasId);
  const rows = rowsForRepo(metric.data);
  const labels = weekAxis(rows);
  const datasets = [{
    label: metricName,
    data:  labels.map(w => {
      const r = rows.find(x => x.week === w);
      return r ? r[yField] : null;
    }),
    tension: 0.2,
  }];
  makeLineChart(canvasId, labels, datasets, yLabel);
}

function renderLeadTime() {
  const metric = currentReport.metrics.find(m => m.metric === "lead-time");
  if (!metric) return destroyChart("chart-lead-time");
  const rows = rowsForRepo(metric.data);
  const labels = weekAxis(rows);
  const series = ["mean_h", "median_h", "p90_h"];
  const datasets = series.map(field => ({
    label: field.replace("_h", ""),
    data:  labels.map(w => {
      const r = rows.find(x => x.week === w);
      return r ? r[field] : null;
    }),
    tension: 0.2,
  }));
  makeLineChart("chart-lead-time", labels, datasets, "Hours");
}

// --------- detail tables ---------

function renderDetailTables() {
  const host = document.getElementById("detail-tables");
  host.innerHTML = "";
  const weeklyMetrics = ["deploy-freq-prs", "deploy-freq", "lead-time", "change-failure-rate"];
  for (const m of currentReport.metrics) {
    if (!weeklyMetrics.includes(m.metric)) continue;
    const rows = rowsForRepo(m.data);
    host.append(makeTable(m.metric, rows));
  }
}

function renderHotfixes() {
  const host = document.getElementById("hotfixes-table");
  host.innerHTML = "";
  const metric = currentReport.metrics.find(m => m.metric === "hotfixes");
  if (!metric) return;
  host.append(makeTable("hotfixes", rowsForRepo(metric.data)));
}

function makeTable(caption, rows) {
  const wrap = document.createElement("div");
  if (rows.length === 0) {
    wrap.innerHTML = `<p><em>${escapeHtml(caption)}: no data</em></p>`;
    return wrap;
  }
  const headers = Object.keys(rows[0]);
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const trh = document.createElement("tr");
  for (const h of headers) {
    const th = document.createElement("th");
    th.textContent = h;
    th.addEventListener("click", () => sortTable(table, headers.indexOf(h)));
    trh.append(th);
  }
  thead.append(trh);
  table.append(thead);
  const tbody = document.createElement("tbody");
  for (const r of rows) {
    const tr = document.createElement("tr");
    for (const h of headers) {
      const td = document.createElement("td");
      td.textContent = r[h] ?? "";
      tr.append(td);
    }
    tbody.append(tr);
  }
  table.append(tbody);
  const cap = document.createElement("caption");
  cap.textContent = caption;
  cap.style.cssText = "caption-side: top; text-align: left; padding: 0.5rem 0; font-weight: 600;";
  table.prepend(cap);
  wrap.append(table);
  return wrap;
}

function sortTable(table, colIdx) {
  const tbody = table.querySelector("tbody");
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const dir = table.dataset.sortCol === String(colIdx) && table.dataset.sortDir === "asc"
              ? "desc" : "asc";
  rows.sort((a, b) => {
    const av = a.children[colIdx].textContent;
    const bv = b.children[colIdx].textContent;
    const an = parseFloat(av);
    const bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return dir === "asc" ? an - bn : bn - an;
    return dir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
  });
  for (const r of rows) tbody.append(r);
  table.dataset.sortCol = String(colIdx);
  table.dataset.sortDir = dir;
}

// --------- utils ---------

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
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
repoSel.addEventListener("change", () => {
  currentRepo = repoSel.value;
  render();
});

const src = decideInitialSource();
loadFromUrl(src.url, src.label).catch(err => {
  console.error(err);
  srcInfo.textContent = `Failed to load ${src.label}: ${err.message}`;
  setEmpty(true);
});
