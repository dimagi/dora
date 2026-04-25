# Turn `dora` into a hostable GitHub project

**Date:** 2026-04-24
**Status:** Draft — pending review

## Goal

Turn the three-script `dora` collection into a proper public GitHub project that other Dimagi teams (and anyone else who adopts the same label conventions) can install and use. Two deliverables:

1. **A Python CLI** (`dora`) — fetches DORA signals from GitHub, runs metric queries, emits JSON. Runs locally or in GitHub Actions. Replaces the Google Sheets push with an optional S3 upload.
2. **A static dashboard** — hosted on GitHub Pages from this repo. Loads any `report.json` via a URL query param or file upload. Renders summary tiles, weekly charts, and detail tables.

## Non-goals

- Publishing to PyPI now (can be added later; `uv tool install git+...` is sufficient).
- Multi-report "team switcher" dashboard (design keeps the door open via a future manifest).
- MTTR automation.
- Non-S3 upload targets (GCS, Azure, scp) — not required.
- Dashboard browser tests.

## Audience

- Primary: Dimagi teams with their own repos and deploy environments.
- Secondary: anyone who adopts the same PR label conventions (`caused-incident`, `hotfix`).

The code is already generic; the cleanup is removing any incidental OCS-specific naming in docs and defaults, and giving adopters a template CI workflow.

## Architecture

Two concerns, one repo:

- **CLI** (`src/dora/`, Python package) — `dora pull`, `dora report`, `dora upload`.
- **Dashboard** (`dashboard/`, static site) — served by GitHub Pages from this repo.

Teams adopting the tool do *not* fork this repo. They install the CLI in their own repo's CI, produce a `report.json`, host it (commit back to their repo OR S3), and share the dashboard URL with `?url=<their-report>`.

### Data flow

```
Adopting team's repo                           This repo (dora)
────────────────────                           ────────────────
CI (cron) runs:                                dashboard/ deployed to
  dora pull --repo X --since Y                 https://<owner>.github.io/dora/
  dora report --format json --output r.json
  either:
    (A) git commit r.json  ──► team's repo @ raw.githubusercontent.com
    (B) dora upload r.json --target s3://...  ──► S3
                                                        │
                                                        ▼
                                    https://<owner>.github.io/dora/?url=<either above>
```

### Repo layout

```
dora/
├── pyproject.toml              # Package config, entry point `dora` -> dora.cli:main
├── README.md                   # User-facing: install, usage, adoption recipe
├── LICENSE                     # BSD-3-Clause (subject to user confirmation)
├── .gitignore                  # dora.db, *.egg-info, __pycache__, .venv
├── src/dora/
│   ├── __init__.py
│   ├── cli.py                  # Argparse, subcommand dispatch
│   ├── pull.py                 # GitHub fetch -> SQLite (from dora_pull.py)
│   ├── report.py               # Metric runner + formatters (from dora_report.py)
│   ├── metrics.py              # Each metric as a pure function (SQL + post-processing)
│   ├── db.py                   # Schema, connection, upserts
│   ├── github.py               # API client: auth, pagination, rate limits
│   └── upload.py               # S3 target (optional extra: dora-metrics[s3])
├── tests/
│   ├── conftest.py             # fixture_db builder
│   ├── fixtures/
│   │   └── seed.sql
│   ├── test_metrics.py
│   ├── test_github.py          # requests-mock
│   └── test_cli.py             # Subcommand smoke tests
├── dashboard/                  # GitHub Pages source (NOT docs/, to avoid collision with specs)
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   └── fixtures/sample.json    # Anonymized demo data (repos -> acme/example)
├── docs/
│   └── superpowers/specs/      # Design specs (this file lives here)
├── examples/
│   └── workflows/
│       └── dora-report.yml     # Template CI for adopting teams to copy
└── .github/workflows/
    ├── pages.yml               # Deploys dashboard/ to Pages on push to main
    ├── test.yml                # pytest on PRs
    └── release.yml             # (optional, later) tags -> GitHub Release
```

