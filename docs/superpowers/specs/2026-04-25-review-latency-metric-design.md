# `review-latency` metric: PR review time, controlled for size

**Date:** 2026-04-25
**Status:** Draft — pending review

## Goal

Add a new metric, `review-latency`, that tells the team how long PRs sit in review, controlled for the size of the change. The current `lead-time` metric measures `first_commit_at → merged_at` — it conflates dev work with review wait, and a 5-line typo PR is compared against a 1000-line refactor as if they were the same animal.

`review-latency` answers a different question: *"once a PR is open and ready for review, how long does it take to land, given how big it is?"*

## Non-goals

- Replacing `lead-time`. The two metrics measure different things; both stay.
- Per-reviewer attribution. This is a process-health signal, not a performance review.
- A single scalar "review effort" number. Bucketed comparison is the design.
- Dashboard exposure of `additions` / `deletions`. They're stored for future use only.
- A backfill pass for legacy DB rows. Coverage ramps forward from the next `dora pull`. A `--rebuild` flag is parked as future work.

## Definition

### Per-PR review window

```
review_window_hours =
    (merged_at − COALESCE(ready_for_review_at, opened_at)) × 24
```

- `ready_for_review_at` is populated only for PRs that were ever drafts (from the GitHub timeline `ready_for_review` event); otherwise `NULL`, and the formula falls through to `opened_at`.
- Only merged PRs are included (`merged_at IS NOT NULL`). Open PRs have no terminal latency. Matches the convention used by `lead-time` and `change-failure-rate`.

### Size signal

`changed_files` (from `/pulls/{n}.changed_files`). Lines changed (`additions + deletions`) is also stored, but not used by this metric — see *Future work* for why it's there.

PRs are binned into four fixed buckets:

| Bucket | `changed_files` | Mental model |
|--------|-----------------|--------------|
| XS | 1 | Trivial single-file change |
| S | 2–3 | Tightly scoped |
| M | 4–9 | Feature-sized |
| L+ | 10+ | Sprawling |

Boundaries are fixed (not percentile-based) so that "the median S-bucket review latency this week" has a stable meaning across weeks, repos, and teams. Tweaking the cuts later is a one-line change but should be a deliberate decision, not a quiet drift.

### Aggregation

Group by `(repo, week, bucket)` where `week = strftime('%Y-W%W', merged_at)`. Per group, compute:

- `n_prs` — PR count
- `median_h` — median `review_window_hours`, rounded to 1 decimal place
- `p90_h` — nearest-rank 90th percentile, rounded to 1 decimal place

Aggregation happens in Python (consistent with `lead-time` — SQLite has no `PERCENTILE_CONT`, and nearest-rank is fine for small weekly samples).

### Output rows

```
repo | week | bucket | n_prs | median_h | p90_h
```

Bucket is rendered as a string label (`"XS"`, `"S"`, `"M"`, `"L+"`) so the dashboard renderer can pick colors and order without re-deriving from numeric ranges.

### Edge cases

- A `(repo, week, bucket)` group with `n_prs == 0` produces no row. The dashboard renders missing weeks as gaps, not zeros — a quiet week with no XL PRs shouldn't drag the L+ line to zero.
- PRs with `changed_files IS NULL` (legacy DB rows from before the schema change) are excluded — they can't be bucketed. README documents that metric coverage starts from the first pull on the new code.
- PRs with `merged_at < ready_for_review_at` (theoretically possible if a PR was merged before the timeline event was processed; in practice, near-impossible) are clamped: the formula would produce a negative number, and the metric would be misleading. We exclude these defensively (`WHERE review_window_hours >= 0`).

## Data: schema + fetch impact

### New columns on `pull_requests`

All nullable, populated on the next `dora pull` against the new code:

| Column | Type | Source |
|--------|------|--------|
| `additions` | INTEGER | `/pulls/{n}.additions` |
| `deletions` | INTEGER | `/pulls/{n}.deletions` |
| `changed_files` | INTEGER | `/pulls/{n}.changed_files` |
| `ready_for_review_at` | TEXT | first `ready_for_review` event from `/issues/{n}/timeline` |

### New API calls in `github.py`

The existing flow fetches the PR list (paginated `/pulls`) once, then makes per-PR calls only on the **unknown-PR** branch. This metric extends that branch:

- *Existing:* `GET /repos/{r}/pulls/{n}/commits` for `first_commit_at`.
- *New:* `GET /repos/{r}/pulls/{n}` for `additions`, `deletions`, `changed_files`.
- *New:* `GET /repos/{r}/issues/{n}/timeline`, paginated; walk events in chronological order, return the first `event: "ready_for_review"` timestamp; stop early. In practice this almost always lands in the first page (`per_page=100`).

So per **new** PR: 3 API calls instead of 1 (commits + pull + timeline). Per **known** PR: still 0 — the COALESCE pattern in `upsert_pr` already preserves stored values when the fetch returns `None`.

We don't try to detect "was this ever a draft" from list metadata. The `draft` field reflects current state only; a PR that was a draft and then got marked ready shows `draft: false` indistinguishably from one that was never a draft. Cheaper-but-wrong heuristics aren't worth the bug surface — we just call timeline on every new PR.

### Migration

`init_db()` gains a small ALTER-TABLE-ADD-COLUMN sweep keyed off `PRAGMA table_info(pull_requests)`. Adds the four columns if they don't exist; otherwise no-op. Idempotent. SQLite supports `ALTER TABLE ... ADD COLUMN` for nullable columns without a default, which is what we need.

No data backfill: legacy rows stay `NULL` for the four columns until they're naturally re-fetched (which only happens for PRs that get re-touched and reappear as "unknown" — i.e., almost never for old merged PRs). Metric coverage therefore ramps **forward** from the first pull on the new code. Documented in the README.

