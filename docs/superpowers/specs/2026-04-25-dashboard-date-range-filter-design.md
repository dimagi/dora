# Dashboard date-range filter

**Date:** 2026-04-25
**Status:** Draft — pending review

## Goal

Let dashboard users narrow the visible window to an arbitrary range of weeks. Affects every panel: charts, KPI cards, the CFR PR drill-down, and the hotfix list. Range is shareable via URL.

## Non-goals

- Day-level granularity. Data is week-bucketed; filter operates on whole ISO weeks.
- Server-side filtering. Filter is purely client-side. The CLI's `report.json` is unchanged.
- New tests. Dashboard is unverified by tests today (per the project spec); manual verification only.
- Custom date pickers (calendar widget). Slider + presets is enough; if a calendar becomes necessary later it slots in alongside.

## UI

A new control row sits between the source-row and the dashboard header — visible above the KPIs so it's clearly the master control for everything below:

```
┌──────────────────────────────────────────────────────────────┐
│ [URL input……………] [Load URL] [Upload]   Source: …            │ source-row (existing)
├──────────────────────────────────────────────────────────────┤
│ Range:  [4w] [12w*] [26w] [All]   2025-W42 ◀──████──▶ 2026-W14│ NEW
├──────────────────────────────────────────────────────────────┤
│ DORA metrics                  Data since … · View source ↗   │ header (existing)
│ acme/example                  Repo dropdown                  │
├──────────────────────────────────────────────────────────────┤
│ KPIs · charts · CFR + drill-down · hotfixes                  │ panels (existing)
└──────────────────────────────────────────────────────────────┘
```

### Preset buttons

