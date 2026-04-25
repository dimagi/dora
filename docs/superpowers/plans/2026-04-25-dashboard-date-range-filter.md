# Dashboard Date-Range Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a client-side date-range filter to the dashboard — preset buttons (4w / 12w / 26w / All) plus a two-handle slider over the week axis — that drives every panel (charts, KPIs, CFR drill-down, hotfixes), with the selection persisted via `?from=<week>&to=<week>` URL params.

**Architecture:** Three-file dashboard (HTML, CSS, JS); no new files. Data is week-bucketed; filter operates by lex-comparing ISO-week strings on each row's `week` field. Filter state lives in three globals (`weeksAxis`, `currentFrom`, `currentTo`); changes call the existing `renderForRepo()` path, so renderers don't change shape — they just consult one new helper. The two-handle slider is built from two overlapping `<input type="range">` elements (no library).

**Tech Stack:** Vanilla HTML / CSS / ES2022. No build step. No tests (per project spec; manual verification only).

**Working directory:** All paths relative to `/home/skelly/src/dora/`. Spec at `docs/superpowers/specs/2026-04-25-dashboard-date-range-filter-design.md` is the source of truth — if this plan and the spec disagree, stop and flag.

---

## Task 1: Add range-row markup + styles

**Files:**
- Modify: `dashboard/index.html`
- Modify: `dashboard/style.css`

After this task the range row appears on the page, the slider is draggable, but moving handles or clicking presets does nothing yet.

- [ ] **Step 1: Add range-row markup to `dashboard/index.html`**

Insert this block immediately after the `<div class="source-row">…</div>` closing tag and before the `<div id="loading" …>` line:

```html
    <div class="range-row" id="range-row" hidden>
      <span class="range-label-text">Range</span>
      <div class="presets" id="presets">
        <button type="button" data-preset="4">4w</button>
        <button type="button" data-preset="12">12w</button>
        <button type="button" data-preset="26">26w</button>
        <button type="button" data-preset="all">All</button>
      </div>
      <span class="range-week" id="range-from-label">—</span>
      <div class="range-slider" id="range-slider">
        <div class="rs-track"></div>
        <div class="rs-fill" id="rs-fill"></div>
        <input type="range" class="rs-input rs-from" id="range-from" min="0" max="0" value="0" aria-label="Range start">
        <input type="range" class="rs-input rs-to"   id="range-to"   min="0" max="0" value="0" aria-label="Range end">
      </div>
      <span class="range-week" id="range-to-label">—</span>
    </div>
```

- [ ] **Step 2: Add range-row + slider styles to `dashboard/style.css`**

Append this block at the end of the file:

```css
/* Date-range filter */
.range-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  margin-bottom: 24px;
  padding: 10px 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 13px;
}
.range-label-text {
  font-size: 12px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.presets {
  display: flex;
  gap: 4px;
}
.presets button {
  font: inherit;
  font-size: 12px;
  padding: 4px 10px;
  background: var(--surface-muted);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.1s, border-color 0.1s;
}
.presets button:hover { background: var(--accent-soft); }
.presets button.active {
  background: var(--accent);
  color: #ffffff;
  border-color: var(--accent);
}
.range-week {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-muted);
  min-width: 5.5rem;
}
.range-week:last-child { text-align: right; }

/* Two-handle range slider built from overlapping inputs.
   Tracks have pointer-events:none so neither input swallows clicks
   meant for the other handle; thumbs re-enable pointer-events. */
.range-slider {
  position: relative;
  height: 28px;
  flex: 1 1 14rem;
  min-width: 12rem;
}
.rs-track {
  position: absolute;
  top: 50%;
  left: 8px;
  right: 8px;
  height: 4px;
  background: var(--border);
  border-radius: 2px;
  transform: translateY(-50%);
}
.rs-fill {
  position: absolute;
  top: 50%;
  height: 4px;
  background: var(--accent);
  border-radius: 2px;
  transform: translateY(-50%);
  pointer-events: none;
}
.rs-input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 28px;
  margin: 0;
  background: transparent;
  pointer-events: none;
  -webkit-appearance: none;
  appearance: none;
}
.rs-input::-webkit-slider-runnable-track { background: transparent; height: 28px; }
.rs-input::-moz-range-track             { background: transparent; height: 28px; border: 0; }
.rs-input::-webkit-slider-thumb {
  pointer-events: auto;
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--accent);
  border: 2px solid var(--surface);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
  cursor: pointer;
}
.rs-input::-moz-range-thumb {
  pointer-events: auto;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--accent);
  border: 2px solid var(--surface);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
  cursor: pointer;
}
```