**Why `dashboard/` not `docs/` for Pages:** `docs/superpowers/specs/` is the spec location per the brainstorming skill convention. If Pages served `docs/`, specs would be public. Using `dashboard/` as the Pages source keeps concerns separated, and is more descriptive.

## CLI

### Entry point

```toml
# pyproject.toml (key sections)
[project]
name = "dora-metrics"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["requests"]

[project.optional-dependencies]
s3 = ["boto3"]
dev = ["pytest", "requests-mock"]

[project.scripts]
dora = "dora.cli:main"
```

- **Package name** `dora-metrics` (PyPI-safe; `dora` on PyPI is taken).
- **CLI binary** `dora`.
- **Install:** `uv tool install git+https://github.com/<owner>/dora` (or `...dora-metrics[s3]` once published).

### Subcommands

| Command | Behavior | Flags |
|---|---|---|
| `dora pull` | Fetch from GitHub into SQLite. Same behavior as current `dora_pull.py`. | `--repo` (repeatable, required), `--since` (required), `--db` (default `dora.db`), `--base` (default `main`), `--environment` (default `production`), `--skip-prs`, `--skip-deployments` |
| `dora report` | Run metric queries, emit table/CSV/JSON. | `--db` (default `dora.db`), `--weeks` (default 12), `--metric` (repeatable, default all), `--format {table,csv,json}` (default `table`), `--output FILE` (new; stdout if omitted) |
| `dora upload` | Upload a file to a target URL. | positional `PATH`, `--target s3://bucket/key` (required), `--content-type` (default `application/json`), `--public-read` (opt-in S3 ACL) |

**New vs today:** `--output FILE` on `report` (convenience for CI — avoids shell redirection subtleties).
**Removed vs today:** `dora_push_sheets.py` — replaced by `dora upload` (S3 only).

### Auth conventions (unchanged)

- GitHub: `gh auth token` first, then `$GITHUB_TOKEN`.
- S3: default `boto3` credential chain (env vars, `~/.aws/credentials`, IAM role). No `dora`-specific flags.

### Module boundaries

- `metrics.py` owns all SQL and post-processing. Each metric is a pure function `(conn, since) -> (headers, rows)`. Adding a metric = one function + one entry in the `METRICS` dict.
- `db.py` owns schema DDL and upsert SQL. Consumed by both `pull.py` and `report.py`.
- `github.py` owns the HTTP session, pagination generator, rate-limit sleep-and-retry. Unit-testable with `requests-mock`.
- `cli.py` is thin: argparse setup, subcommand dispatch. Each subcommand is a function returning an exit code.

### Constants (unchanged from current code)

- `TERMINAL_DEPLOY_STATUSES = {"success", "failure", "error", "inactive"}`
- `SUCCESS_DEPLOY_STATUSES = ("success", "inactive")`
- `FAILURE_LABELS = ("caused-incident",)`

These live in `metrics.py` / `pull.py` as top-level constants. Not currently configurable per team — adopting the label convention is how teams opt in, consistent with existing docs.

## Dashboard

### Tech

- Vanilla HTML + JS + CSS. No build step. No framework.
- `Chart.js@4` from a CDN with SRI hash (for the four weekly charts).
- Dark-mode-friendly via `prefers-color-scheme`.

### Loading priority

First non-empty source wins:

1. `?url=<URL>` query param — primary flow for team-specific dashboards.
2. File picker (`<input type="file">`) — one-off local exploration.
3. `localStorage["dora:lastUrl"]` — remember the last URL loaded.
4. `dashboard/fixtures/sample.json` — default demo view on a cold visit, labelled as demo data so no one thinks it's real.

URL fetches happen client-side. Hosts must serve with CORS open:
- `raw.githubusercontent.com` → works out of the box.
- S3 → requires `AllowedOrigin: ["*"]` in bucket CORS config. Documented in README.

### Layout