Four buttons on the left: `4w`, `12w`, `26w`, `All`. The active preset gets a highlighted style. Default on cold load is `12w` (matches the CLI's `--weeks 12` convention).

A preset's "from" week is computed as `latestWeek - (N-1) weeks`. `All` sets `from = earliestWeek`. `to` always equals `latestWeek` for a preset click.

### Range slider

Two-handle range over the week axis (`weeksAxis = sorted unique weeks across all metrics`). Implemented as **two overlapping `<input type="range">` elements** with the well-known no-library overlapping-thumbs technique:

- Each input's `value` is an integer index into `weeksAxis`.
- `min=0`, `max=weeksAxis.length - 1`.
- Lower-handle's `pointer-events: none` on the track, `auto` on the thumb (and vice-versa for the upper handle).
- Visible labels above/beside the slider show the current `from` and `to` weeks (`2025-W42` style), driven by JS on input.

### Preset/slider interaction

- Clicking a preset moves the slider's two values to match.
- Dragging the slider deselects all presets — UNLESS the resulting range happens to match a preset (e.g. you drag to exactly the last 4 weeks), in which case that preset highlights again.
- A `rangeMatchesPreset(weeks, from, to)` helper checks each preset's [from, to] against the current selection.

## Filter semantics

**Inclusion rule** (used by `applyDateFilter(rows, from, to)`): a row is kept iff its `week` field satisfies `from <= row.week <= to` lexically. ISO week strings sort correctly (`2025-W42 < 2026-W01`).

For the hotfix metric, rows have a `merged` field (YYYY-MM-DD) instead of `week`. Filter on `merged[:10]` against the from/to weeks' Monday dates. **Preceding-merge rows that follow a hotfix stay attached to their hotfix even if their `merged` date is technically outside the window** — keeping investigation groups intact is more important than strict filtering on a per-row basis.

### KPI recomputation

| KPI | Today | After filter |
|---|---|---|
| Deploy frequency | avg deploys/week, last 4 weeks | avg deploys/week across selected range |
| Lead time | mean of weekly medians, last 4 wk | mean of weekly medians across selected range |
| Change failure rate | total failures ÷ total merges, full window | total failures ÷ total merges, selected range |
| MTTR | N/A | N/A (unchanged) |

Subtext labels switch from "last 4 weeks" / "across window" → **"in selected range"** so the meaning is unambiguous.

Tier-band logic (Elite/High/Medium/Low) is unchanged. Same thresholds, narrower input.

### `summary` metric becomes fallback-only (and dropped when filtering)

Today, `summary` is consulted as a third-tier fallback in three KPI computations (when weekly data is empty). With the filter active, those fallbacks are **dropped** — the summary's "across whole window" value would be misleading inside a narrowed range. If the selected range has no weekly data, the KPI shows `—` rather than the summary number.

In practice with a non-empty report, weekly data is always present for the default 12w window, so `summary` was already dead-code fallback. This change makes the dashboard self-sufficient — `summary` is only used when the user has explicitly dragged to a range with no data, and even then we prefer the honest `—`.

## URL sync

### Params

`?from=<week>&to=<week>` alongside the existing `?url=…`. Example:

```
https://dimagi.github.io/dora/?url=…/r.json&from=2025-W42&to=2026-W14
```

### Sync direction

Slider drag-end / preset click → `history.replaceState({}, "", newUrl)` updates the `?from`/`?to` params. No scroll, no history clutter (we use `replaceState`, not `pushState` — back/forward shouldn't step through every slider tick).

When range returns to "All" (matches data extents), the params are removed entirely, so a clean URL stays clean.

### Cold load priority

1. `?from` and `?to` both present and parseable → apply.
2. Only one of them present → pair with the data's natural extent on the missing side (`from = earliestWeek` or `to = latestWeek`).
3. Neither present → default to the **12w preset** computed from the data's own latest week.

### Validation

- Out-of-range weeks → clamp to the data's `[earliestWeek, latestWeek]` bounds.
- `from > to` → swap them silently.
- Bad-format values (not in `YYYY-W##` shape) → ignore the offending param, fall back to the natural extent for that side.

## Edge cases

- **Empty range** (slider dragged to a no-data span): all charts show their existing per-panel "No data yet" message; KPIs show `—`. No special UI.
- **Single-week data**: `weeksAxis.length === 1` → slider min == max. Both handles snap to the same week, presets all collapse to "All". Acceptable degenerate state.
- **Repo switch**: range persists across repo dropdown changes. The user's range is about *time*, not *repo*.
- **Range outlives data refresh**: if the user is on a stale page and someone uploads a longer report.json, the existing range stays valid (clamps if needed). New data won't suddenly auto-show without a reload.

## Implementation notes

### Module/file boundaries

All changes are in `dashboard/`:

- `index.html` — new range-row markup (preset buttons + slider + labels).
- `style.css` — preset-button styles + two-handle slider CSS (overlapping inputs technique).
- `app.js` — new state (`currentFrom`, `currentTo`, `weeksAxis`), new helpers (`applyDateFilter`, `rangeMatchesPreset`, `setRange`, `syncUrlParams`), and a re-wiring of every renderer to consult `applyDateFilter` after `rowsForRepo`.

No new files. The dashboard surface stays three files.

### Re-render flow

Any of {preset click, slider drag-end, repo dropdown change, fresh-data load} → call existing `renderForRepo(metrics, currentRepo)`, which already invokes every per-section renderer. The renderers each call a new `inRange(rows)` step after `rowsForRepo(rows)`. Charts use `chart.update()` against new datasets (already destroy-and-recreate today; we keep that pattern).

### Slider implementation reference

The two-overlapping-input pattern is well-documented; the typical structure:

```html
<div class="range-slider">
  <input type="range" id="range-from" min="0" max="N-1" value="0">
  <input type="range" id="range-to"   min="0" max="N-1" value="N-1">
  <div class="range-track"></div>
  <div class="range-fill"></div>
</div>
```

CSS gives the `.range-fill` a width based on the gap between the two thumbs (computed in JS on input). Both `<input>`s overlap absolutely; the lower one's track is z-indexed below the upper one. Each input has `pointer-events: none` on its track and `auto` on its thumb so neither input "eats" clicks meant for the other handle.

### Tests

None. The dashboard has no test harness today and the project spec explicitly defers browser tests. Manual verification: open `dashboard/fixtures/sample.json` with `?from=`/`?to=` variations and confirm charts/KPIs/lists update correctly.

## Future work

- **Calendar date picker** — if week-level granularity becomes limiting (probably never).
- **Compare two ranges** — overlay W12-W24 vs W36-W48 on the same chart. Larger feature; out of scope.