- [ ] **Step 3: Make the range row visible for verification**

Edit `dashboard/index.html` and *temporarily* remove the `hidden` attribute from the `<div class="range-row" id="range-row" hidden>` line so it reads `<div class="range-row" id="range-row">`. This lets us check the static layout.

- [ ] **Step 4: Manual verification**

Run: `cd dashboard && python3 -m http.server 8000`
Open: `http://localhost:8000/?url=fixtures/sample.json`

Expected:
- A range-row panel appears between the source-row and the dashboard.
- Four preset buttons render (4w / 12w / 26w / All) — none yet styled active.
- Slider widget shows a track and **two** thumbs, both initially at the left edge (since min/max are both `0`).
- Clicking the presets does nothing yet.
- No console errors.

Stop the server (Ctrl-C).

- [ ] **Step 5: Restore the `hidden` attribute**

Re-add `hidden` to `<div class="range-row" id="range-row">` so it reads `<div class="range-row" id="range-row" hidden>`. The element will be revealed by JS once data loads (Task 4).

- [ ] **Step 6: Commit**

```bash
git add dashboard/index.html dashboard/style.css
git commit -m "feat(dashboard): add range-row markup + styles

Static UI for the date-range filter — preset buttons and a two-handle
slider (overlapping inputs technique). Hidden by default; revealed by
JS in a later task once data loads. No interactivity yet."
```

---

## Task 2: Add filter state + pure helper functions

**Files:**
- Modify: `dashboard/app.js`

This task adds the data structures and pure helpers used by the renderers and event handlers in later tasks. Nothing wires up yet — verification is just "no console errors after the next reload."

- [ ] **Step 1: Replace the global state block in `dashboard/app.js`**

Find this block near the top of the file:

```javascript
let currentReport = null;
let currentRepo   = null;
let charts        = [];
```

Replace it with:

```javascript
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
  { id: "4",   weeks: 4,   label: "4w"  },
  { id: "12",  weeks: 12,  label: "12w" },
  { id: "26",  weeks: 26,  label: "26w" },
  { id: "all", weeks: null, label: "All" },
];
const DEFAULT_PRESET_ID = "12";
```

- [ ] **Step 2: Add the helper functions**

Append this block to `dashboard/app.js` immediately before the `// --------- wire up ---------` comment near the bottom of the file:

```javascript
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
    if (!r.week) return true;        // metric has no week (shouldn't happen for filtered metrics)
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

/** Filter hotfix rows: keep each `hotfix` row in range AND its trailing
 *  `preceded-by` rows (groups stay intact even if the prev row's date
 *  is technically outside the window). */
function inRangeHotfixes(rows) {
  if (!currentFrom || !currentTo) return rows;
  const fromDate = weekToMondayDate(currentFrom);
  const toDate   = weekToMondayDate(currentTo);
  if (!fromDate || !toDate) return rows;
  // Add 6 days to toDate to include the whole "to" week.
  const toEnd = (() => {
    const d = new Date(toDate + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + 6);
    return d.toISOString().slice(0, 10);
  })();
  const out = [];
  let keepGroup = false;
  for (const r of rows) {
    if (r.relation === "hotfix") {
      keepGroup = r.merged >= fromDate && r.merged <= toEnd;
      if (keepGroup) out.push(r);
    } else if (keepGroup) {
      out.push(r);
    }
  }
  return out;
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
  // Pair missing side with the data extent.
  if (!from) from = earliest;
  if (!to)   to   = latest;
  // Swap if reversed.
  if (from > to) [from, to] = [to, from];
  // Clamp to data range.
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
```

