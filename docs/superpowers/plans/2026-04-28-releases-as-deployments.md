# GitHub Releases as deployment signals — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--source releases` mode to `dora pull` so repos that cut a GitHub Release on each deploy (instead of using GitHub Deployments) produce correct DORA metrics.

**Architecture:** Releases map 1:1 onto the existing `deployments` table — a new `fetch_releases` function in `github.py` produces dicts with the same shape as `fetch_deployments`, and `pull.run_pull` dispatches on a new `source` parameter. No schema, metric, or dashboard changes.

**Tech Stack:** Python 3.12+, pytest, requests, requests-mock, sqlite3, argparse

**Spec:** `docs/superpowers/specs/2026-04-28-releases-as-deployments-design.md`

---

## File touchpoints

| File | Why |
| --- | --- |
| `src/dora/github.py` | Add `fetch_releases` next to `fetch_deployments` |
| `tests/test_github.py` | Three new tests for `fetch_releases` |
| `src/dora/cli.py` | Add `--source` arg to `pull`; thread through to `run_pull`; warn if `--environment` is non-default with `--source=releases` |
| `tests/test_cli.py` | Three new tests for CLI source dispatch |
| `src/dora/pull.py` | Accept `source` kwarg; branch on it inside `skip_deployments` block; factor shared progress/upsert loop |
| `tests/test_pull.py` | NEW file — one test asserting `run_pull(..., source="releases")` calls `fetch_releases` (not `fetch_deployments`) and writes correct rows |
| `README.md` | One subsection under **Adoption** |
| `examples/workflows/dora-report.yml` | One comment near the `dora pull` line |

---

## Task 1: Add `fetch_releases` to `src/dora/github.py`

**Files:**
- Modify: `src/dora/github.py` — append new function after `fetch_deployments` (currently ends ~line 205)
- Modify: `tests/test_github.py` — append three tests after the existing `fetch_deployments` tests (~line 281)

- [ ] **Step 1: Write three failing tests in `tests/test_github.py`**

Append at the end of the file:

```python
# --- fetch_releases ------------------------------------------------------

def test_fetch_releases_skips_draft_and_prerelease(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/releases",
        json=[
            {
                "id": 300, "tag_name": "v3", "target_commitish": "main",
                "published_at": "2025-10-12T00:00:00Z",
                "draft": False, "prerelease": True,
            },
            {
                "id": 200, "tag_name": "v2", "target_commitish": "main",
                "published_at": "2025-10-11T00:00:00Z",
                "draft": True, "prerelease": False,
            },
            {
                "id": 100, "tag_name": "v1", "target_commitish": "main",
                "published_at": "2025-10-10T00:00:00Z",
                "draft": False, "prerelease": False,
            },
        ],
    )
    session = requests.Session()
    since = github.iso_to_dt("2025-10-01T00:00:00+00:00")
    out = list(github.fetch_releases(session, "x/y", since, known_releases=set()))
    assert len(out) == 1
    assert out[0] == {
        "deployment_id": 100,
        "sha":           "main",
        "environment":   "production",
        "created_at":    "2025-10-10T00:00:00Z",
        "status":        "success",
    }


def test_fetch_releases_stops_at_since_cutoff(requests_mock):
    base = "https://api.github.com"
    # Releases endpoint is newest-first; the iterator must stop on the
    # first entry older than `since` (no need to walk all history).
    requests_mock.get(
        f"{base}/repos/x/y/releases",
        json=[
            {
                "id": 200, "tag_name": "v2", "target_commitish": "main",
                "published_at": "2025-10-15T00:00:00Z",
                "draft": False, "prerelease": False,
            },
            {
                "id": 100, "tag_name": "v1", "target_commitish": "main",
                "published_at": "2025-09-15T00:00:00Z",  # older than since
                "draft": False, "prerelease": False,
            },
        ],
    )
    session = requests.Session()
    since = github.iso_to_dt("2025-10-01T00:00:00+00:00")
    out = list(github.fetch_releases(session, "x/y", since, known_releases=set()))
    assert [r["deployment_id"] for r in out] == [200]


def test_fetch_releases_skips_cached(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/releases",
        json=[
            {
                "id": 200, "tag_name": "v2", "target_commitish": "main",
                "published_at": "2025-10-12T00:00:00Z",
                "draft": False, "prerelease": False,
            },
            {
                "id": 100, "tag_name": "v1", "target_commitish": "main",
                "published_at": "2025-10-10T00:00:00Z",
                "draft": False, "prerelease": False,
            },
        ],
    )
    session = requests.Session()
    since = github.iso_to_dt("2025-10-01T00:00:00+00:00")
    out = list(github.fetch_releases(session, "x/y", since, known_releases={100}))
    assert [r["deployment_id"] for r in out] == [200]
```