```
┌────────────────────────────────────────────────────┐
│ DORA metrics   [URL input_____________] [Load]     │
│                [Choose file] or drop a .json here  │
│ Source: <url> (loaded 2m ago) · Repo: [dropdown ▼] │
├────────────────────────────────────────────────────┤
│ Summary tiles (from `summary` metric):             │
│   PRs       PRs/week   Median lead   CFR           │
│    342        28.5       18.3h       2.1%          │
├────────────────────────────────────────────────────┤
│ Weekly charts:                                     │
│  ┌──────────────┐  ┌──────────────┐                │
│  │ Deploy freq  │  │ Deploy freq  │                │
│  │ (PRs)        │  │ (deployments)│                │
│  └──────────────┘  └──────────────┘                │
│  ┌──────────────┐  ┌──────────────┐                │
│  │ Lead time    │  │ Change-      │                │
│  │ mean/med/p90 │  │ failure rate │                │
│  └──────────────┘  └──────────────┘                │
├────────────────────────────────────────────────────┤
│ Detail (collapsed by default):                     │
│  ▸ Weekly metrics (raw, sortable)                  │
│  ▸ Hotfixes investigation                          │
└────────────────────────────────────────────────────┘
```

### Behavior

- **Multi-repo:** if the loaded JSON contains more than one `repo` value across rows, show a repo dropdown. Single-repo reports skip the dropdown.
- **Unknown metrics:** any metric name without a registered renderer falls back to a raw `<table>`. Keeps the dashboard forward-compatible with future CLI metrics.
- **Sortable tables:** lightweight sort-on-header helper (~20 lines), no library.

### File size targets

- `index.html` — ~80 lines of semantic markup, no inline JS.
- `app.js` — ~400 lines total (URL loader, renderers, repo filter, table sort).
- `style.css` — ~150 lines, CSS variables for theming.
- `fixtures/sample.json` — current `dora.json`, repo names anonymized to `acme/example`.

### Local preview

```
cd dashboard
python -m http.server 8000
# open http://localhost:8000/?url=fixtures/sample.json
```

## CI workflows

### This repo (`.github/workflows/`)

- **`pages.yml`** — on push to `main` touching `dashboard/**` or the workflow itself, builds and deploys via `actions/deploy-pages@v4` (uploads `dashboard/` directory as-is; no build step).
- **`test.yml`** — on PR and push: `uv sync --extra dev && uv run pytest`. Matrix on Python 3.11, 3.12, 3.13.
- **`release.yml`** — stub for later; not required for `uv tool install git+...`.

### Template for adopting teams (`examples/workflows/dora-report.yml`)

Teams copy this into their own repo at `.github/workflows/dora-report.yml`, edit the `--since` date, and commit. The DB is the source of truth — `report.json` is regenerated from it on every run.

**DB persistence pattern:** `dora.db` is preserved between runs via `actions/cache`. Hot cache → `dora pull` only fetches new/changed PRs and refreshes transient deployment statuses (fast). Cold cache (first run, or 7+ days inactivity) → empty DB, full re-pull from `--since` (slow but correct). To bust the cache deliberately, bump the `v1` prefix in the cache key.

```yaml
name: DORA metrics
on:
  schedule: [{cron: "0 6 * * 1"}]   # Monday 06:00 UTC
  workflow_dispatch:
jobs:
  report:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - uses: actions/cache@v4
        with:
          path: dora.db
          key: dora-db-v1-${{ github.run_id }}
          restore-keys: dora-db-v1-
      - run: uv tool install git+https://github.com/<owner>/dora
      - env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          dora pull --repo ${{ github.repository }} --since 2025-10-01
          dora report --format json --output dora-report.json
      - run: |
          git config user.name  "dora-bot"
          git config user.email "dora-bot@users.noreply.github.com"
          git add dora-report.json
          git diff --staged --quiet || git commit -m "Update DORA report"
          git push
```

Team's dashboard URL:

```
https://<owner>.github.io/dora/?url=https://raw.githubusercontent.com/<team-repo>/main/dora-report.json
```

