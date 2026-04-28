# Ingest GitHub Releases as deployment signals

**Date:** 2026-04-28
**Status:** Approved for planning

## Problem

Some repos don't use GitHub Deployments — they cut a GitHub Release for each
production deploy instead. Today `dora pull` only fetches from `/repos/.../deployments`,
so those repos get `deploy-freq` charts that show zero deploys regardless of activity.

We need to support these repos as a first-class source without forking the
schema, the metrics, or the dashboard.

## Goals

- A repo using GitHub Releases gets correct `deploy-freq` numbers.
- No change to the schema, the metric queries, or `report.json` shape.
- No change to the dashboard.
- The existing deployments code path is untouched (no regressions).
- No write access required to the source repo (read-only token sufficient).

## Non-goals

- Mixing both sources within a single `dora pull` invocation. To pull both, run
  `dora pull` twice into the same DB, once per source.
- Retroactively creating GitHub Deployment objects in the source repo.
- Tag-pattern filtering (e.g. only `prod-*` tags). Can be added later if asked.
- Multi-environment release lines. Releases always map to `environment="production"`.
- Including draft or pre-release releases.

## Design

### CLI

Add one argument to `dora pull`:

```
--source {deployments,releases}   default: deployments
```

When `--source=releases`:
- The existing `--environment` flag is ignored. If the user passed it explicitly
  (i.e. it's not the default `"production"`), log a warning to stderr and proceed.
- All other `pull` flags work as before (`--repo`, `--since`, `--db`, `--skip-prs`,
  `--skip-deployments`, `--base`).

### Fetcher

New function in `src/dora/github.py`, located next to `fetch_deployments`:

```python
def fetch_releases(
    session: requests.Session,
    repo: str,
    since: datetime,
    known_releases: set[int],
) -> Generator[dict, None, None]:
    """Yield published GitHub releases on/after `since` as deployment-shaped dicts.

    Skips drafts, pre-releases, and releases already in `known_releases`.
    Releases are immutable post-publish, so cached IDs are skipped entirely
    (no status to refresh).
    """
    for r in gh(session, f"/repos/{repo}/releases", {"per_page": 100}):
        if r["draft"] or r["prerelease"]:
            continue
        if r["published_at"] is None:
            continue  # belt-and-suspenders for drafts that slip through
        if iso_to_dt(r["published_at"]) < since:
            return  # /releases endpoint returns newest-first
        if r["id"] in known_releases:
            continue
        yield {
            "deployment_id": r["id"],
            "sha":           r["target_commitish"],
            "environment":   "production",
            "created_at":    r["published_at"],
            "status":        "success",
        }
```

Three deliberate decisions:

- **Drafts and pre-releases are skipped.** Drafts aren't published events.
  Pre-releases are explicitly "not production yet." Adding `--include-prereleases`
  is deferred until a real use case appears.
- **`sha` = `target_commitish` as-is.** This may be a branch name (`"main"`) or
  a real SHA, depending on how the release was created. The `sha` column is
  stored but never read by any metric query — it exists for forensics only.
  Resolving the tag → real SHA via an extra API call is wasted work.
- **`status` = `"success"`.** Releases have no failure semantics. `"success"`
  puts them in `SUCCESS_DEPLOY_STATUSES = ("success", "inactive")`, so
  `m_deploy_freq` counts them.

### Orchestration

`run_pull` in `src/dora/pull.py` gains a `source: str` keyword argument
(defaulting to `"deployments"`). The deployments branch refactors to:

```python
if not skip_deployments:
    if source == "releases":
        known = {row[0] for row in conn.execute(
            "SELECT deployment_id FROM deployments "
            "WHERE repo = ? AND environment = 'production'",
            (repo,),
        )}
        label = "releases"
        fetcher = github.fetch_releases(session, repo, since_dt, known)
        cache_msg = f"  fetching releases… ({len(known)} cached, skipped)"
    else:
        # existing deployments code, factored to produce `known`, `label`,
        # `fetcher`, `cache_msg` the same way
        ...

    print(cache_msg, file=sys.stderr)
    tick, done = _make_progress(label)
    n_cached = 0
    for d in fetcher:
        db.upsert_deployment(conn, repo, d)
        if d["deployment_id"] in known:
            n_cached += 1
        tick()
    done()
    if n_cached:
        print(f"    ({n_cached} reused from cache)", file=sys.stderr)
    conn.commit()
```

The shared progress + upsert loop is extracted from the if/else to avoid
duplication.

### Schema

Unchanged. Releases write into the existing `deployments` table:

| Column          | Value for releases                                 |
| --------------- | -------------------------------------------------- |
| `repo`          | `owner/name`                                       |
| `deployment_id` | GitHub release ID                                  |
| `sha`           | release `target_commitish` (branch name or SHA)    |
| `environment`   | `"production"` (hardcoded)                         |
| `created_at`    | release `published_at`                             |
| `status`        | `"success"`                                        |

Primary key `(repo, deployment_id)` holds: GitHub release IDs are unique per
repo and don't collide with deployment IDs (different ID spaces, and a single
repo only uses one source).

### Metrics, dashboard, report.json

Unchanged.

- `m_deploy_freq` already accepts `"success"` via `SUCCESS_DEPLOY_STATUSES`.
- `m_change_failure_rate` is PR-label-driven (`caused-incident`), so it doesn't
  depend on deployment status. Releases-as-deployments is fully neutral here.
- Dashboard renders `report.json` rows; no source-of-deployments column exists.

## Testing

New tests in `tests/`:

- `test_fetch_releases_basic` — mock `/releases` response with three releases
  (one draft, one prerelease, one normal); assert only the normal one is yielded
  with the expected dict shape (`deployment_id`, `sha`, `environment`,
  `created_at`, `status`).
- `test_fetch_releases_since_cutoff` — releases newest-first; assert iteration
  stops at the first one older than `since`.
- `test_fetch_releases_cache_skip` — pre-populate `known_releases`; assert
  cached IDs are not yielded.
- `test_pull_releases_writes_deployments` — end-to-end with a mocked session:
  run `dora pull --source releases`, assert `deployments` table is populated
  with `environment='production'` and `status='success'`, and `m_deploy_freq`
  returns the expected weekly counts.

Existing deployments-path tests are untouched.

## Documentation

`README.md` gets one new subsection under **Adoption**:

> **Repos that don't use GitHub Deployments**
> If your repo creates a GitHub Release on each deploy instead, run
> `dora pull --source releases`. Releases map to `environment='production'`
> deployment rows; everything else (charts, change-failure rate, dashboard)
> works identically. Drafts and pre-releases are ignored.

`examples/workflows/dora-report.yml` gets a comment near the `dora pull`
invocation:

```yaml
# If your repo deploys via GitHub Releases instead of Deployments, add:
#   --source releases
```

## Files touched

- `src/dora/cli.py` — add `--source` arg to `_add_pull`, thread through `_cmd_pull`
- `src/dora/github.py` — new `fetch_releases` function
- `src/dora/pull.py` — accept `source` kwarg, branch on it inside the
  `skip_deployments` block, factor shared loop
- `tests/` — four new tests as above
- `README.md` — one subsection
- `examples/workflows/dora-report.yml` — one comment

No schema migration. No dashboard change. No `report.json` shape change.