- [ ] **Step 2: Run the new tests and verify they all fail**

Run: `pytest tests/test_github.py -v -k fetch_releases`

Expected: 3 failures with `AttributeError: module 'dora.github' has no attribute 'fetch_releases'`

- [ ] **Step 3: Implement `fetch_releases` in `src/dora/github.py`**

Append after the existing `fetch_deployments` function (currently the last function in the file):

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
    (no status to refresh, unlike fetch_deployments).
    """
    for r in gh(session, f"/repos/{repo}/releases", {"per_page": 100}):
        if r["draft"] or r["prerelease"]:
            continue
        if r["published_at"] is None:
            continue
        if iso_to_dt(r["published_at"]) < since:
            return  # /releases is newest-first
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

- [ ] **Step 4: Run the new tests and verify they pass**

Run: `pytest tests/test_github.py -v -k fetch_releases`

Expected: 3 passed

- [ ] **Step 5: Run the full github test module to confirm no regressions**

Run: `pytest tests/test_github.py -v`

Expected: all tests pass (existing + 3 new)

- [ ] **Step 6: Commit**

```bash
git add src/dora/github.py tests/test_github.py
git commit -m "feat(github): add fetch_releases as a deployment signal source

Yields published GitHub releases as deployment-shaped dicts so they can
be ingested into the existing deployments table. Skips drafts and
pre-releases; respects known_releases for cache hot-path."
```

---

## Task 2: Wire `--source` flag through `src/dora/cli.py`

**Files:**
- Modify: `src/dora/cli.py:20-28` (`_add_pull`) and `src/dora/cli.py:57-67` (`_cmd_pull`)
- Modify: `tests/test_cli.py` — append new tests at the end

- [ ] **Step 1: Write three failing tests in `tests/test_cli.py`**

Append at the end of the file:

```python
# --- pull --source dispatch ----------------------------------------------

def test_cli_pull_default_source_is_deployments(monkeypatch):
    """Default --source is 'deployments' (preserves pre-existing behavior)."""
    captured = {}

    def fake_run_pull(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli.pull_mod, "run_pull", fake_run_pull)
    rc = cli.main(["pull", "--repo", "x/y", "--since", "2025-01-01"])
    assert rc == 0
    assert captured["source"] == "deployments"


def test_cli_pull_source_releases(monkeypatch):
    captured = {}

    def fake_run_pull(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli.pull_mod, "run_pull", fake_run_pull)
    rc = cli.main([
        "pull", "--repo", "x/y", "--since", "2025-01-01",
        "--source", "releases",
    ])
    assert rc == 0
    assert captured["source"] == "releases"


def test_cli_pull_warns_when_environment_set_with_releases(monkeypatch, capsys):
    """`--source releases` ignores --environment; warn if user set it explicitly."""
    monkeypatch.setattr(cli.pull_mod, "run_pull", lambda **kw: None)
    rc = cli.main([
        "pull", "--repo", "x/y", "--since", "2025-01-01",
        "--source", "releases",
        "--environment", "staging",
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "ignored" in err.lower() and "releases" in err.lower()


def test_cli_pull_invalid_source_rejected():
    """argparse should reject --source values outside the choice set."""
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "pull", "--repo", "x/y", "--since", "2025-01-01",
            "--source", "rainbows",
        ])
    assert exc.value.code == 2
```

Note: `cli` is already imported at the top of `tests/test_cli.py`. `pytest` is imported. No new imports needed.

- [ ] **Step 2: Run the new tests and verify they fail**

Run: `pytest tests/test_cli.py -v -k "pull"`

Expected:
- `test_cli_pull_default_source_is_deployments` fails with `KeyError: 'source'` (the fake `run_pull` captures kwargs; the real call doesn't pass `source` yet).
- `test_cli_pull_source_releases` and `test_cli_pull_warns_when_environment_set_with_releases` fail with `SystemExit: 2` (argparse rejects the unknown `--source` arg).
- `test_cli_pull_invalid_source_rejected` passes by coincidence (argparse rejects `--source` regardless of value). Re-verify it still passes after step 3 — when `--source` is recognized, argparse should still exit 2 for `rainbows` because of the `choices=` constraint.

- [ ] **Step 3: Modify `_add_pull` in `src/dora/cli.py`**

Find the function (currently lines 20-28):

```python
def _add_pull(sub):
    p = sub.add_parser("pull", help="Fetch DORA signals from GitHub into SQLite.")
    p.add_argument("--repo", required=True, action="append", help="owner/name (repeatable)")
    p.add_argument("--since", required=True, help="ISO date, e.g. 2025-10-01")
    p.add_argument("--db", default="dora.db")
    p.add_argument("--base", default="main")
    p.add_argument("--environment", default="production")
    p.add_argument("--skip-prs", action="store_true")
    p.add_argument("--skip-deployments", action="store_true")
```

Add a new `--source` line after `--environment`:

```python
def _add_pull(sub):
    p = sub.add_parser("pull", help="Fetch DORA signals from GitHub into SQLite.")
    p.add_argument("--repo", required=True, action="append", help="owner/name (repeatable)")
    p.add_argument("--since", required=True, help="ISO date, e.g. 2025-10-01")
    p.add_argument("--db", default="dora.db")
    p.add_argument("--base", default="main")
    p.add_argument("--environment", default="production")
    p.add_argument("--source", choices=("deployments", "releases"),
                   default="deployments",
                   help="Deploy-signal source: GitHub Deployments (default) "
                        "or GitHub Releases. With 'releases', --environment is ignored "
                        "(releases always map to environment='production').")
    p.add_argument("--skip-prs", action="store_true")
    p.add_argument("--skip-deployments", action="store_true")
```

- [ ] **Step 4: Modify `_cmd_pull` in `src/dora/cli.py`**

Find the function (currently lines 57-67) and replace it with:

```python
def _cmd_pull(args: argparse.Namespace) -> int:
    if args.source == "releases" and args.environment != "production":
        print(
            f"warning: --environment={args.environment!r} is ignored with "
            f"--source=releases (releases always map to environment='production')",
            file=sys.stderr,
        )
    pull_mod.run_pull(
        repos=args.repo,
        since=args.since,
        db_path=args.db,
        base=args.base,
        environment=args.environment,
        source=args.source,
        skip_prs=args.skip_prs,
        skip_deployments=args.skip_deployments,
    )
    return 0
```

`sys` is already imported at the top of `cli.py` — no new import needed.

- [ ] **Step 5: Run the new tests and verify they pass**

Run: `pytest tests/test_cli.py -v -k "pull"`

Expected: 4 passed

Note: `run_pull` doesn't yet accept `source` — this works because the tests in step 1 patch `pull_mod.run_pull` to a fake that ignores its kwargs. Task 3 fixes the real signature.

- [ ] **Step 6: Run the full CLI test module**

Run: `pytest tests/test_cli.py -v`

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add src/dora/cli.py tests/test_cli.py
git commit -m "feat(cli): add --source {deployments,releases} to dora pull

Defaults to 'deployments' (no behavior change). With --source=releases,
warns if --environment was set explicitly since releases always map to
environment='production'."
```

---

## Task 3: Dispatch on `source` in `src/dora/pull.py`

**Files:**
- Modify: `src/dora/pull.py:36-114` (whole `run_pull` function)
- Create: `tests/test_pull.py`

- [ ] **Step 1: Create the new test file `tests/test_pull.py`**

```python
"""Tests for src/dora/pull.py — orchestration + source dispatch."""

import sqlite3
from unittest.mock import patch

from dora import db, pull


def _release_dict(rid: int, published_at: str) -> dict:
    return {
        "deployment_id": rid,
        "sha":           "main",
        "environment":   "production",
        "created_at":    published_at,
        "status":        "success",
    }


def test_run_pull_releases_writes_rows_via_fetch_releases(tmp_path, monkeypatch):
    """source='releases' calls fetch_releases (not fetch_deployments) and
    persists the synthesized rows into the deployments table."""
    db_path = tmp_path / "dora.db"

    # Stub out token + session so no real network is touched.
    monkeypatch.setattr(pull.github, "get_token", lambda: "fake")
    monkeypatch.setattr(pull.github, "make_session", lambda token: object())

    fake_releases = [
        _release_dict(100, "2025-10-10T00:00:00Z"),
        _release_dict(200, "2025-10-12T00:00:00Z"),
    ]
    fetch_releases_mock = patch.object(
        pull.github, "fetch_releases", return_value=iter(fake_releases)
    )
    fetch_deployments_mock = patch.object(
        pull.github, "fetch_deployments",
        side_effect=AssertionError("must not be called for source=releases"),
    )

    with fetch_releases_mock, fetch_deployments_mock:
        pull.run_pull(
            repos=["x/y"],
            since="2025-10-01",
            db_path=str(db_path),
            base="main",
            environment="production",
            source="releases",
            skip_prs=True,
            skip_deployments=False,
        )

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT deployment_id, environment, status FROM deployments "
        "WHERE repo = ? ORDER BY deployment_id",
        ("x/y",),
    ).fetchall()
    conn.close()
    assert rows == [(100, "production", "success"), (200, "production", "success")]


def test_run_pull_deployments_default_calls_fetch_deployments(tmp_path, monkeypatch):
    """Default source preserves pre-existing behavior (calls fetch_deployments)."""
    db_path = tmp_path / "dora.db"
    monkeypatch.setattr(pull.github, "get_token", lambda: "fake")
    monkeypatch.setattr(pull.github, "make_session", lambda token: object())

    fake_deployments = [{
        "deployment_id": 7,
        "sha":           "abc",
        "environment":   "production",
        "created_at":    "2025-10-10T00:00:00Z",
        "status":        "success",
    }]
    fetch_deployments_mock = patch.object(
        pull.github, "fetch_deployments", return_value=iter(fake_deployments)
    )
    fetch_releases_mock = patch.object(
        pull.github, "fetch_releases",
        side_effect=AssertionError("must not be called for source=deployments"),
    )

    with fetch_deployments_mock, fetch_releases_mock:
        pull.run_pull(
            repos=["x/y"],
            since="2025-10-01",
            db_path=str(db_path),
            base="main",
            environment="production",
            source="deployments",
            skip_prs=True,
            skip_deployments=False,
        )

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT deployment_id FROM deployments WHERE repo = ?", ("x/y",),
    ).fetchall()
    conn.close()
    assert rows == [(7,)]
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run: `pytest tests/test_pull.py -v`

Expected: 2 failures with `TypeError: run_pull() got an unexpected keyword argument 'source'`

- [ ] **Step 3: Refactor `run_pull` in `src/dora/pull.py`**

Replace the whole `run_pull` function (currently lines 36-113) with:

```python
def run_pull(
    *,
    repos: list[str],
    since: str,
    db_path: str,
    base: str,
    environment: str,
    source: str,
    skip_prs: bool,
    skip_deployments: bool,
) -> None:
    """Pull signals for one or more repos into the SQLite DB.

    `source` selects the deploy-signal endpoint:
        "deployments" → /repos/.../deployments (default)
        "releases"    → /repos/.../releases (mapped to environment='production')
    """
    token = github.get_token()
    session = github.make_session(token)

    since_dt = github.iso_to_dt(
        since if "T" in since else since + "T00:00:00+00:00"
    )

    conn = db.init_db(db_path)
    try:
        for repo in repos:
            print(f"→ {repo}", file=sys.stderr)

            if not skip_prs:
                _pull_prs(conn, session, repo, since_dt, base)

            if not skip_deployments:
                _pull_deploy_signals(
                    conn, session, repo, since_dt, environment, source,
                )
    finally:
        conn.close()
```

Then add two new helper functions above `run_pull` (below `_make_progress`):

```python
def _pull_prs(conn, session, repo, since_dt, base):
    known_prs = {
        row[0] for row in conn.execute(
            "SELECT number FROM pull_requests "
            "WHERE repo = ? AND first_commit_at IS NOT NULL",
            (repo,),
        )
    }
    print(
        f"  fetching merged PRs into {base}… "
        f"({len(known_prs)} cached, commits call skipped)",
        file=sys.stderr,
    )
    tick, done = _make_progress(f"merged PRs into {base}")
    n_cached = 0
    for pr in github.fetch_prs(session, repo, since_dt, base, known_prs):
        db.upsert_pr(conn, repo, pr)
        if pr["number"] in known_prs:
            n_cached += 1
        tick()
    done()
    if n_cached:
        print(f"    ({n_cached} reused from cache)", file=sys.stderr)
    conn.commit()


def _pull_deploy_signals(conn, session, repo, since_dt, environment, source):
    """Fetch deploy signals for `repo` and upsert them into `deployments`.

    Two source paths share the same upsert + progress scaffolding; only the
    cache query, fetcher, and log labels differ.
    """
    if source == "releases":
        known = {
            row[0] for row in conn.execute(
                "SELECT deployment_id FROM deployments "
                "WHERE repo = ? AND environment = 'production'",
                (repo,),
            )
        }
        label = "releases"
        cache_msg = (
            f"  fetching releases… ({len(known)} cached, skipped)"
        )
        fetcher = github.fetch_releases(session, repo, since_dt, known)
    else:
        placeholders = ",".join("?" * len(TERMINAL_DEPLOY_STATUSES))
        known = {
            row[0] for row in conn.execute(
                f"SELECT deployment_id FROM deployments "
                f"WHERE repo = ? AND environment = ? "
                f"AND status IN ({placeholders})",
                (repo, environment, *TERMINAL_DEPLOY_STATUSES),
            )
        }
        label = f"deployments ({environment})"
        cache_msg = (
            f"  fetching deployments ({environment})… "
            f"({len(known)} cached, statuses call skipped)"
        )
        fetcher = github.fetch_deployments(
            session, repo, since_dt, environment, known
        )

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

The final `pull.py` should still have `import sys`, `from . import db, github`, and `TERMINAL_DEPLOY_STATUSES = frozenset(...)` at the top — keep them as-is.

- [ ] **Step 4: Run the new tests and verify they pass**

Run: `pytest tests/test_pull.py -v`

Expected: 2 passed

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `pytest -v`

Expected: all tests pass (existing + new from Tasks 1, 2, 3).

- [ ] **Step 6: Manual smoke check (optional but recommended)**

If you have a GitHub token set, run against a known repo that uses releases:

```bash
GITHUB_TOKEN=... dora pull \
  --repo dimagi/dora \
  --since 2025-01-01 \
  --source releases \
  --db /tmp/dora-smoke.db
sqlite3 /tmp/dora-smoke.db \
  "SELECT deployment_id, environment, status, created_at FROM deployments LIMIT 5;"
```

Expected: rows with `environment='production'` and `status='success'`. (`dimagi/dora` itself doesn't cut releases, so this is just a "no crash" check — substitute a repo you know cuts releases for a real check.)

- [ ] **Step 7: Commit**

```bash
git add src/dora/pull.py tests/test_pull.py
git commit -m "feat(pull): dispatch on source flag — deployments or releases

run_pull now accepts source={'deployments','releases'}. The shared
progress + upsert loop is factored into _pull_deploy_signals to keep
the two source paths DRY. Releases write into the existing deployments
table with environment='production' and status='success'."
```

---

## Task 4: Documentation

**Files:**
- Modify: `README.md` — append a subsection under **Adoption (for teams running this in CI)**
- Modify: `examples/workflows/dora-report.yml` — add a comment near the `dora pull` line

- [ ] **Step 1: Add subsection to `README.md`**

Open `README.md`. Find the **Adoption (for teams running this in CI)** section (~line 50) and the existing `### Cross-repo reports` subsection (~line 76). Insert this new subsection *before* `### Cross-repo reports` (so the order becomes: How the DB cache works → Repos that don't use GitHub Deployments → Cross-repo reports → S3 variant).

The exact bytes to insert (a four-backtick fence is used here only so the nested triple-backtick `bash` block displays correctly in the plan — copy only what's *between* the four-backtick lines):

````markdown
### Repos that don't use GitHub Deployments

If your repo creates a GitHub Release on each deploy instead of a GitHub
Deployment, run `dora pull` with `--source releases`:

```bash
dora pull --repo owner/name --since 2025-10-01 --source releases
```

Releases map to `environment='production'` rows in the `deployments`
table. Charts, change-failure rate, and the dashboard work identically.
Drafts and pre-releases are ignored.
````

The pasted README content is exactly: the `### Repos that don't use GitHub Deployments` heading, the two paragraphs, and the embedded triple-backtick `bash` block (which opens and closes within the subsection).

- [ ] **Step 2: Add comment to `examples/workflows/dora-report.yml`**

Find the `Pull & report` step (the line that runs `dora pull --repo ... --since ...`). Insert a comment line directly above the `dora pull` invocation:

```yaml
      - name: Pull & report
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          # If your repo deploys via GitHub Releases instead of Deployments, add:
          #   --source releases
          dora pull --repo ${{ github.repository }} --since 2025-10-01
          dora report --format json --output dora-report.json
```

- [ ] **Step 3: Sanity-check the README renders**

Open `README.md` in your editor and visually confirm the new subsection appears between the **How the DB cache works** subsection and **Cross-repo reports**, with no broken fences or stray backticks. Optionally render it (`grip`, `pandoc`, GitHub's preview, or your editor's preview) to be sure.

- [ ] **Step 4: Commit**

```bash
git add README.md examples/workflows/dora-report.yml
git commit -m "docs: document --source releases for repos using GitHub Releases"
```

---

## Final verification

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -v`

Expected: all tests pass. No skipped/error rows beyond what was already there.

- [ ] **Step 2: Run the CLI help to confirm the new flag is documented**

Run: `python -m dora pull --help`

Expected: `--source {deployments,releases}` appears in the output with the help text from Task 2.

- [ ] **Step 3: Confirm the four commits are in order**

Run: `git log --oneline -5`

Expected (top-down): docs commit, pull-dispatch commit, cli commit, fetch_releases commit, then the spec commit (`c925aa9` or similar).