### S3 variant (also documented)

For teams that prefer guaranteed persistence (beyond the 7-day cache eviction window) or don't want JSON history in git, both `dora.db` and `dora-report.json` round-trip through S3. The DB stays private; only the JSON is `--public-read` so the dashboard can fetch it. README includes the bucket CORS config snippet teams need (`AllowedOrigin: ["*"]`, `AllowedMethods: ["GET"]`).

### Documented gotchas

- `GITHUB_TOKEN` scope: the default is single-repo. Cross-repo aggregation (one team, multiple repos) requires a PAT or GitHub App installation token. Called out in README so teams don't discover it mid-setup.
- `--since` date is explicit (not a relative date), matching current behavior and keeping "what window am I looking at" obvious. With the persistent-DB pattern, `--since` only matters on cold-cache restoration.

## Testing

Matches moderate ("option B") scope: CLI smoke + metric correctness + HTTP layer.

- **`tests/conftest.py`** — `fixture_db` builds an in-memory SQLite, loads `tests/fixtures/seed.sql` with known PRs + deployments spanning several weeks. Reused across metric tests.
- **`tests/test_metrics.py`** — one test per metric. Example: "given 3 merged PRs in W42 with 1 labelled `caused-incident`, CFR for W42 is 33.3%." Seeded inputs → asserted exact output rows.
- **`tests/test_github.py`** — `requests-mock` simulates paginated responses, 403 rate-limit with `X-RateLimit-Reset`, deployment-status fetches. Verifies caching logic (already-known PRs skip `/commits`, terminal deployments skip `/statuses`).
- **`tests/test_cli.py`** — `subprocess.run([sys.executable, "-m", "dora", "report", ...])` per subcommand. Asserts exit 0, parseable output, basic flag parsing.

No dashboard browser tests. README documents the local preview recipe (above) for manual verification.

## Naming & license

- **Repo:** `dora` under the chosen org (presumed `dimagi/dora` — confirm).
- **PyPI package name:** `dora-metrics` (if/when published). `dora` is taken.
- **CLI binary:** `dora`.
- **License:** BSD-3-Clause (to match Dimagi conventions like CommCare HQ). Switchable to MIT or Apache-2.0 on request.

## Migration from current state

Current directory `/home/skelly/src/dora/` contains:
- `dora_pull.py`, `dora_report.py`, `dora_push_sheets.py` — get ported into `src/dora/` and then deleted.
- `dora.json` — becomes `dashboard/fixtures/sample.json` with repo names anonymized to `acme/example`.
- `dora.db` — not committed; added to `.gitignore`.
- `README.md` — rewritten for the new structure and generalized audience.

Porting is a faithful move, not a rewrite. All existing behavior (caching logic, rate-limit handling, progress ticker, CSV comment lines, JSON schema) is preserved. Metric SQL is unchanged.

## Future work (out of scope for first cut)

1. **Date-range filter in the dashboard** — from/to picker that narrows charts and tables client-side. Useful once reports accumulate more weeks.
2. **`change-failure-rate-deploys`** — CFR derived from `failure`/`error` deployment statuses, as an objective counterpart to the label-based CFR.
3. **Multi-report manifest** — dashboard loads a `manifest.json` listing all teams' reports with a switcher. Layer on top of the current single-report design.
4. **MTTR pipeline** — needs an incident log schema the current collector can't produce.
5. **PyPI release** — once the API stabilizes.

### Considered and deferred

- **`dora merge`** — was on the original roadmap as a way to combine a bootstrapped historical `report.json` with weekly increments. After working through the use case, we decided the persistent-DB workflow (above) makes merge unnecessary for the primary single-team use case: the DB is the source of truth, the JSON is just a derived view, and `dora pull` already handles incremental updates via its caching layer. A merge command might still make sense later for cross-team/cross-repo aggregation (combining two independent teams' reports into a meta-dashboard), but that's a different design than weekly-increment merge and we'll revisit when the need shows up.
