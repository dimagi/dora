# Dora — DORA metrics from GitHub

[![Tests](https://github.com/dimagi/dora/actions/workflows/test.yml/badge.svg)](https://github.com/dimagi/dora/actions/workflows/test.yml)

**▶ [View the dashboard](https://dimagi.github.io/dora/)** — point it at any `report.json` via `?url=…` or upload directly.

A Python CLI that pulls the four DORA metrics — deployment frequency, lead time for changes, change failure rate, and a hotfix investigation helper — from the GitHub API, and a static dashboard (GitHub Pages) that renders the resulting `report.json`.

Designed for team adoption: you run the CLI on your own repo (locally or from CI), produce a `report.json`, and share a link to the central dashboard pointing at your data.

## Quick start

### Install the CLI

```bash
uv tool install git+https://github.com/dimagi/dora
# or with the S3 extra:
uv tool install "git+https://github.com/dimagi/dora[s3]"
```

### Generate a report

```bash
# First pull (slow: one API call per PR for commit history)
dora pull --repo owner/name --since 2025-10-01

# Report to stdout
dora report

# Or as JSON:
dora report --format json --output dora-report.json
```

### View on the dashboard

```
https://dimagi.github.io/dora/?url=https://<your-json-location>/dora-report.json
```

Or open `https://dimagi.github.io/dora/` and upload the file directly.

## Subcommands

- `dora pull` — fetch merged PRs + deployments from GitHub into a SQLite cache
- `dora report` — run metric queries, emit table / CSV / JSON
- `dora upload` — upload a file to an `s3://bucket/key` target (install with `[s3]` extra)

Run `dora <subcommand> --help` for flags.

## Adoption (for teams running this in CI)

Copy [`examples/workflows/dora-report.yml`](examples/workflows/dora-report.yml) to your repo's `.github/workflows/` directory. Edit the `--since` date once. The workflow:

1. Runs weekly (cron) or on demand
2. Restores `dora.db` from the Actions cache (or starts fresh on first run)
3. Pulls new PRs/deployments since the last run
4. Writes `dora-report.json` from the DB
5. Saves the updated `dora.db` back to the cache
6. Commits the JSON back to your repo

Your dashboard link becomes:

```
https://dimagi.github.io/dora/?url=https://raw.githubusercontent.com/<your-repo>/main/dora-report.json
```

### How the DB cache works

`dora.db` is the source of truth — `dora-report.json` is derived from it on every run. The DB is persisted between CI runs via [`actions/cache`](https://github.com/actions/cache):

- **Hot cache (typical)**: `dora pull` only fetches PRs/deployments updated since the previous run, plus refreshes labels and transient deployment statuses. Fast.
- **Cold cache (first run, or after 7+ days of inactivity)**: GitHub evicts the cache, the next run starts with an empty DB and re-pulls everything since `--since`. Slow but correct — typically a few minutes for a year of history. Each new PR costs 3 API calls (commits + pull detail + timeline) for the size + ready-for-review fields; subsequent pulls only re-fetch labels and transient deployment statuses.

To bust the cache deliberately (e.g. if a future schema change requires it), bump the `v1` prefix in the workflow's cache `key`.

### Repos that don't use GitHub Deployments

If your repo creates a GitHub Release on each deploy instead of a GitHub
Deployment, run `dora pull` with `--source releases`:

```bash
dora pull --repo owner/name --since 2025-10-01 --source releases
```

Releases map to `environment='production'` rows in the `deployments`
table. Charts, change-failure rate, and the dashboard work identically.
Drafts and pre-releases are ignored.

### Cross-repo reports

The default `GITHUB_TOKEN` in Actions is scoped to the workflow's own repo. To aggregate multiple repos (`--repo a/b --repo c/d`), generate a PAT or install a GitHub App with access to each repo and pass its token via `GITHUB_TOKEN` in the env.

### S3 variant

A commented S3 variant in the example workflow stores both `dora.db` and `dora-report.json` in S3 instead of using the cache + git-commit pattern. Useful if you'd rather not have JSON history in your git log, or if you want guaranteed persistence beyond the 7-day cache eviction window.

**Recommended auth: GitHub OIDC.** Short-lived credentials assumed at workflow runtime; no long-lived AWS keys to rotate, no secrets stored in the repo. Run [`examples/setup-aws.sh`](examples/setup-aws.sh) to provision the bucket, OIDC provider, and IAM role in one command:

    ./examples/setup-aws.sh \
      --repo OWNER/REPO --bucket BUCKET --region REGION [--branch main]

The script prints the role ARN and bucket details to paste into your workflow. See `examples/setup-aws.sh --help` for full options, or the workflow file's S3-variant section for the underlying resources if you'd rather provision by hand.

**Fallback: long-lived access keys.** If you don't have AWS-side access to set up OIDC, store `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` as repo secrets and pass them via env vars on the relevant steps.

Either way, you'll also need:

- Bucket CORS config allowing `GET` from `*` (so the dashboard can fetch the JSON)
- The DB is stored privately; only the JSON is publicly readable (via a bucket policy scoped to `dora-report.json`)

## Metric definitions

| Metric | Counts | Notes |
|---|---|---|
| `deploy-freq-prs` | Merged PRs into `main` per week | Overstates if PRs are batched into single deploys |
| `deploy-freq` | Successful deployments per week | Counts both `success` and `inactive` GitHub statuses |
| `lead-time` | Hours from first commit to merge | Mean / median / p90 per week |
| `change-failure-rate` | % of merged PRs labelled `caused-incident` | Requires label discipline |
| `review-latency` | Median hours waiting for review (`merged − ready_for_review_at \| opened_at`), bucketed by `changed_files` (XS=1, S=2-3, M=4-9, L+=10+) | Chart shows median; JSON output also includes p90 |
| `hotfixes` | Recent `hotfix`-labelled PRs + their 3 preceding merges | Investigative — helps find causing PRs to backfill `caused-incident` |
| `large-prs` | Weekly count of merged PRs with `changed_files >= 10` | Same NULL coverage caveat as `review-latency` (legacy rows excluded) |
| `hotfix-count` | Weekly count of `hotfix`-labelled PRs | Aggregate of the same set `hotfixes` lists individually |
| `weekend-merges` | Individual PRs merged on Sat/Sun (UTC) | Per-PR drill-down with author + day-of-week |
| `summary` | Per-repo roll-up over the window | Used by the dashboard's summary tiles |

> **`review-latency` coverage ramps forward.** When you upgrade `dora` and run the next `dora pull`, only newly-merged PRs get their size + draft data fetched. Previously-cached PRs keep their `changed_files` and `ready_for_review_at` columns `NULL` and are excluded from the metric. Coverage fills in over time as new PRs merge. A `--rebuild` flag for forced backfill is parked as future work.

## Label conventions

- **`caused-incident`** — applied to the PR that SHIPPED a production defect. This is what `change-failure-rate` counts.
- **`hotfix`** — applied to the PR that FIXED a prior defect. Not counted in CFR (avoids double-counting one incident as two). Surfaced by `hotfixes`.

Do not apply both to the same PR.

## Bot filter

Bot-authored PRs (login matches `*[bot]` — dependabot, renovate, github-actions, etc.) are filtered per metric by default. The defaults aim to keep bots in metrics where they represent real shipped work and exclude them where their volume or speed distorts the human signal.

| Metric | Bots | Why |
|---|---|---|
| `deploy-freq-prs` | counted | bot PRs ship real changes |
| `deploy-freq` | n/a | reads the deployments table — no `author` column |
| `lead-time` | excluded | bot merges happen in seconds; distort distribution |
| `change-failure-rate` | counted | a bot-shipped defect is still a defect |
| `change-failure-prs` | counted | drill-down for CFR; matches |
| `hotfixes` | counted | bots can ship hotfixes; list them if they do |
| `hotfix-count` | counted | aggregate of `hotfixes`; matches |
| `summary` | mixed | composite — each component uses its own default |
| `review-latency` | excluded | auto-merged; not a human review wait |
| `large-prs` | excluded | dependabot weekly mega-bumps dominate the L+ bucket |
| `weekend-merges` | excluded | bot cron schedules aren't human patterns |

Override the defaults globally:
```bash
dora report --exclude-bots   # filter bots from every metric
dora report --include-bots   # keep bots in every metric (even where excluded by default)
```

The dashboard shows a `humans only` chip on each tile or panel whose data excludes bots, plus a banner at the top when a global override (either flag) is active.

## Deployment status quirks

GitHub auto-marks a successful deployment as `inactive` when a newer deployment for the same environment succeeds — so most historically-successful deploys show up as `inactive`, not `success`. The report treats both as successful.

Stuck `pending` rows usually indicate a workflow-level timeout (e.g. `aws ecs wait services-stable` killed by a CI job timeout). Fix by emitting a terminal deployment status in an `if: always()` step.

## Development

```bash
git clone https://github.com/dimagi/dora
cd dora
uv sync --extra dev --extra s3
uv run pytest
```

Preview the dashboard locally:

```bash
cd dashboard
python -m http.server 8000
# open http://localhost:8000/?url=fixtures/sample.json
```

## Data model

```
pull_requests (repo, number) PK
  title, author, base, labels (comma-joined)
  opened_at, merged_at, first_commit_at
  merge_sha
  additions, deletions, changed_files       -- powers `review-latency`
  ready_for_review_at                       -- NULL when never drafted

deployments (repo, deployment_id) PK
  sha, environment, created_at, status
```

The DB is a rebuildable cache — not a source of truth. Drop it and re-pull at any time.

## License

BSD-3-Clause. See [LICENSE](LICENSE).