## Module placement

- `metrics.py` — new constants `BUCKETS = [("XS", 1, 1), ("S", 2, 3), ("M", 4, 9), ("L+", 10, None)]`, new function `m_review_latency(conn, since)`, and one new entry in the `METRICS` dict.
- `db.py` — new column definitions in `SCHEMA`, new migration helper `_migrate_add_columns(conn)` called from `init_db()`.
- `github.py` — extend `fetch_prs` to make the two new API calls on the unknown-PR branch. Add a small helper `_fetch_ready_for_review_at(session, repo, number)` that paginates `/issues/{n}/timeline` and short-circuits on the first matching event.
- `pull.py` — pass the new fields through to `upsert_pr`. The yielded dict gains four keys.

No new modules. The metric is small enough to live alongside the others.

## Dashboard

### Placement

New 5th panel inside `<section class="panels">`, sibling to the existing four (Deploy frequency, Lead time, Change failure rate, Recent hotfixes). The container already wraps; a fifth tile slots in beside Recent hotfixes naturally — same shape as today, one tile heavier. No layout redesign.

### Panel

- **Title:** "Review latency"
- **Sub-title:** "Median hours waiting for review, by PR size"
- **Info tooltip on the sub-title:** bucket boundaries (`XS=1, S=2-3, M=4-9, L+=10+`) and the time-window definition (`merged − ready_for_review (or opened, if never drafted)`). Reuses the existing tooltip styles in `style.css`.
- **Legend:** four dots — XS / S / M / L+
- **Chart:** Chart.js line chart, 4 series (one per bucket), x-axis `week`, y-axis `median_h`. Same colors-via-CSS-variables convention as the other panels.

### Renderer

`app.js` gains a renderer keyed by metric name `review-latency`, registered in the existing dispatch. The spec's "unknown metrics fall back to a raw table" rule means a CLI-first rollout to a team that hasn't pulled the new dashboard still gets the raw weekly numbers — graceful degradation, no broken dashboard.

### Where `p90_h` lives

The main chart shows `median_h` only. `p90_h` is preserved in the row and ends up in the JSON output (`dora report --format json` and `dashboard/fixtures/sample.json`), accessible to anyone who wants the tail. The dashboard panel itself doesn't render a tail visualization.

The original 2026-04-24 design sketch mentioned a collapsible "Weekly metrics (raw, sortable)" section, but that section was never built in the first cut. If/when a generic raw-table renderer is added, it'll pick up `p90_h` automatically since the column is already in the metric output.

### Filters

- **Repo dropdown:** rows have a `repo` column, so the existing repo filter wires up for free.
- **Date range:** the recently added range filter plumbs through all renderers; new panel inherits it.

### KPI tile

Considered and deferred. A single "median S-bucket review latency" number loses the bucket comparison that's the whole point of the metric. The four-line chart is the smallest representation that still communicates.

## Testing

- **`tests/test_db.py`** — new test: ALTER-TABLE migration is idempotent. Run `init_db` twice on the same path; second call is a no-op. Run `init_db` on a DB that pre-dates the migration (manually `CREATE TABLE` the old schema) and assert the four new columns appear.
- **`tests/test_github.py`** — `requests-mock` covers:
  - `/pulls/{n}` returns size fields; they reach the yielded dict.
  - `/issues/{n}/timeline` with a `ready_for_review` event in the first page → `ready_for_review_at` is the event timestamp.
  - Timeline with no `ready_for_review` event → `ready_for_review_at` is `None`.
  - Timeline event on page 2 (forces a pagination follow) → still found.
  - Known PR (in `known_prs`) → none of the three new endpoints are hit.
- **`tests/test_metrics.py`** — new test for `m_review_latency`:
  - Seed PRs spanning all four buckets (`changed_files` of 1, 3, 7, 25).
  - Include one PR with a non-NULL `ready_for_review_at` later than `opened_at` — verify the formula uses `ready_for_review_at`.
  - Include a PR with `changed_files IS NULL` — verify it's excluded.
  - Verify median + p90 rounding and bucket label assignment.
- **`tests/test_cli.py`** — smoke test: `dora report --metric review-latency --format json` exits 0 and produces parseable output.

No dashboard browser tests (consistent with the existing testing scope).

## Documentation

- README gains a short paragraph in the metrics list, with the bucket boundaries and a one-line "what it tells you."
- README's "Known limitations" section gains: "metric coverage ramps forward from the first pull after upgrade; old PRs stay excluded until re-fetched."
- The `dora report --help` description of `--metric` automatically picks up the new entry from the `METRICS` dict.

## Future work

1. **`--rebuild` flag** for `dora pull` — forces re-fetch of all PRs in the window, populating size + draft fields on legacy rows. Useful when adopting this metric on a long-running DB.
2. **Surface `additions + deletions`** in the dashboard, behind a toggle, once the lockfile/generated-file noise question has a real answer (path-exclusion config, perhaps per-team).
3. **Bucket boundary tuning** — collect a few months of real data, see if the `1 / 2-3 / 4-9 / 10+` cuts hold up, adjust if a different distribution is more informative.
4. **`review-latency-strict`** variant excluding PRs with `caused-incident` or `hotfix` labels — those are abnormal flows and may distort the central tendency. Defer until we see whether they actually do.
5. **Promote panel colors to CSS variables.** The 5th panel currently uses 4 hardcoded hex values for the per-bucket lines (`dashboard/app.js`'s `REVIEW_LATENCY_BUCKETS`), because the existing `--chart-*` palette only has three slots. Adding `--chart-bucket-{xs,s,m,l}` vars in `style.css` and reading them via `readVar` would give the panel automatic light/dark-mode adaptation like the other charts.