- [ ] **Step 3: Manual verification**

Run: `cd dashboard && python3 -m http.server 8000`
Open: `http://localhost:8000/?url=fixtures/sample.json`

Expected:
- Page renders identically to before (filter helpers exist but nothing calls them yet).
- Open browser console and check there are no errors.
- In console, type `weeksAxis` — should be `[]` (because we haven't yet called `computeWeeksAxis` from the load flow; that wires up in Task 4).
- In console, type `computePresetRange("12")` — should return `[null, null]` (empty axis, expected).

Stop the server.

- [ ] **Step 4: Commit**

```bash
git add dashboard/app.js
git commit -m "feat(dashboard): add date-range state + helper functions

Pure helpers only — no DOM wiring, no rendering changes yet.
Adds globals (weeksAxis, currentFrom, currentTo, currentMetrics),
PRESETS table, and helpers: computeWeeksAxis, inRange,
inRangeHotfixes, computePresetRange, rangeMatchesPreset,
parseRangeFromUrl, writeRangeToUrl."
```

---

## Task 3: Apply the filter inside renderers

**Files:**
- Modify: `dashboard/app.js`

This task plumbs the filter through the existing renderers. Range state isn't yet wired up to the UI — `currentFrom` / `currentTo` stay `null`, so `inRange()` is a no-op and the dashboard renders identically. But the call sites are in place so Task 4 just needs to flip switches.

- [ ] **Step 1: Cache `currentMetrics` on data load**

Find this block in `loadFromUrl`:

```javascript
    const report = await res.json();
    currentReport = report;
    localStorage.setItem(LS_KEY, url);
    urlInput.value = url;
    srcInfo.textContent = `Source: ${label || url}`;
    render();
```

Replace with:

```javascript
    const report = await res.json();
    currentReport  = report;
    currentMetrics = byMetric(report);
    localStorage.setItem(LS_KEY, url);
    urlInput.value = url;
    srcInfo.textContent = `Source: ${label || url}`;
    render();
```

Also update `loadFromFile` similarly:

```javascript
async function loadFromFile(file) {
  showState({ load: true });
  try {
    const text = await file.text();
    currentReport  = JSON.parse(text);
    currentMetrics = byMetric(currentReport);
    srcInfo.textContent = `Source: ${file.name} (local file)`;
    render();
  } catch (err) {
    console.error(err);
    showState({ err: `${file.name}: ${err.message}` });
  }
}
```

- [ ] **Step 2: Update `render()` to use the cached `currentMetrics`**

Find:

```javascript
function render() {
  showState({});
  dash.hidden = false;

  const metrics = byMetric(currentReport);
  const repos = uniqueRepos(metrics);
```

Replace with:

```javascript
function render() {
  showState({});
  dash.hidden = false;

  const metrics = currentMetrics;
  const repos = uniqueRepos(metrics);
```

(Same body afterwards.)

- [ ] **Step 3: Apply the filter in `renderForRepo`**

Find:

```javascript
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
```

Replace with:

```javascript
function renderForRepo(metrics, repo) {
  resetCharts();

  const freqPrs     = inRange(filterByRepo(metrics["deploy-freq-prs"]     || [], repo));
  const freqDeploys = inRange(filterByRepo(metrics["deploy-freq"]         || [], repo));
  const leadTime    = inRange(filterByRepo(metrics["lead-time"]           || [], repo));
  const cfr         = inRange(filterByRepo(metrics["change-failure-rate"] || [], repo));
  const cfrPrs      = inRange(filterByRepo(metrics["change-failure-prs"]  || [], repo));
  const hotfixes    = inRangeHotfixes(filterByRepo(metrics["hotfixes"]    || [], repo));
  // summary is not date-filterable; renderKPIs only uses it as a fallback,
  // and that fallback is dropped when filtering is active (see renderKPIs).
  const summary     = filterByRepo(metrics["summary"] || [], repo);

  renderKPIs(summary, freqPrs, freqDeploys, leadTime, cfr);
  renderFreqChart(freqPrs, freqDeploys);
  renderLeadChart(leadTime);
  renderCFRChart(cfr);
  renderCfrPrs(cfrPrs);
  renderHotfixes(hotfixes);
}
```

- [ ] **Step 4: Recompute KPIs over the full range; drop summary fallback when filtering**

Replace the entire `renderKPIs` function with:

```javascript
function renderKPIs(summary, freqPrs, freqDeploys, leadTime, cfr) {
  const filtering = currentFrom !== null && currentTo !== null;
  const s = filtering ? null : summary[0];
  const subText = filtering ? "in selected range" : "last 4 weeks";
  const leadSubText = filtering ? "median, in selected range" : "median, last 4 wk";

  // Deploy frequency.
  // When filtering: average across the selected range (all rows of freqDeploys
  // / freqPrs are already filtered). When not filtering: last 4 weeks proxy.
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
      subText: filtering ? "in selected range" : "across window",
      tier: cfrTier(cfrPct),
      info: "PRs labelled `caused-incident` ÷ all merged PRs across the window. Apply the label to the PR that SHIPPED the defect (not the PR that fixed it). See the drill-down list below the chart.",
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
```

- [ ] **Step 5: Manual verification**

Run: `cd dashboard && python3 -m http.server 8000`
Open: `http://localhost:8000/?url=fixtures/sample.json`

Expected: page renders identically to before this task (filter is active in code, but `currentFrom`/`currentTo` are still `null`, so `inRange()` is a no-op and `renderKPIs` takes its non-filtering path). No console errors.

Stop the server.

- [ ] **Step 6: Commit**

```bash
git add dashboard/app.js
git commit -m "feat(dashboard): plumb the date filter through renderers

Renderers now consult inRange() / inRangeHotfixes() after the per-repo
filter. KPIs branch on whether currentFrom/currentTo are set: when
filtering, drop the summary fallback (its 'whole window' value would
be misleading) and recompute over the full selected range instead of
last-4-weeks. With currentFrom still null, behavior is unchanged."
```

---

## Task 4: Wire the UI — presets, slider, and URL sync

**Files:**
- Modify: `dashboard/app.js`

After this task: clicking presets and dragging slider handles update the dashboard, the URL syncs both ways, and the range row reveals once data loads.

- [ ] **Step 1: Add the DOM-level helpers (range setter + slider rendering)**

Append this block to `dashboard/app.js` immediately above the `// --------- wire up ---------` comment:

```javascript
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
  // Set up slider min/max for current data.
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
```

- [ ] **Step 2: Hook `initRangeFromData` into the load flow**

Find the new line in `loadFromUrl`:

```javascript
    currentMetrics = byMetric(report);
```

Add right below it:

```javascript
    weeksAxis      = computeWeeksAxis(report);
    initRangeFromData();
```

The block becomes:

```javascript
    const report = await res.json();
    currentReport  = report;
    currentMetrics = byMetric(report);
    weeksAxis      = computeWeeksAxis(report);
    initRangeFromData();
    localStorage.setItem(LS_KEY, url);
    urlInput.value = url;
    srcInfo.textContent = `Source: ${label || url}`;
    render();
```

Apply the same insertion to `loadFromFile`:

```javascript
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
```

- [ ] **Step 3: Wire preset and slider event listeners**

Append this block at the very end of `dashboard/app.js`, after the existing `loadFromUrl(src.url, src.label);` line:

```javascript
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
  // If user dragged the lower handle past the upper, push the upper along
  // (and vice-versa). Standard two-handle slider behavior.
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
```

- [ ] **Step 4: Manual verification — basic interaction**

Run: `cd dashboard && python3 -m http.server 8000`
Open: `http://localhost:8000/?url=fixtures/sample.json`

Expected:
1. Range row appears under the source-row, with **`12w` highlighted** as active.
2. Both range labels show valid week strings (e.g. `2026-W04` and `2026-W14`).
3. KPI subtexts show "in selected range" / "median, in selected range".
4. Click `4w` → range narrows to the last 4 weeks; KPI numbers update; charts redraw.
5. Click `All` → range expands to the full data; URL params disappear (clean URL).
6. Drag the lower handle inward → the active preset deselects (no preset matches custom range); chart axes narrow; KPI numbers update.
7. URL updates as you interact (look at the address bar) — `?url=…&from=2025-W##&to=2025-W##`.

Stop the server.

- [ ] **Step 5: Manual verification — URL load + share**

Open: `http://localhost:8000/?url=fixtures/sample.json&from=2025-W44&to=2025-W48`

Expected:
- Page loads with that range applied; slider handles positioned at W44 and W48; no preset highlighted (or `4w`/`12w`/etc. only if it happens to match).
- Reload → same view.
- Manually edit URL to `?url=…&from=garbage` → page falls back to default 12w preset.

Stop the server.

- [ ] **Step 6: Manual verification — empty range**

In the URL bar, set `?url=fixtures/sample.json&from=2030-W01&to=2030-W52`.

Expected: range gets clamped back into the data range (since 2030 is past the data's latest week, both `from` and `to` clamp to `latest`). Result is a single-week range; charts/KPIs reflect that.

Stop the server.

- [ ] **Step 7: Commit**

```bash
git add dashboard/app.js
git commit -m "feat(dashboard): wire date-range UI + URL sync

Preset clicks and slider drags update state, redraw via the existing
renderForRepo path, and sync ?from=&to= in the URL. Default range on
cold load is the 12w preset (matches CLI --weeks 12). Range row stays
hidden until data with a non-empty week axis arrives."
```

---

## Task 5: Final verification + edge cases

**Files:**
- (Verification only — no code changes expected.)

- [ ] **Step 1: Test all four panels respect the filter**

Run: `cd dashboard && python3 -m http.server 8000`
Open: `http://localhost:8000/?url=fixtures/sample.json`

For each preset (4w, 12w, 26w, All):
- KPI cards: "Deploy frequency" / "Lead time" numbers change with range size.
- Combined deploy-frequency chart: x-axis spans the selected weeks only.
- Lead-time chart: same.
- CFR bar chart: same.
- "Incident-causing PRs" details: count shrinks as you narrow.
- Hotfix panel: hotfix groups appear/disappear based on whether the hotfix's `merged` date is in range. Preceded-by rows under each kept hotfix are still attached even if their dates are technically outside.

- [ ] **Step 2: Test reload + browser back/forward**

- Click `26w`, then back-button. Browser history should not step through individual slider movements (we use `replaceState`).
- Reload the page → range from URL is restored.
- Change `?from=` to a week that doesn't exist (e.g. `2099-W01`) → falls back gracefully (clamped to `latest`).

- [ ] **Step 3: Test repo switch (multi-repo report — manual setup)**

Skip this step if `fixtures/sample.json` only has one repo (the case for the OCS-derived sample). The interaction is exercised in code regardless: repo dropdown's `onchange` calls `renderForRepo(currentMetrics, currentRepo)`, which already consults `inRange()`.

If you want to test multi-repo manually, edit `fixtures/sample.json` to duplicate a metric block under a second repo name temporarily — but this isn't required.

- [ ] **Step 4: Confirm full test suite still passes**

Run: `uv run pytest -v 2>&1 | tail -3`
Expected: 43 tests pass (no Python changes were made; this is just a sanity check that the dashboard work didn't accidentally touch backend code).

- [ ] **Step 5: Review the full diff before merging**

```bash
git log --oneline main ^origin/main 2>/dev/null || git log --oneline -10
git diff origin/main...HEAD -- dashboard/ 2>/dev/null | wc -l
```

Expect ~600-800 added lines across the three dashboard files.

- [ ] **Step 6: No further commit needed**

This task is verification only. If anything failed in steps 1-3, return to Task 4 to fix.

---

## Out of scope (per spec)

- Calendar date picker
- Compare two ranges side-by-side
- Server-side filtering / changes to `report.json` schema
- Automated browser tests
