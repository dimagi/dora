# Dora Project Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the three-script dora collection at `/home/skelly/src/dora/` into a hostable GitHub project with a Python CLI (`dora pull|report|upload`) and a static GitHub Pages dashboard that renders any `report.json`.

**Architecture:** One repo, two concerns. The CLI lives under `src/dora/` (pip/uv installable Python package, entry point `dora = dora.cli:main`). The dashboard lives under `dashboard/` (vanilla HTML/JS/CSS, served by Pages via `actions/deploy-pages@v4`). Specs live under `docs/superpowers/specs/`. The existing `dora_pull.py` / `dora_report.py` / `dora_push_sheets.py` scripts get ported into the package modules (preserving behavior), then deleted. Google Sheets push is replaced by an optional S3 upload.

**Tech stack:** Python 3.11+, `requests` (runtime), `boto3` (optional `[s3]` extra), `pytest` + `requests-mock` (dev). Dashboard: vanilla ES2022, Chart.js 4 via CDN (SRI-hashed). Package manager: `uv`. CI: GitHub Actions.

**Working directory:** All paths below are relative to `/home/skelly/src/dora/`. The repo is already `git init`'d with `main` as the default branch; the spec (`docs/superpowers/specs/2026-04-24-dora-project-design.md`) and `.gitignore` are already committed. The legacy scripts (`dora_pull.py`, `dora_report.py`, `dora_push_sheets.py`, `README.md`, `dora.json`, `dora.db`) are untracked and will be referenced during porting, then removed in Task 13.

**Reference:** The design spec at `docs/superpowers/specs/2026-04-24-dora-project-design.md` is the source of truth. If this plan and the spec disagree, the spec wins — stop and flag.

---

## Task 1: Initialize Python package skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `src/dora/__init__.py`
- Create: `src/dora/cli.py`
- Create: `LICENSE`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`
- Modify: `.gitignore` (add `uv.lock`? — NO, keep it committed; add `dist/`, `build/`)

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "dora-metrics"
version = "0.1.0"
description = "Pull DORA metrics from GitHub and visualise them on a static dashboard."
readme = "README.md"
requires-python = ">=3.11"
license = { text = "BSD-3-Clause" }
authors = [{ name = "Dimagi" }]
dependencies = [
    "requests>=2.31",
]

[project.optional-dependencies]
s3 = ["boto3>=1.34"]
dev = [
    "pytest>=8.0",
    "requests-mock>=1.11",
]

[project.scripts]
dora = "dora.cli:main"

[project.urls]
Homepage = "https://github.com/dimagi/dora"
Issues   = "https://github.com/dimagi/dora/issues"

[build-system]
requires      = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/dora"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts   = "-ra --strict-markers"
```

- [ ] **Step 2: Write `src/dora/__init__.py`**

```python
"""Dora: DORA metrics collection + reporting CLI."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Write `src/dora/cli.py` (entry-point stub)**

```python
"""Dora CLI — argparse dispatch. Subcommands filled in later tasks."""

import sys


def main(argv: list[str] | None = None) -> int:
    """Entry point referenced by pyproject.toml [project.scripts].

    Subcommands added in later tasks (pull, report, upload).
    """
    argv = argv if argv is not None else sys.argv[1:]
    print("dora: no subcommands wired up yet (skeleton)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Write `LICENSE` (BSD-3-Clause)**

Fetch the canonical text at https://opensource.org/license/bsd-3-clause. Copy it verbatim, fill in:
```
Copyright (c) 2026, Dimagi Inc.
```

- [ ] **Step 5: Write `tests/__init__.py`**

Empty file.

- [ ] **Step 6: Write `tests/conftest.py` (placeholder; extended in Task 2)**

```python
"""Shared pytest fixtures. Extended in Task 2 with the seeded fixture DB."""
```

- [ ] **Step 7: Write `tests/test_smoke.py`**

```python
"""Smoke tests — confirm the package imports and CLI entry point exists."""

import subprocess
import sys

import dora
from dora import cli


def test_package_version():
    assert dora.__version__ == "0.1.0"


def test_cli_main_is_callable():
    assert callable(cli.main)


def test_cli_skeleton_exits_nonzero():
    """The skeleton should exit non-zero (no subcommands wired yet)."""
    rc = cli.main([])
    assert rc != 0


def test_cli_module_runnable_as_script():
    """`python -m dora.cli` should run and exit with the same non-zero code."""
    result = subprocess.run(
        [sys.executable, "-m", "dora.cli"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
```

- [ ] **Step 8: Extend `.gitignore`**

Append these lines (don't replace existing content):

```
# Build outputs
dist/
build/
```

- [ ] **Step 9: Bootstrap the virtualenv**

Run: `uv sync --extra dev --extra s3`
Expected: `uv.lock` created, `.venv/` created.

- [ ] **Step 10: Run smoke tests**

Run: `uv run pytest -v`
Expected: 4 tests pass.

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml uv.lock LICENSE .gitignore src/ tests/
git commit -m "chore: scaffold dora-metrics package

Initial pyproject.toml with entry point, package skeleton, BSD-3-Clause
license, smoke tests for imports and CLI module execution."
```

---

## Task 2: Seed fixture DB for metric + SQL tests

**Files:**
- Create: `tests/fixtures/seed.sql`
- Modify: `tests/conftest.py`
- Create: `tests/test_fixture.py`

The seed DB is used by Tasks 4, 7–10 (db, metrics). It has deterministic inputs that make metric assertions exact.

- [ ] **Step 1: Write `tests/fixtures/seed.sql`**

```sql
-- Seed fixture for metric tests.
--
-- Three weeks of activity across two repos:
--   W42 (2025-10-13 Mon): acme/api  — 3 merged PRs, 1 caused-incident,
--                                     2 deployments (1 success, 1 failure)
--   W43 (2025-10-20 Mon): acme/api  — 2 merged PRs, 0 caused-incident,
--                                     1 deployment (inactive = succeeded-then-superseded)
--                         acme/web  — 1 merged PR (hotfix), 0 deployments
--   W44 (2025-10-27 Mon): acme/api  — 1 merged PR (no first_commit_at), 0 deployments
--
-- Lead-time values (merged_at - first_commit_at in hours):
--   PR 1: 10h, PR 2: 20h, PR 3: 30h, PR 4: 5h, PR 5: 15h, PR 6: 1h, PR 7: NULL
-- Median for W42 = 20h, for W43 on acme/api = 10h, acme/web = 1h.

CREATE TABLE IF NOT EXISTS pull_requests (
    repo TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT,
    author TEXT,
    base TEXT,
    opened_at TEXT NOT NULL,
    merged_at TEXT,
    first_commit_at TEXT,
    merge_sha TEXT,
    labels TEXT,
    PRIMARY KEY (repo, number)
);

CREATE TABLE IF NOT EXISTS deployments (
    repo TEXT NOT NULL,
    deployment_id INTEGER NOT NULL,
    sha TEXT NOT NULL,
    environment TEXT,
    created_at TEXT NOT NULL,
    status TEXT,
    PRIMARY KEY (repo, deployment_id)
);

CREATE INDEX IF NOT EXISTS idx_pr_merged   ON pull_requests(repo, merged_at);
CREATE INDEX IF NOT EXISTS idx_dep_created ON deployments(repo, created_at);

-- W42: acme/api, 3 merged PRs
INSERT INTO pull_requests VALUES
    ('acme/api', 1, 'PR 1', 'alice', 'main',
     '2025-10-13T00:00:00Z', '2025-10-14T10:00:00Z', '2025-10-14T00:00:00Z',
     'sha1', ''),
    ('acme/api', 2, 'PR 2', 'bob',   'main',
     '2025-10-14T00:00:00Z', '2025-10-15T20:00:00Z', '2025-10-15T00:00:00Z',
     'sha2', 'caused-incident'),
    ('acme/api', 3, 'PR 3', 'carol', 'main',
     '2025-10-15T00:00:00Z', '2025-10-16T06:00:00Z', '2025-10-15T00:00:00Z',
     'sha3', '');

-- W42: acme/api deployments (1 success, 1 failure)
INSERT INTO deployments VALUES
    ('acme/api', 100, 'sha1', 'production', '2025-10-14T11:00:00Z', 'success'),
    ('acme/api', 101, 'sha2', 'production', '2025-10-15T21:00:00Z', 'failure');

-- W43: acme/api, 2 merged PRs
INSERT INTO pull_requests VALUES
    ('acme/api', 4, 'PR 4', 'alice', 'main',
     '2025-10-20T00:00:00Z', '2025-10-20T05:00:00Z', '2025-10-20T00:00:00Z',
     'sha4', ''),
    ('acme/api', 5, 'PR 5', 'dave',  'main',
     '2025-10-21T00:00:00Z', '2025-10-21T15:00:00Z', '2025-10-21T00:00:00Z',
     'sha5', '');

-- W43: acme/api deployment (inactive = auto-superseded)
INSERT INTO deployments VALUES
    ('acme/api', 102, 'sha4', 'production', '2025-10-20T06:00:00Z', 'inactive');

-- W43: acme/web, 1 merged PR (hotfix)
INSERT INTO pull_requests VALUES
    ('acme/web', 6, 'PR 6 hotfix', 'alice', 'main',
     '2025-10-22T00:00:00Z', '2025-10-22T01:00:00Z', '2025-10-22T00:00:00Z',
     'sha6', 'hotfix');

-- W44: acme/api, 1 merged PR without first_commit_at (should appear in CFR but not lead-time)
INSERT INTO pull_requests VALUES
    ('acme/api', 7, 'PR 7', 'alice', 'main',
     '2025-10-27T00:00:00Z', '2025-10-28T00:00:00Z', NULL,
     'sha7', '');
```

- [ ] **Step 2: Replace `tests/conftest.py`**

```python
"""Shared pytest fixtures."""

import sqlite3
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_db(tmp_path):
    """SQLite DB on disk, seeded from tests/fixtures/seed.sql.

    On-disk (not :memory:) so subprocess CLI tests can open the same file.
    """
    db_path = tmp_path / "dora.db"
    conn = sqlite3.connect(db_path)
    conn.executescript((FIXTURES / "seed.sql").read_text())
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def fixture_conn(fixture_db):
    """Open a connection to the seeded fixture DB."""
    conn = sqlite3.connect(fixture_db)
    yield conn
    conn.close()
```

- [ ] **Step 3: Write `tests/test_fixture.py`**

```python
"""Sanity: the seeded fixture DB has the expected shape."""


def test_fixture_has_seven_prs(fixture_conn):
    (n,) = fixture_conn.execute("SELECT COUNT(*) FROM pull_requests").fetchone()
    assert n == 7


def test_fixture_has_three_deployments(fixture_conn):
    (n,) = fixture_conn.execute("SELECT COUNT(*) FROM deployments").fetchone()
    assert n == 3


def test_fixture_has_both_repos(fixture_conn):
    rows = fixture_conn.execute(
        "SELECT DISTINCT repo FROM pull_requests ORDER BY repo"
    ).fetchall()
    assert rows == [("acme/api",), ("acme/web",)]
```

- [ ] **Step 4: Run the fixture tests**

Run: `uv run pytest tests/test_fixture.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/fixtures/ tests/test_fixture.py
git commit -m "test: add seeded SQLite fixture for metric tests

Three weeks of PRs + deployments across two repos with known counts,
labels, and lead times — lets every metric be tested against an exact
expected row set."
```

---

## Task 3: CI workflow for tests

**Files:**
- Create: `.github/workflows/test.yml`

- [ ] **Step 1: Write `.github/workflows/test.yml`**

```yaml
name: Tests
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - name: Install
        run: uv sync --extra dev --extra s3 --python ${{ matrix.python }}
      - name: Test
        run: uv run pytest -v
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "ci: run pytest on 3.11/3.12/3.13 for push and PRs"
```

---

## Task 4: Port `db.py` (schema + upserts)

**Files:**
- Create: `src/dora/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing test `tests/test_db.py`**

```python
"""Tests for src/dora/db.py — schema init and upserts."""

import sqlite3

import pytest

from dora import db


def test_init_db_creates_both_tables(tmp_path):
    path = tmp_path / "empty.db"
    conn = db.init_db(path)
    tables = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "pull_requests" in tables
    assert "deployments"   in tables
    conn.close()


def test_init_db_creates_indexes(tmp_path):
    conn = db.init_db(tmp_path / "a.db")
    idx = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
    }
    assert "idx_pr_merged"   in idx
    assert "idx_dep_created" in idx
    conn.close()


def test_init_db_is_idempotent(tmp_path):
    path = tmp_path / "b.db"
    db.init_db(path).close()
    # Second call must not raise.
    db.init_db(path).close()


def test_upsert_pr_inserts(tmp_path):
    conn = db.init_db(tmp_path / "c.db")
    pr = {
        "number": 1, "title": "t", "author": "alice", "base": "main",
        "opened_at": "2025-10-01T00:00:00Z",
        "merged_at": "2025-10-02T00:00:00Z",
        "first_commit_at": "2025-10-01T00:00:00Z",
        "merge_sha": "abc", "labels": "",
    }
    db.upsert_pr(conn, "acme/api", pr)
    conn.commit()
    row = conn.execute(
        "SELECT number, title, first_commit_at FROM pull_requests"
    ).fetchone()
    assert row == (1, "t", "2025-10-01T00:00:00Z")


def test_upsert_pr_preserves_first_commit_on_update(tmp_path):
    """COALESCE: when an update passes first_commit_at=None, keep the old one."""
    conn = db.init_db(tmp_path / "d.db")
    pr = {
        "number": 1, "title": "v1", "author": "alice", "base": "main",
        "opened_at": "2025-10-01T00:00:00Z",
        "merged_at": "2025-10-02T00:00:00Z",
        "first_commit_at": "2025-10-01T00:00:00Z",
        "merge_sha": "abc", "labels": "",
    }
    db.upsert_pr(conn, "acme/api", pr)
    pr_update = {**pr, "title": "v2", "first_commit_at": None}
    db.upsert_pr(conn, "acme/api", pr_update)
    conn.commit()
    title, fca = conn.execute(
        "SELECT title, first_commit_at FROM pull_requests"
    ).fetchone()
    assert title == "v2"
    assert fca   == "2025-10-01T00:00:00Z"  # preserved


def test_upsert_deployment_preserves_status_on_null_update(tmp_path):
    conn = db.init_db(tmp_path / "e.db")
    d = {
        "deployment_id": 100, "sha": "abc", "environment": "production",
        "created_at": "2025-10-01T00:00:00Z", "status": "success",
    }
    db.upsert_deployment(conn, "acme/api", d)
    db.upsert_deployment(conn, "acme/api", {**d, "status": None})
    conn.commit()
    (status,) = conn.execute("SELECT status FROM deployments").fetchone()
    assert status == "success"
```

- [ ] **Step 2: Run test — expect failure**

Run: `uv run pytest tests/test_db.py -v`
Expected: ImportError or ModuleNotFoundError on `from dora import db`.

- [ ] **Step 3: Write `src/dora/db.py`**

```python
"""SQLite schema, connections, upserts for pull_requests + deployments.

Used by both `dora pull` (writes) and `dora report` (reads). Schema is
kept small and stable — the DB is treated as a cache, rebuildable from
the GitHub API at any time.
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS pull_requests (
    repo TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT,
    author TEXT,
    base TEXT,
    opened_at TEXT NOT NULL,
    merged_at TEXT,
    first_commit_at TEXT,
    merge_sha TEXT,
    labels TEXT,
    PRIMARY KEY (repo, number)
);

CREATE TABLE IF NOT EXISTS deployments (
    repo TEXT NOT NULL,
    deployment_id INTEGER NOT NULL,
    sha TEXT NOT NULL,
    environment TEXT,
    created_at TEXT NOT NULL,
    status TEXT,
    PRIMARY KEY (repo, deployment_id)
);

CREATE INDEX IF NOT EXISTS idx_pr_merged   ON pull_requests(repo, merged_at);
CREATE INDEX IF NOT EXISTS idx_dep_created ON deployments(repo, created_at);
"""


def init_db(path: str | Path) -> sqlite3.Connection:
    """Open (or create) the SQLite DB and ensure the schema is present."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def upsert_pr(conn: sqlite3.Connection, repo: str, pr: dict) -> None:
    """Insert or update a PR row.

    COALESCE on first_commit_at: a subsequent upsert that omits the field
    (pr["first_commit_at"] is None) preserves the existing value. Lets the
    pull script skip the expensive /pulls/{n}/commits call for PRs it has
    already seen.
    """
    conn.execute(
        """
        INSERT INTO pull_requests
            (repo, number, title, author, base, opened_at, merged_at,
             first_commit_at, merge_sha, labels)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(repo, number) DO UPDATE SET
            title           = excluded.title,
            merged_at       = excluded.merged_at,
            first_commit_at = COALESCE(excluded.first_commit_at, pull_requests.first_commit_at),
            merge_sha       = excluded.merge_sha,
            labels          = excluded.labels
        """,
        (
            repo, pr["number"], pr["title"], pr["author"], pr["base"],
            pr["opened_at"], pr["merged_at"], pr["first_commit_at"],
            pr["merge_sha"], pr["labels"],
        ),
    )


def upsert_deployment(conn: sqlite3.Connection, repo: str, d: dict) -> None:
    """Insert or update a deployment row.

    COALESCE on status: lets the pull script skip the /statuses call for
    deployments that already have a terminal status.
    """
    conn.execute(
        """
        INSERT INTO deployments
            (repo, deployment_id, sha, environment, created_at, status)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(repo, deployment_id) DO UPDATE SET
            status = COALESCE(excluded.status, deployments.status)
        """,
        (
            repo, d["deployment_id"], d["sha"], d["environment"],
            d["created_at"], d["status"],
        ),
    )
```

- [ ] **Step 4: Run test — expect pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/dora/db.py tests/test_db.py
git commit -m "feat(db): port schema and upserts from dora_pull.py

Pulled out of the monolithic pull script so report.py and pull.py can
share it. COALESCE semantics preserved (first_commit_at on PR upsert,
status on deployment upsert) so cached rows aren't clobbered by
re-runs that intentionally skip the expensive N+1 fetches."
```

---

## Task 5: Port `github.py` — auth, pagination, rate limits

**Files:**
- Create: `src/dora/github.py`
- Create: `tests/test_github.py`

- [ ] **Step 1: Write failing test `tests/test_github.py`**

```python
"""Tests for src/dora/github.py — auth + paginated fetch + rate limits."""

import subprocess
from unittest.mock import patch

import pytest

from dora import github


# --- get_token ------------------------------------------------------------

def test_get_token_uses_gh_cli_first():
    completed = subprocess.CompletedProcess(
        args=["gh", "auth", "token"], returncode=0, stdout="ghp_abc\n", stderr=""
    )
    with patch("dora.github.subprocess.run", return_value=completed):
        assert github.get_token() == "ghp_abc"


def test_get_token_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env_token")
    # Force gh lookup to "fail" (FileNotFoundError simulates gh not installed)
    with patch("dora.github.subprocess.run", side_effect=FileNotFoundError):
        assert github.get_token() == "env_token"


def test_get_token_exits_when_nothing_available(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with patch("dora.github.subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(SystemExit):
            github.get_token()


# --- gh() paginator -------------------------------------------------------

def test_gh_yields_items_across_pages(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/pulls",
        json=[{"id": 1}, {"id": 2}],
        headers={"Link": f'<{base}/repos/x/y/pulls?page=2>; rel="next"'},
    )
    requests_mock.get(
        f"{base}/repos/x/y/pulls?page=2",
        json=[{"id": 3}],
    )
    session = __import__("requests").Session()
    ids = [it["id"] for it in github.gh(session, "/repos/x/y/pulls")]
    assert ids == [1, 2, 3]


def test_gh_sleeps_and_retries_on_rate_limit(requests_mock, monkeypatch):
    base = "https://api.github.com"
    # First response: 403 rate limit with reset timestamp.
    # Second response: 200 with one item.
    calls = {"n": 0}

    def respond(request, context):
        calls["n"] += 1
        if calls["n"] == 1:
            context.status_code = 403
            context.headers["X-RateLimit-Reset"] = "1000"
            return "rate limit exceeded for this request"
        context.status_code = 200
        return [{"id": 1}]

    requests_mock.get(f"{base}/foo", text=respond)

    # Freeze time so computed sleep is predictable, patch sleep to no-op.
    monkeypatch.setattr("dora.github.time.time",  lambda: 995)
    slept = []
    monkeypatch.setattr("dora.github.time.sleep", lambda s: slept.append(s))

    session = __import__("requests").Session()
    items = list(github.gh(session, "/foo"))
    assert items == [{"id": 1}]
    assert slept and slept[0] >= 5
```

- [ ] **Step 2: Run test — expect failure**

Run: `uv run pytest tests/test_github.py -v`
Expected: ImportError on `from dora import github`.

- [ ] **Step 3: Write `src/dora/github.py`**

```python
"""GitHub API client: auth, paginated fetch, rate-limit handling.

Factored out of dora_pull.py so pull logic and HTTP plumbing can be
tested independently. Uses `requests.Session` for connection reuse.
"""

import os
import subprocess
import sys
import time
from collections.abc import Generator, Iterator
from typing import Any

import requests

API = "https://api.github.com"


def get_token() -> str:
    """Return a GitHub token. Prefers `gh auth token`, falls back to GITHUB_TOKEN."""
    try:
        r = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, check=True, timeout=5,
        )
        token = r.stdout.strip()
        if token:
            return token
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    sys.exit("No GitHub auth found. Run `gh auth login`, or set GITHUB_TOKEN.")


def make_session(token: str) -> requests.Session:
    """Configured Session with GitHub auth headers."""
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    return s


def gh(
    session: requests.Session,
    path: str,
    params: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Iterate a paginated GitHub endpoint, handling rate limits.

    Yields items one at a time. Follows Link: rel="next" for pagination.
    On 403 with "rate limit" in the body, sleeps until X-RateLimit-Reset
    and retries the same URL.
    """
    url = f"{API}{path}"
    while url:
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            reset = int(r.headers.get("X-RateLimit-Reset", "0"))
            wait = max(reset - int(time.time()), 0) + 1
            print(f"  rate-limited; sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        r.raise_for_status()
        for item in r.json():
            yield item
        url = r.links.get("next", {}).get("url")
        params = None  # next URL already carries the query string
```

- [ ] **Step 4: Run test — expect pass**

Run: `uv run pytest tests/test_github.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/dora/github.py tests/test_github.py
git commit -m "feat(github): port auth + paginated fetch + rate-limit handling

Extracted from dora_pull.py so pagination and rate-limit retries can
be unit-tested with requests-mock. Behavior unchanged: prefers \`gh
auth token\`, falls back to \$GITHUB_TOKEN, sleeps until
X-RateLimit-Reset on 403 rate limits."
```

---

## Task 6: Port `github.py` — `fetch_prs` + `fetch_deployments`

**Files:**
- Modify: `src/dora/github.py`
- Modify: `tests/test_github.py`

- [ ] **Step 1: Add failing tests to `tests/test_github.py`**

Append to the end of the file:

```python
# --- fetch_prs ------------------------------------------------------------

def test_fetch_prs_filters_to_merged_within_window(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/pulls",
        json=[
            {   # in window, merged → kept
                "number": 1, "title": "t1", "user": {"login": "a"},
                "base": {"ref": "main"}, "labels": [],
                "created_at": "2025-10-10T00:00:00Z",
                "updated_at": "2025-10-10T00:00:00Z",
                "merged_at":  "2025-10-10T00:00:00Z",
                "merge_commit_sha": "s1",
            },
            {   # in window, NOT merged → skipped
                "number": 2, "title": "t2", "user": {"login": "a"},
                "base": {"ref": "main"}, "labels": [],
                "created_at": "2025-10-10T00:00:00Z",
                "updated_at": "2025-10-10T00:00:00Z",
                "merged_at": None,
                "merge_commit_sha": None,
            },
            {   # before window → paginator should stop
                "number": 3, "title": "t3", "user": {"login": "a"},
                "base": {"ref": "main"}, "labels": [],
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "merged_at":  "2024-01-01T00:00:00Z",
                "merge_commit_sha": "s3",
            },
        ],
    )
    requests_mock.get(
        f"{base}/repos/x/y/pulls/1/commits",
        json=[{"commit": {"author": {"date": "2025-10-09T00:00:00Z"}}}],
    )

    session = __import__("requests").Session()
    since = github.iso_to_dt("2025-10-01T00:00:00+00:00")
    out = list(github.fetch_prs(session, "x/y", since, "main", known_prs=set()))
    assert [p["number"] for p in out] == [1]
    assert out[0]["first_commit_at"] == "2025-10-09T00:00:00Z"


def test_fetch_prs_skips_commits_for_known(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/pulls",
        json=[{
            "number": 1, "title": "t", "user": {"login": "a"},
            "base": {"ref": "main"}, "labels": [{"name": "L1"}],
            "created_at": "2025-10-10T00:00:00Z",
            "updated_at": "2025-10-10T00:00:00Z",
            "merged_at":  "2025-10-10T00:00:00Z",
            "merge_commit_sha": "s1",
        }],
    )
    # If the implementation tried /commits, requests-mock would 404.
    session = __import__("requests").Session()
    since = github.iso_to_dt("2025-10-01T00:00:00+00:00")
    out = list(github.fetch_prs(session, "x/y", since, "main", known_prs={1}))
    assert out[0]["first_commit_at"] is None
    assert out[0]["labels"] == "L1"


# --- fetch_deployments ----------------------------------------------------

def test_fetch_deployments_skips_statuses_for_known(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/deployments",
        json=[{
            "id": 100, "sha": "s1", "environment": "production",
            "created_at": "2025-10-10T00:00:00Z",
        }],
    )
    session = __import__("requests").Session()
    since = github.iso_to_dt("2025-10-01T00:00:00+00:00")
    out = list(github.fetch_deployments(
        session, "x/y", since, "production", known_deployments={100}
    ))
    assert out[0]["status"] is None  # preserved via COALESCE in upsert


def test_fetch_deployments_fetches_status_for_unknown(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/deployments",
        json=[{
            "id": 100, "sha": "s1", "environment": "production",
            "created_at": "2025-10-10T00:00:00Z",
        }],
    )
    requests_mock.get(
        f"{base}/repos/x/y/deployments/100/statuses",
        json=[{"state": "success"}],
    )
    session = __import__("requests").Session()
    since = github.iso_to_dt("2025-10-01T00:00:00+00:00")
    out = list(github.fetch_deployments(
        session, "x/y", since, "production", known_deployments=set()
    ))
    assert out[0]["status"] == "success"
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_github.py -v`
Expected: the four new tests fail with `AttributeError: module 'dora.github' has no attribute 'fetch_prs'` (and similar).

- [ ] **Step 3: Extend `src/dora/github.py`**

Append to the end of the file:

```python
from datetime import datetime


def iso_to_dt(s: str) -> datetime:
    """Parse an ISO-8601 timestamp (GitHub uses trailing Z) to aware datetime."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fetch_prs(
    session: requests.Session,
    repo: str,
    since: datetime,
    base: str,
    known_prs: set[int],
) -> Generator[dict, None, None]:
    """Yield merged PRs against `base` merged on/after `since`.

    The /pulls API doesn't filter by merged_at, so we page in updated-desc
    order, stop when we page past `since`, and filter merged_at within.

    PRs whose number is in `known_prs` skip the /commits call (the
    expensive part) — first_commit_at stays None so the upsert COALESCE
    preserves the existing DB value.
    """
    params = {
        "state":     "closed",
        "sort":      "updated",
        "direction": "desc",
        "base":      base,
        "per_page":  100,
    }
    for pr in gh(session, f"/repos/{repo}/pulls", params):
        if iso_to_dt(pr["updated_at"]) < since:
            return
        if not pr["merged_at"] or iso_to_dt(pr["merged_at"]) < since:
            continue

        if pr["number"] in known_prs:
            first_commit_at = None  # cached
        else:
            commits = list(
                gh(session, f"/repos/{repo}/pulls/{pr['number']}/commits", {"per_page": 100})
            )
            first_commit_at = (
                commits[0]["commit"]["author"]["date"] if commits else pr["created_at"]
            )

        yield {
            "number":          pr["number"],
            "title":           pr["title"],
            "author":          (pr.get("user") or {}).get("login"),
            "base":            pr["base"]["ref"],
            "opened_at":       pr["created_at"],
            "merged_at":       pr["merged_at"],
            "first_commit_at": first_commit_at,
            "merge_sha":       pr["merge_commit_sha"],
            "labels":          ",".join(l["name"] for l in pr.get("labels") or []),
        }


def fetch_deployments(
    session: requests.Session,
    repo: str,
    since: datetime,
    environment: str,
    known_deployments: set[int],
) -> Generator[dict, None, None]:
    """Yield deployments for `environment` created on/after `since`.

    Deployments in `known_deployments` (already have a terminal status)
    skip the /statuses call; yielded status is None so COALESCE preserves
    the stored value. Transient statuses (pending/queued/in_progress) are
    always re-fetched because they can change.
    """
    params = {"environment": environment, "per_page": 100}
    for d in gh(session, f"/repos/{repo}/deployments", params):
        if iso_to_dt(d["created_at"]) < since:
            return  # API returns newest first

        if d["id"] in known_deployments:
            status = None
        else:
            statuses = list(
                gh(session, f"/repos/{repo}/deployments/{d['id']}/statuses", {"per_page": 1})
            )
            status = statuses[0]["state"] if statuses else None

        yield {
            "deployment_id": d["id"],
            "sha":           d["sha"],
            "environment":   d["environment"],
            "created_at":    d["created_at"],
            "status":        status,
        }
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/test_github.py -v`
Expected: 9 tests pass (5 from Task 5 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/dora/github.py tests/test_github.py
git commit -m "feat(github): port fetch_prs and fetch_deployments

Includes the caching optimization (skip /commits for known PRs, skip
/statuses for known deployments) — verified by tests that would 404
against requests-mock if the optimization were bypassed."
```

---

## Task 7: Port `metrics.py` — numeric weekly metrics

**Files:**
- Create: `src/dora/metrics.py`
- Create: `tests/test_metrics.py`

Covers four metrics: `deploy-freq-prs`, `deploy-freq`, `lead-time`, `change-failure-rate`.

- [ ] **Step 1: Write failing test `tests/test_metrics.py`**

```python
"""Tests for src/dora/metrics.py against the seeded fixture DB.

Fixture layout (from tests/fixtures/seed.sql):
  W42 acme/api: PRs 1,2,3 (PR 2 = caused-incident); deploys 100(success), 101(failure)
  W43 acme/api: PRs 4,5; deploy 102(inactive)
  W43 acme/web: PR 6 (hotfix)
  W44 acme/api: PR 7 (no first_commit_at)

SQLite strftime('%Y-W%W') notes:
  2025-10-14 is W42, 2025-10-20 is W43, 2025-10-28 is W44.
"""

from dora import metrics

SINCE = "2025-10-01T00:00:00+00:00"


def _row_dict(headers, row):
    return dict(zip(headers, row))


def test_deploy_freq_prs_counts_merged_per_week(fixture_conn):
    headers, rows = metrics.m_deploy_freq_prs(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    assert {"repo": "acme/api", "week": "2025-W42", "deploys": 3} in out
    assert {"repo": "acme/api", "week": "2025-W43", "deploys": 2} in out
    assert {"repo": "acme/api", "week": "2025-W44", "deploys": 1} in out
    assert {"repo": "acme/web", "week": "2025-W43", "deploys": 1} in out


def test_deploy_freq_counts_success_and_inactive(fixture_conn):
    headers, rows = metrics.m_deploy_freq(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    # W42: one success (id 100), one failure (id 101) → count 1
    # W43: one inactive (id 102)                       → count 1
    # (failure is excluded)
    assert {"repo": "acme/api", "environment": "production",
            "week": "2025-W42", "deploys": 1} in out
    assert {"repo": "acme/api", "environment": "production",
            "week": "2025-W43", "deploys": 1} in out
    assert not any(r["deploys"] == 2 for r in out)


def test_lead_time_excludes_rows_with_null_first_commit(fixture_conn):
    headers, rows = metrics.m_lead_time(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    # W42 acme/api: PRs 1,2,3 with lead times 10h, 20h, 30h
    w42 = next(r for r in out if r["repo"] == "acme/api" and r["week"] == "2025-W42")
    assert w42["prs"]      == 3
    assert w42["median_h"] == 20.0
    # W44 acme/api has only PR 7 (NULL first_commit_at) → no W44 row
    assert not any(r["repo"] == "acme/api" and r["week"] == "2025-W44" for r in out)


def test_change_failure_rate_uses_labels(fixture_conn):
    headers, rows = metrics.m_change_failure_rate(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    # W42: 3 merged, 1 caused-incident → 33.3%
    w42 = next(r for r in out if r["repo"] == "acme/api" and r["week"] == "2025-W42")
    assert w42["deploys"]     == 3
    assert w42["failures"]    == 1
    assert w42["failure_pct"] == 33.3
    # W43 acme/web: 1 merged, labelled `hotfix` (NOT counted)
    w43_web = next(r for r in out if r["repo"] == "acme/web" and r["week"] == "2025-W43")
    assert w43_web["failures"] == 0
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: ImportError (`metrics` module doesn't exist yet).

- [ ] **Step 3: Write `src/dora/metrics.py` (partial — four metrics)**

```python
"""Metric queries + post-processing. One pure function per metric.

Each metric function is called as `f(conn, since) -> (headers, rows)`.
Adding a metric means writing a new function and adding one entry to
METRICS at the bottom of the file.
"""

import sqlite3
import statistics

# Labels that mark a PR as having caused a production failure.
# Convention: apply `caused-incident` to the PR that SHIPPED the defect,
# not the PR that FIXED it. `hotfix` is tracked separately (investigative,
# not counted) to avoid double-counting a single failure.
FAILURE_LABELS = ("caused-incident",)

# GitHub auto-marks old successful deployments as `inactive` when newer
# deploys supersede them — so over any time window, most historically-
# successful deploys show up as `inactive`, not `success`.
SUCCESS_DEPLOY_STATUSES = ("success", "inactive")


def m_deploy_freq_prs(conn: sqlite3.Connection, since: str):
    cur = conn.execute(
        """
        SELECT repo,
               strftime('%Y-W%W', merged_at) AS week,
               COUNT(*) AS deploys
        FROM pull_requests
        WHERE merged_at IS NOT NULL AND merged_at >= ?
        GROUP BY repo, week
        ORDER BY repo, week
        """,
        (since,),
    )
    return [c[0] for c in cur.description], cur.fetchall()


def m_deploy_freq(conn: sqlite3.Connection, since: str):
    ph = ",".join("?" * len(SUCCESS_DEPLOY_STATUSES))
    cur = conn.execute(
        f"""
        SELECT repo,
               environment,
               strftime('%Y-W%W', created_at) AS week,
               COUNT(*) AS deploys
        FROM deployments
        WHERE status IN ({ph}) AND created_at >= ?
        GROUP BY repo, environment, week
        ORDER BY repo, environment, week
        """,
        (*SUCCESS_DEPLOY_STATUSES, since),
    )
    return [c[0] for c in cur.description], cur.fetchall()


def m_lead_time(conn: sqlite3.Connection, since: str):
    """Weekly lead time (merged_at - first_commit_at) in hours.

    Aggregation in Python because SQLite has no PERCENTILE_CONT; p90 is
    nearest-rank (fine for small weekly samples).
    """
    cur = conn.execute(
        """
        SELECT repo,
               strftime('%Y-W%W', merged_at) AS week,
               (julianday(merged_at) - julianday(first_commit_at)) * 24.0 AS hours
        FROM pull_requests
        WHERE merged_at       IS NOT NULL
          AND first_commit_at IS NOT NULL
          AND merged_at >= ?
        """,
        (since,),
    )
    buckets: dict[tuple[str, str], list[float]] = {}
    for repo, week, hours in cur:
        buckets.setdefault((repo, week), []).append(hours)

    rows = []
    for (repo, week), vals in sorted(buckets.items()):
        vals.sort()
        mean   = statistics.mean(vals)
        median = statistics.median(vals)
        p90    = vals[min(len(vals) - 1, int(len(vals) * 0.9))]
        rows.append((repo, week, len(vals),
                     round(mean, 1), round(median, 1), round(p90, 1)))
    return ["repo", "week", "prs", "mean_h", "median_h", "p90_h"], rows


def m_change_failure_rate(conn: sqlite3.Connection, since: str):
    # Safe interpolation: FAILURE_LABELS is a hardcoded constant, not user input.
    fail_expr = " OR ".join(f"labels LIKE '%{lab}%'" for lab in FAILURE_LABELS)
    cur = conn.execute(
        f"""
        SELECT repo,
               strftime('%Y-W%W', merged_at) AS week,
               COUNT(*) AS deploys,
               SUM(CASE WHEN {fail_expr} THEN 1 ELSE 0 END) AS failures,
               ROUND(100.0 * SUM(CASE WHEN {fail_expr} THEN 1 ELSE 0 END)
                     / COUNT(*), 1) AS failure_pct
        FROM pull_requests
        WHERE merged_at IS NOT NULL AND merged_at >= ?
        GROUP BY repo, week
        ORDER BY repo, week
        """,
        (since,),
    )
    return [c[0] for c in cur.description], cur.fetchall()


# METRICS dict populated in Task 8 once summary + hotfixes exist.
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/dora/metrics.py tests/test_metrics.py
git commit -m "feat(metrics): port weekly numeric metrics

Ports deploy-freq-prs, deploy-freq, lead-time, and change-failure-rate
into pure-function form. Each asserted against a deterministic fixture
DB with hand-computed expected outputs (CFR 33.3%, lead time median
20h, etc)."
```

---

## Task 8: Port `metrics.py` — `summary` + `hotfixes` + `METRICS` registry

**Files:**
- Modify: `src/dora/metrics.py`
- Modify: `tests/test_metrics.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_metrics.py`:

```python
def test_summary_rollup(fixture_conn):
    headers, rows = metrics.m_summary(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    # acme/api: 6 merged PRs over 3 weeks, 1 caused-incident → CFR 16.7%
    api = next(r for r in out if r["repo"] == "acme/api")
    assert api["prs"] == 6
    assert api["cfr"] == "16.7%"
    # acme/web: 1 merged PR, 0 caused-incident → CFR 0%
    web = next(r for r in out if r["repo"] == "acme/web")
    assert web["prs"] == 1
    assert web["cfr"] == "0%"


def test_hotfixes_lists_hotfix_with_preceding(fixture_conn):
    headers, rows = metrics.m_hotfixes(fixture_conn, SINCE)
    # Expect PR 6 (acme/web, hotfix) as a 'hotfix' row, followed by up to 3
    # 'preceded-by' rows (acme/web has none before it → 1 row total).
    hotfix_rows = [r for r in rows if r[2] == "hotfix"]
    assert len(hotfix_rows) == 1
    assert hotfix_rows[0][1] == "#6"


def test_metrics_registry_has_all_six():
    assert set(metrics.METRICS) == {
        "deploy-freq-prs",
        "deploy-freq",
        "lead-time",
        "change-failure-rate",
        "hotfixes",
        "summary",
    }
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: 3 new failures.

- [ ] **Step 3: Extend `src/dora/metrics.py`**

Replace the trailing `# METRICS dict populated in Task 8…` comment with:

```python
def m_summary(conn: sqlite3.Connection, since: str):
    """Per-repo roll-up over the whole window."""
    repos = [
        r[0] for r in conn.execute(
            "SELECT DISTINCT repo FROM pull_requests "
            "WHERE merged_at >= ? ORDER BY repo",
            (since,),
        )
    ]
    rows = []
    for repo in repos:
        n_prs, n_weeks = conn.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT strftime('%Y-W%W', merged_at))
            FROM pull_requests
            WHERE repo = ? AND merged_at IS NOT NULL AND merged_at >= ?
            """,
            (repo, since),
        ).fetchone()
        prs_per_week = round(n_prs / n_weeks, 1) if n_weeks else 0

        hours = [
            r[0] for r in conn.execute(
                """
                SELECT (julianday(merged_at) - julianday(first_commit_at)) * 24.0
                FROM pull_requests
                WHERE repo = ? AND merged_at IS NOT NULL
                  AND first_commit_at IS NOT NULL AND merged_at >= ?
                """,
                (repo, since),
            )
        ]
        median_h = round(statistics.median(hours), 1) if hours else None

        fail_expr = " OR ".join(f"labels LIKE '%{lab}%'" for lab in FAILURE_LABELS)
        total, failed = conn.execute(
            f"""
            SELECT COUNT(*), SUM(CASE WHEN {fail_expr} THEN 1 ELSE 0 END)
            FROM pull_requests
            WHERE repo = ? AND merged_at IS NOT NULL AND merged_at >= ?
            """,
            (repo, since),
        ).fetchone()
        cfr = round(100.0 * (failed or 0) / total, 1) if total else 0

        rows.append((repo, n_prs, prs_per_week, median_h, f"{cfr}%"))
    return ["repo", "prs", "prs_per_week", "median_lead_h", "cfr"], rows


def m_hotfixes(conn: sqlite3.Connection, since: str):
    """Each hotfix PR plus its 3 preceding merges — investigative tool."""
    hotfixes = conn.execute(
        """
        SELECT repo, number, merged_at, author, title, base
        FROM pull_requests
        WHERE labels LIKE '%hotfix%'
          AND merged_at IS NOT NULL
          AND merged_at >= ?
        ORDER BY merged_at DESC
        """,
        (since,),
    ).fetchall()

    rows = []
    for repo, num, merged_at, author, title, base in hotfixes:
        rows.append((repo, f"#{num}", "hotfix", merged_at[:10], author, title[:70]))
        preceding = conn.execute(
            """
            SELECT number, merged_at, author, title
            FROM pull_requests
            WHERE repo = ? AND base = ?
              AND merged_at < ? AND merged_at IS NOT NULL
              AND number != ?
            ORDER BY merged_at DESC
            LIMIT 3
            """,
            (repo, base, merged_at, num),
        ).fetchall()
        for pnum, pmerged, pauthor, ptitle in preceding:
            rows.append((repo, f"#{pnum}", "preceded-by",
                         pmerged[:10], pauthor, (ptitle or "")[:70]))
    return ["repo", "pr", "relation", "merged", "author", "title"], rows


METRICS = {
    "deploy-freq-prs": (
        m_deploy_freq_prs,
        "Weekly merged PRs (proxy for shipped changes)",
    ),
    "deploy-freq": (
        m_deploy_freq,
        "Weekly successful deployments (success + inactive GitHub statuses)",
    ),
    "lead-time": (
        m_lead_time,
        "Weekly lead time in hours, first commit to merge (mean / median / p90)",
    ),
    "change-failure-rate": (
        m_change_failure_rate,
        f"Weekly % of merged PRs labelled "
        f"{', '.join(f'`{l}`' for l in FAILURE_LABELS)}",
    ),
    "hotfixes": (
        m_hotfixes,
        "Recent hotfix PRs with their preceding merges (investigative)",
    ),
    "summary": (
        m_summary,
        "Per-repo roll-up over the whole window",
    ),
}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/dora/metrics.py tests/test_metrics.py
git commit -m "feat(metrics): port summary + hotfixes + METRICS registry

Completes the metric surface. The METRICS dict is the only thing
dora.report and dora.cli need to know about — adding a metric =
writing one function + registering it here."
```

---

## Task 9: Port `report.py` — runner + formatters

**Files:**
- Create: `src/dora/report.py`
- Create: `tests/test_report.py`

- [ ] **Step 1: Write failing test `tests/test_report.py`**

```python
"""Tests for src/dora/report.py — runner and formatters."""

import json
from io import StringIO

from dora import report


def test_run_report_returns_all_metrics_by_default(fixture_conn):
    out = report.run_report(fixture_conn, since="2025-10-01T00:00:00+00:00")
    names = {r["metric"] for r in out}
    assert names == {
        "deploy-freq-prs", "deploy-freq", "lead-time",
        "change-failure-rate", "hotfixes", "summary",
    }


def test_run_report_filters_by_metric_names(fixture_conn):
    out = report.run_report(
        fixture_conn,
        since="2025-10-01T00:00:00+00:00",
        metrics=["lead-time"],
    )
    assert [r["metric"] for r in out] == ["lead-time"]


def test_json_formatter_has_expected_top_level(fixture_conn):
    out = report.run_report(
        fixture_conn,
        since="2025-10-01T00:00:00+00:00",
        metrics=["deploy-freq-prs"],
    )
    buf = StringIO()
    report.print_json(out, "2025-10-01T00:00:00+00:00", buf)
    data = json.loads(buf.getvalue())
    assert data["since"] == "2025-10-01"
    assert isinstance(data["metrics"], list)
    assert data["metrics"][0]["metric"] == "deploy-freq-prs"
    assert all({"repo", "week", "deploys"} <= set(r)
               for r in data["metrics"][0]["data"])


def test_csv_formatter_emits_comment_metadata(fixture_conn):
    out = report.run_report(
        fixture_conn,
        since="2025-10-01T00:00:00+00:00",
        metrics=["deploy-freq-prs"],
    )
    buf = StringIO()
    report.print_csv(out, "2025-10-01T00:00:00+00:00", buf)
    text = buf.getvalue()
    assert "# metric: deploy-freq-prs" in text
    assert "# since: 2025-10-01"       in text
    # Header row is present after the metadata comments.
    assert "repo,week,deploys" in text


def test_table_formatter_emits_header_and_rows(fixture_conn):
    out = report.run_report(
        fixture_conn,
        since="2025-10-01T00:00:00+00:00",
        metrics=["deploy-freq-prs"],
    )
    buf = StringIO()
    report.print_table(out, "2025-10-01T00:00:00+00:00", buf)
    text = buf.getvalue()
    assert "deploy-freq-prs" in text
    assert "repo"            in text
    assert "acme/api"        in text
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_report.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `src/dora/report.py`**

```python
"""Metric runner and output formatters.

`run_report(conn, since, metrics=None)` returns a list of dicts:
    [{"metric", "description", "headers", "rows"}, ...]

Formatters (`print_table`, `print_csv`, `print_json`) take that list plus
the `since` string and an output stream. Keeping them as pure functions
of list→stream lets the CLI pick a stream (stdout or a file) without
formatters needing to know about files.
"""

import csv
import json
import sqlite3
import sys
from typing import IO

from .metrics import METRICS


def run_report(
    conn: sqlite3.Connection,
    since: str,
    metrics: list[str] | None = None,
) -> list[dict]:
    names = metrics or list(METRICS)
    results = []
    for name in names:
        func, description = METRICS[name]
        headers, rows = func(conn, since)
        results.append({
            "metric":      name,
            "description": description,
            "headers":     headers,
            "rows":        rows,
        })
    return results


def print_table(results: list[dict], since: str, stream: IO[str] = sys.stdout) -> None:
    for i, r in enumerate(results):
        if i:
            stream.write("\n")
        stream.write(f"# {r['metric']}  (since {since[:10]})\n")
        stream.write(f"# {r['description']}\n")
        headers, rows = r["headers"], r["rows"]
        if not rows:
            stream.write("  (no data)\n")
            continue
        widths = [len(h) for h in headers]
        for row in rows:
            for j, val in enumerate(row):
                widths[j] = max(widths[j], len(str(val if val is not None else "-")))
        fmt = "  ".join(f"{{:<{w}}}" for w in widths)
        stream.write(fmt.format(*headers) + "\n")
        stream.write(fmt.format(*("-" * w for w in widths)) + "\n")
        for row in rows:
            stream.write(fmt.format(*(str(v) if v is not None else "-" for v in row)) + "\n")


def print_csv(results: list[dict], since: str, stream: IO[str] = sys.stdout) -> None:
    w = csv.writer(stream)
    for i, r in enumerate(results):
        if i:
            stream.write("\n")
        stream.write(f"# metric: {r['metric']}\n")
        stream.write(f"# description: {r['description']}\n")
        stream.write(f"# since: {since[:10]}\n")
        w.writerow(r["headers"])
        w.writerows(r["rows"])


def print_json(results: list[dict], since: str, stream: IO[str] = sys.stdout) -> None:
    payload = {
        "since": since[:10],
        "metrics": [
            {
                "metric":      r["metric"],
                "description": r["description"],
                "data":        [dict(zip(r["headers"], row)) for row in r["rows"]],
            }
            for r in results
        ],
    }
    json.dump(payload, stream, default=str, indent=2)
    stream.write("\n")


FORMATTERS = {
    "table": print_table,
    "csv":   print_csv,
    "json":  print_json,
}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/test_report.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/dora/report.py tests/test_report.py
git commit -m "feat(report): port runner + formatters (table/csv/json)

Formatters take an explicit output stream so the CLI can target stdout
or a file via --output. run_report returns plain dicts so callers don't
need to import METRICS."
```

---

## Task 10: Port `pull.py` (orchestration)

**Files:**
- Create: `src/dora/pull.py`

No dedicated tests for `pull.py` — its moving parts (`db.py`, `github.py`) are already tested. CLI smoke test in Task 11 exercises this end-to-end against a mocked HTTP session.

- [ ] **Step 1: Write `src/dora/pull.py`**

```python
"""Orchestration: fetch GitHub → upsert into SQLite, with caching + progress."""

import sqlite3
import sys
from datetime import datetime

from . import db, github

TERMINAL_DEPLOY_STATUSES = frozenset({"success", "failure", "error", "inactive"})


def _make_progress(label: str):
    """(tick, done) callbacks that print a running counter on stderr.

    On a TTY, overwrite a single line. Otherwise, every 10 ticks so log
    tails stay readable.
    """
    tty = sys.stderr.isatty()
    n = 0

    def tick():
        nonlocal n
        n += 1
        if tty:
            print(f"\r  {label}: {n}", file=sys.stderr, end="", flush=True)
        elif n % 10 == 0:
            print(f"  {label}: {n}", file=sys.stderr, flush=True)

    def done():
        if tty:
            print(f"\r  {label}: {n}", file=sys.stderr, flush=True)
        else:
            print(f"  {label}: {n} (done)", file=sys.stderr, flush=True)

    return tick, done


def run_pull(
    *,
    repos: list[str],
    since: str,
    db_path: str,
    base: str,
    environment: str,
    skip_prs: bool,
    skip_deployments: bool,
) -> None:
    """Pull signals for one or more repos into the SQLite DB."""
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

            if not skip_deployments:
                placeholders = ",".join("?" * len(TERMINAL_DEPLOY_STATUSES))
                known_deployments = {
                    row[0] for row in conn.execute(
                        f"SELECT deployment_id FROM deployments "
                        f"WHERE repo = ? AND environment = ? "
                        f"AND status IN ({placeholders})",
                        (repo, environment, *TERMINAL_DEPLOY_STATUSES),
                    )
                }
                print(
                    f"  fetching deployments ({environment})… "
                    f"({len(known_deployments)} cached, statuses call skipped)",
                    file=sys.stderr,
                )
                tick, done = _make_progress(f"deployments ({environment})")
                n_cached = 0
                for d in github.fetch_deployments(
                    session, repo, since_dt, environment, known_deployments
                ):
                    db.upsert_deployment(conn, repo, d)
                    if d["deployment_id"] in known_deployments:
                        n_cached += 1
                    tick()
                done()
                if n_cached:
                    print(f"    ({n_cached} reused from cache)", file=sys.stderr)
                conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 2: Quick smoke — run the existing test suite**

Run: `uv run pytest -v`
Expected: all previous tests still pass (no regressions).

- [ ] **Step 3: Commit**

```bash
git add src/dora/pull.py
git commit -m "feat(pull): port orchestration layer

Thin coordinator that wires github.fetch_* to db.upsert_*, with progress
ticker and cache-aware logging. No dedicated tests — the HTTP layer and
DB layer are already unit-tested, and the CLI smoke test (next task)
exercises this end-to-end."
```

---

## Task 11: Build `cli.py` — argparse + `pull` + `report` subcommands

**Files:**
- Modify: `src/dora/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing test `tests/test_cli.py`**

```python
"""CLI smoke tests — parse + dispatch + end-to-end JSON output."""

import json
import subprocess
import sys

import pytest

from dora import cli


def test_no_args_shows_help(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    # argparse prints help and exits with code 2 when required subcommand is missing.
    assert exc.value.code == 2


def test_report_subcommand_invokes_json(fixture_db, capsys):
    rc = cli.main([
        "report",
        "--db", str(fixture_db),
        "--weeks", "52",         # wide window to include all fixture data
        "--format", "json",
        "--metric", "deploy-freq-prs",
    ])
    assert rc == 0
    text = capsys.readouterr().out
    payload = json.loads(text)
    assert payload["metrics"][0]["metric"] == "deploy-freq-prs"
    assert any(d["repo"] == "acme/api" for d in payload["metrics"][0]["data"])


def test_report_writes_to_output_file(fixture_db, tmp_path):
    out = tmp_path / "out.json"
    rc = cli.main([
        "report",
        "--db", str(fixture_db),
        "--weeks", "52",
        "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    assert out.exists()
    payload = json.loads(out.read_text())
    assert "metrics" in payload


def test_report_via_python_m_module(fixture_db):
    """End-to-end: `python -m dora report ...` returns exit 0 + parseable JSON."""
    result = subprocess.run(
        [
            sys.executable, "-m", "dora", "report",
            "--db", str(fixture_db), "--weeks", "52",
            "--format", "json", "--metric", "summary",
        ],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["metrics"][0]["metric"] == "summary"
```

- [ ] **Step 2: Create `src/dora/__main__.py` so `python -m dora` works**

```python
"""Entry point for `python -m dora`."""

from .cli import main

raise SystemExit(main())
```

- [ ] **Step 3: Rewrite `src/dora/cli.py`**

```python
"""Dora CLI — argparse + subcommand dispatch.

Subcommands (each in its own module):
  - pull    (dora.pull.run_pull)
  - report  (dora.report.run_report + formatters)
  - upload  (dora.upload.upload — optional, added in Task 12)
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Sequence

from . import pull as pull_mod
from . import report as report_mod
from .metrics import METRICS


def _add_pull(sub):
    p = sub.add_parser("pull", help="Fetch DORA signals from GitHub into SQLite.")
    p.add_argument("--repo", required=True, action="append", help="owner/name (repeatable)")
    p.add_argument("--since", required=True, help="ISO date, e.g. 2025-10-01")
    p.add_argument("--db", default="dora.db")
    p.add_argument("--base", default="main")
    p.add_argument("--environment", default="production")
    p.add_argument("--skip-prs", action="store_true")
    p.add_argument("--skip-deployments", action="store_true")


def _add_report(sub):
    p = sub.add_parser("report", help="Run metric queries, emit table/CSV/JSON.")
    p.add_argument("--db", default="dora.db")
    p.add_argument("--weeks", type=int, default=12)
    p.add_argument("--metric", choices=list(METRICS), action="append")
    p.add_argument("--format", choices=list(report_mod.FORMATTERS), default="table")
    p.add_argument("--output", help="Write output to FILE instead of stdout")


def _cmd_pull(args: argparse.Namespace) -> int:
    pull_mod.run_pull(
        repos=args.repo,
        since=args.since,
        db_path=args.db,
        base=args.base,
        environment=args.environment,
        skip_prs=args.skip_prs,
        skip_deployments=args.skip_deployments,
    )
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    since = (datetime.now(timezone.utc) - timedelta(weeks=args.weeks)).isoformat()
    conn = sqlite3.connect(args.db)
    try:
        results = report_mod.run_report(conn, since, metrics=args.metric)
    finally:
        conn.close()
    fmt = report_mod.FORMATTERS[args.format]
    if args.output:
        with open(args.output, "w") as f:
            fmt(results, since, f)
    else:
        fmt(results, since, sys.stdout)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dora",
        description="Collect DORA metrics from GitHub and report them.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    _add_pull(sub)
    _add_report(sub)
    # _add_upload is registered in Task 12.

    args = parser.parse_args(argv)

    dispatch = {
        "pull":   _cmd_pull,
        "report": _cmd_report,
    }
    return dispatch[args.command](args)
```

- [ ] **Step 4: Drop the now-obsolete smoke test**

`tests/test_smoke.py::test_cli_skeleton_exits_nonzero` previously relied on the placeholder behavior. Replace its contents with tests that don't contradict the new CLI:

Replace the entire file with:

```python
"""Smoke tests — package import + CLI help path."""

import subprocess
import sys

import dora
from dora import cli


def test_package_version():
    assert dora.__version__ == "0.1.0"


def test_cli_main_is_callable():
    assert callable(cli.main)


def test_help_does_not_crash():
    """`dora --help` exits 0 and prints the top-level help."""
    result = subprocess.run(
        [sys.executable, "-m", "dora", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "dora" in result.stdout
    assert "report" in result.stdout
```

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass (smoke tests + test_db + test_github + test_metrics + test_report + test_cli = 30+ tests).

- [ ] **Step 6: Commit**

```bash
git add src/dora/cli.py src/dora/__main__.py tests/test_cli.py tests/test_smoke.py
git commit -m "feat(cli): wire pull + report subcommands with argparse

Adds python -m dora entry point. --output flag on 'report' lets CI
skip shell redirection. Upload subcommand added in next task."
```

---

## Task 12: Port `upload.py` — S3 target

**Files:**
- Create: `src/dora/upload.py`
- Create: `tests/test_upload.py`
- Modify: `src/dora/cli.py`

- [ ] **Step 1: Write failing test `tests/test_upload.py`**

```python
"""Tests for src/dora/upload.py — S3 target parsing + boto3 call shape."""

from unittest.mock import MagicMock, patch

import pytest

from dora import upload


def test_parse_s3_target_extracts_bucket_and_key():
    bucket, key = upload.parse_s3_target("s3://my-bucket/path/to/report.json")
    assert bucket == "my-bucket"
    assert key    == "path/to/report.json"


def test_parse_s3_target_rejects_non_s3_url():
    with pytest.raises(ValueError, match="must start with s3://"):
        upload.parse_s3_target("https://example.com/a.json")


def test_parse_s3_target_rejects_missing_key():
    with pytest.raises(ValueError, match="bucket and key"):
        upload.parse_s3_target("s3://just-a-bucket")


def test_upload_s3_calls_boto3_put_object(tmp_path):
    f = tmp_path / "report.json"
    f.write_text('{"hello": "world"}')
    mock_client = MagicMock()
    with patch("dora.upload.boto3.client", return_value=mock_client):
        upload.upload_s3(str(f), "s3://bk/report.json",
                         content_type="application/json", public_read=False)
    assert mock_client.put_object.called
    kwargs = mock_client.put_object.call_args.kwargs
    assert kwargs["Bucket"]      == "bk"
    assert kwargs["Key"]         == "report.json"
    assert kwargs["ContentType"] == "application/json"
    assert "ACL" not in kwargs   # public_read=False


def test_upload_s3_sets_public_read_acl(tmp_path):
    f = tmp_path / "r.json"
    f.write_text("{}")
    mock_client = MagicMock()
    with patch("dora.upload.boto3.client", return_value=mock_client):
        upload.upload_s3(str(f), "s3://bk/r.json",
                         content_type="application/json", public_read=True)
    assert mock_client.put_object.call_args.kwargs["ACL"] == "public-read"
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_upload.py -v`
Expected: ImportError on `from dora import upload`.

- [ ] **Step 3: Write `src/dora/upload.py`**

```python
"""Upload a file to a supported target URL.

Currently supports `s3://bucket/key`. Credentials come from the default
boto3 chain (env vars, `~/.aws/credentials`, IAM role) — no
dora-specific flags.

`boto3` is an optional extra: install with `uv tool install "dora-metrics[s3]"`
or `pip install dora-metrics[s3]`.
"""

from pathlib import Path

try:
    import boto3
except ImportError as exc:
    boto3 = None  # type: ignore[assignment]
    _boto_import_error = exc
else:
    _boto_import_error = None


def parse_s3_target(target: str) -> tuple[str, str]:
    """Parse `s3://bucket/key...` → (bucket, key). Raises ValueError on bad input."""
    if not target.startswith("s3://"):
        raise ValueError(f"Target must start with s3://, got: {target!r}")
    rest = target[len("s3://"):]
    if "/" not in rest:
        raise ValueError(
            f"Target must include bucket and key (s3://bucket/key), got: {target!r}"
        )
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        raise ValueError(
            f"Target must include bucket and key (s3://bucket/key), got: {target!r}"
        )
    return bucket, key


def upload_s3(
    path: str,
    target: str,
    *,
    content_type: str,
    public_read: bool,
) -> None:
    """Upload `path` to an S3 `target` URL."""
    if boto3 is None:
        raise RuntimeError(
            "boto3 not installed. Install the s3 extra: "
            "`uv tool install \"dora-metrics[s3]\"`"
        ) from _boto_import_error

    bucket, key = parse_s3_target(target)
    data = Path(path).read_bytes()
    client = boto3.client("s3")
    kwargs: dict = {
        "Bucket":      bucket,
        "Key":         key,
        "Body":        data,
        "ContentType": content_type,
    }
    if public_read:
        kwargs["ACL"] = "public-read"
    client.put_object(**kwargs)
```

- [ ] **Step 4: Wire `upload` subcommand in `src/dora/cli.py`**

Add this function above `main`:

```python
def _add_upload(sub):
    p = sub.add_parser("upload", help="Upload a file to a target URL (e.g. s3://…).")
    p.add_argument("path", help="File to upload")
    p.add_argument("--target", required=True, help="Destination URL, e.g. s3://bucket/key")
    p.add_argument("--content-type", default="application/json")
    p.add_argument("--public-read", action="store_true",
                   help="Set public-read ACL on the object (S3 only)")


def _cmd_upload(args: argparse.Namespace) -> int:
    from . import upload as upload_mod  # lazy: boto3 only needed for this path
    upload_mod.upload_s3(
        args.path, args.target,
        content_type=args.content_type,
        public_read=args.public_read,
    )
    return 0
```

Then in `main`, add:

```python
    _add_upload(sub)
```

right after `_add_report(sub)`. And add `"upload": _cmd_upload,` to the `dispatch` dict.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests pass; 5 new tests in `test_upload.py`.

- [ ] **Step 6: Commit**

```bash
git add src/dora/upload.py src/dora/cli.py tests/test_upload.py
git commit -m "feat(upload): add S3 upload subcommand

Replaces the Google Sheets push. boto3 is an optional extra (lazy
import in cli.py so report/pull work without it installed). Default
boto3 credential chain; no dora-specific auth flags."
```

---

## Task 13: Migrate legacy files + anonymize sample JSON

**Files:**
- Delete: `/home/skelly/src/dora/dora_pull.py`
- Delete: `/home/skelly/src/dora/dora_report.py`
- Delete: `/home/skelly/src/dora/dora_push_sheets.py`
- Delete: `/home/skelly/src/dora/dora.json` (after migration)
- Create: `dashboard/fixtures/sample.json`

- [ ] **Step 1: Generate the anonymized sample**

The old `dora.json` contains `dimagi/open-chat-studio`. Anonymize to `acme/example`.

Run:

```bash
mkdir -p dashboard/fixtures
sed 's|dimagi/open-chat-studio|acme/example|g' dora.json > dashboard/fixtures/sample.json
```

- [ ] **Step 2: Sanity-check the anonymized file**

Run: `grep -c 'acme/example' dashboard/fixtures/sample.json`
Expected: a positive integer (many matches).

Run: `grep -c 'dimagi' dashboard/fixtures/sample.json`
Expected: `0` (zero matches).

- [ ] **Step 3: Delete the originals**

```bash
rm dora_pull.py dora_report.py dora_push_sheets.py dora.json
```

- [ ] **Step 4: Verify tests still pass**

Run: `uv run pytest -v`
Expected: all tests pass (migration shouldn't affect anything — those files were untracked).

- [ ] **Step 5: Commit**

```bash
git add dashboard/fixtures/sample.json
git commit -m "chore: migrate dora.json to dashboard/fixtures/sample.json

Repo name anonymized acme/example. Old standalone scripts
(dora_pull.py, dora_report.py, dora_push_sheets.py) deleted —
their logic lives in src/dora/ now."
```

---

## Task 14: Dashboard — `index.html` + `style.css`

**Files:**
- Create: `dashboard/index.html`
- Create: `dashboard/style.css`

- [ ] **Step 1: Write `dashboard/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DORA metrics</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>

<header>
  <h1>DORA metrics</h1>

  <div class="source-row">
    <label for="url-input" class="sr-only">Report URL</label>
    <input id="url-input" type="url" placeholder="https://…/report.json">
    <button id="url-load" type="button">Load</button>

    <label for="file-input" class="file-label">or choose file…</label>
    <input id="file-input" type="file" accept=".json,application/json">

    <span id="source-info" class="source-info"></span>

    <label for="repo-filter" class="repo-label" hidden>Repo:</label>
    <select id="repo-filter" hidden></select>
  </div>
</header>

<main>
  <section id="summary" aria-label="Summary">
    <!-- populated by app.js from `summary` metric -->
  </section>

  <section id="charts" aria-label="Weekly charts">
    <div class="chart-grid">
      <figure><canvas id="chart-deploy-freq-prs"></canvas><figcaption>Deploy frequency (merged PRs)</figcaption></figure>
      <figure><canvas id="chart-deploy-freq"></canvas><figcaption>Deploy frequency (deployments)</figcaption></figure>
      <figure><canvas id="chart-lead-time"></canvas><figcaption>Lead time (hours)</figcaption></figure>
      <figure><canvas id="chart-cfr"></canvas><figcaption>Change failure rate (%)</figcaption></figure>
    </div>
  </section>

  <section id="detail">
    <details>
      <summary>Weekly metrics (raw tables)</summary>
      <div id="detail-tables"></div>
    </details>
    <details>
      <summary>Hotfix investigation</summary>
      <div id="hotfixes-table"></div>
    </details>
  </section>

  <p id="empty-state" class="empty-state" hidden>
    No report loaded. Enter a URL, pick a file, or
    <a href="?url=fixtures/sample.json">view the sample dataset</a>.
  </p>
</main>

<footer>
  <p>Built with <a href="https://github.com/dimagi/dora">dora-metrics</a>.</p>
</footer>

<!-- Chart.js 4 — CDN + SRI.
     Verify the hash at https://www.jsdelivr.com/package/npm/chart.js
     before bumping the version. -->
<script
  src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"
  integrity="sha384-UBLRvI4lxzNjxiP4QQ5j0vaW3zPuyYqIFCIl0NVs9+zVc5K2bCEAC9H2CP9cFsrm"
  crossorigin="anonymous"
  referrerpolicy="no-referrer"></script>
<script src="app.js" defer></script>

</body>
</html>
```

**IMPORTANT:** the SRI hash above is illustrative. Before committing, the implementer MUST fetch the actual SHA-384 for `chart.js@4.4.7/dist/chart.umd.min.js` from jsdelivr (the URL in the comment provides SRI hashes directly) and replace the value. Or pin a known-good version and verify locally:

```bash
curl -s https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js \
  | openssl dgst -sha384 -binary | openssl base64 -A
```

- [ ] **Step 2: Write `dashboard/style.css`**

```css
:root {
  --bg:        #ffffff;
  --fg:        #1a1a1a;
  --muted:    #666666;
  --border:   #dddddd;
  --accent:   #2563eb;
  --chart-bg: #f5f5f5;
  --ok:       #16a34a;
  --warn:     #ca8a04;
  --bad:      #dc2626;
  font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg:        #0f172a;
    --fg:        #e2e8f0;
    --muted:     #94a3b8;
    --border:    #334155;
    --accent:    #60a5fa;
    --chart-bg:  #1e293b;
  }
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  line-height: 1.5;
}

header, main, footer {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1rem 1.25rem;
}

header { border-bottom: 1px solid var(--border); }
h1 { margin: 0 0 0.5rem 0; font-size: 1.5rem; }

.source-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}
.source-row input[type="url"] {
  flex: 1 1 24rem;
  min-width: 12rem;
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg);
  color: var(--fg);
}
.source-row button {
  padding: 0.4rem 0.8rem;
  background: var(--accent);
  color: white;
  border: 0;
  border-radius: 4px;
  cursor: pointer;
}
.source-row input[type="file"] { width: 0.1px; height: 0.1px; opacity: 0; position: absolute; }
.file-label {
  padding: 0.4rem 0.8rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  cursor: pointer;
}
.source-info { color: var(--muted); font-size: 0.875rem; }
.sr-only { position: absolute; left: -9999px; }

#summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
  gap: 0.75rem;
  margin: 1rem 0;
}
.tile {
  padding: 0.75rem 1rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--chart-bg);
}
.tile .label { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
.tile .value { font-size: 1.5rem; font-weight: 600; margin-top: 0.25rem; }

.chart-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(22rem, 1fr));
  gap: 1rem;
}
figure {
  margin: 0;
  padding: 0.75rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--chart-bg);
}
figcaption { color: var(--muted); font-size: 0.875rem; margin-top: 0.5rem; }

#detail details {
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-top: 1rem;
  padding: 0.5rem 1rem;
}
#detail summary { cursor: pointer; font-weight: 600; }
#detail table {
  border-collapse: collapse;
  width: 100%;
  margin-top: 0.75rem;
  font-size: 0.875rem;
}
#detail th {
  text-align: left;
  border-bottom: 2px solid var(--border);
  padding: 0.4rem 0.6rem;
  cursor: pointer;
  user-select: none;
}
#detail td {
  border-bottom: 1px solid var(--border);
  padding: 0.4rem 0.6rem;
}

.empty-state {
  text-align: center;
  color: var(--muted);
  padding: 2rem;
}

footer {
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 0.875rem;
}
```

- [ ] **Step 3: Preview locally**

```bash
cd dashboard && python -m http.server 8000
```

Open `http://localhost:8000/` in a browser. Expected: the page renders header, empty chart grid, empty-state message. Expect a 404 in the console for `app.js` (created in Task 15) — that's fine; this step is only confirming markup and styles render.

Stop the server (Ctrl-C).

- [ ] **Step 4: Commit**

```bash
git add dashboard/index.html dashboard/style.css
git commit -m "feat(dashboard): markup + styles

Semantic HTML, no inline JS, CSS variables with dark-mode via
prefers-color-scheme. Chart.js loaded from jsdelivr with SRI hash
(REVIEWER: verify the SRI hash before merge)."
```

---

## Task 15: Dashboard — `app.js` source loader

**Files:**
- Create: `dashboard/app.js`

This task establishes the loader (URL param > file picker > localStorage > sample). Rendering code goes in Task 16.

- [ ] **Step 1: Write `dashboard/app.js`**

```javascript
/* Dora dashboard — source loader + renderers.
 *
 * Source priority: ?url= > file input > localStorage > fixtures/sample.json
 *
 * Renderers in Task 16.
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

// --------- render (stub; expanded in Task 16) ---------

function render() {
  populateRepoFilter();
  // Renderers in Task 16. For now, just log so we know loading worked.
  console.log("Report loaded:", currentReport.since, currentReport.metrics.map(m => m.metric));
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
```

- [ ] **Step 2: Preview locally**

```bash
cd dashboard && python -m http.server 8000
```

Open `http://localhost:8000/`. Expected:
- Source info shows "Source: sample (demo data) · loaded just now"
- Repo dropdown appears only if the sample has multiple repos
- Browser console logs `Report loaded: 2025-10-24 [...]` with the metric names

Stop the server.

- [ ] **Step 3: Commit**

```bash
git add dashboard/app.js
git commit -m "feat(dashboard): source loader (URL/file/localStorage/fixture)

Renderers are stubbed in this task (log only) — added in next task."
```

---

## Task 16: Dashboard — renderers (summary tiles, charts, tables)

**Files:**
- Modify: `dashboard/app.js`

- [ ] **Step 1: Replace the stub `render()` and add renderers**

In `dashboard/app.js`, replace the stub `render` function with:

```javascript
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
  // If no repo filter, pick first row as "primary" (acceptable for a quick tile view).
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
```

- [ ] **Step 2: Preview locally**

```bash
cd dashboard && python -m http.server 8000
```

Open `http://localhost:8000/`. Expected:
- Four charts render with the sample data
- Summary tiles show PRs / PRs per week / Median lead (h) / CFR
- "Weekly metrics (raw tables)" and "Hotfix investigation" expandable sections render tables
- Clicking a table header sorts that column (numeric columns sort numerically)
- If the sample has multiple repos, the repo dropdown filters all sections

If `fixtures/sample.json` has only one repo (which is the case for the OCS-derived sample), the repo dropdown stays hidden — this is correct.

Stop the server.

- [ ] **Step 3: Commit**

```bash
git add dashboard/app.js
git commit -m "feat(dashboard): summary tiles, charts, sortable tables

Chart.js line charts for the four weekly metrics; lead-time renders
three series (mean/median/p90). Tables rendered with a tiny
sort-on-header helper — no table library. Repo filter (hidden when
there's only one repo) narrows all sections uniformly."
```

---

## Task 17: Pages deploy workflow

**Files:**
- Create: `.github/workflows/pages.yml`

- [ ] **Step 1: Write `.github/workflows/pages.yml`**

```yaml
name: Deploy dashboard to Pages
on:
  push:
    branches: [main]
    paths:
      - "dashboard/**"
      - ".github/workflows/pages.yml"
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/configure-pages@v4
      - uses: actions/upload-pages-artifact@v3
        with:
          path: dashboard
      - id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/pages.yml
git commit -m "ci: deploy dashboard/ to GitHub Pages on main

Path-filtered so test-only changes don't redeploy. Uses upload-pages-
artifact@v3 + deploy-pages@v4 to ship the directory as-is (no build
step)."
```

---

## Task 18: Example adopter workflow

**Files:**
- Create: `examples/workflows/dora-report.yml`

- [ ] **Step 1: Write `examples/workflows/dora-report.yml`**

```yaml
# Copy this file into your repo at .github/workflows/dora-report.yml
# Edit the `--since` date once on adoption. No other secrets needed
# beyond the default GITHUB_TOKEN.
#
# Once deployed, share this link internally:
#   https://<dora-owner>.github.io/dora/?url=https://raw.githubusercontent.com/<your-repo>/main/dora-report.json
name: DORA metrics
on:
  schedule:
    - cron: "0 6 * * 1"   # Mondays, 06:00 UTC
  workflow_dispatch:

jobs:
  report:
    runs-on: ubuntu-latest
    permissions:
      contents: write   # to commit dora-report.json back to the repo
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3

      - name: Install dora
        run: uv tool install git+https://github.com/dimagi/dora

      - name: Pull & report
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          dora pull --repo ${{ github.repository }} --since 2025-10-01
          dora report --format json --output dora-report.json

      - name: Commit report
        run: |
          git config user.name  "dora-bot"
          git config user.email "dora-bot@users.noreply.github.com"
          git add dora-report.json
          if git diff --staged --quiet; then
            echo "No change to dora-report.json"
          else
            git commit -m "Update DORA report"
            git push
          fi

# --- S3 variant -------------------------------------------------------------
# Replace the "Commit report" step with:
#
#       - name: Upload to S3
#         env:
#           AWS_ACCESS_KEY_ID:     ${{ secrets.AWS_ACCESS_KEY_ID }}
#           AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
#           AWS_DEFAULT_REGION:    us-east-1
#         run: |
#           uv tool install "git+https://github.com/dimagi/dora[s3]"
#           dora upload dora-report.json \
#             --target s3://my-bucket/dora-report.json --public-read
#
# S3 bucket CORS (so the dashboard can fetch from your bucket):
#   [ { "AllowedOrigins": ["*"],
#       "AllowedMethods": ["GET"],
#       "AllowedHeaders": ["*"] } ]
```

- [ ] **Step 2: Commit**

```bash
git add examples/workflows/dora-report.yml
git commit -m "docs: template CI workflow for adopting teams

Two commit-then-push scripts (git-back-to-repo default, S3 variant
in a comment). Includes the S3 bucket CORS config teams need."
```

---

## Task 19: Rewrite README

**Files:**
- Modify: `README.md` (untracked → tracked, contents replaced)

- [ ] **Step 1: Replace `README.md`**

```markdown
# Dora — DORA metrics from GitHub

[![Tests](https://github.com/dimagi/dora/actions/workflows/test.yml/badge.svg)](https://github.com/dimagi/dora/actions/workflows/test.yml)

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
2. Pulls into a temporary SQLite DB
3. Writes `dora-report.json`
4. Commits the JSON back to your repo

Your dashboard link becomes:

```
https://dimagi.github.io/dora/?url=https://raw.githubusercontent.com/<your-repo>/main/dora-report.json
```

### Cross-repo reports

The default `GITHUB_TOKEN` in Actions is scoped to the workflow's own repo. To aggregate multiple repos (`--repo a/b --repo c/d`), generate a PAT or install a GitHub App with access to each repo and pass its token via `GITHUB_TOKEN` in the env.

### S3 variant

A commented S3 upload step is in the example workflow. You'll need:
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` as repo secrets
- Bucket CORS config allowing `GET` from `*` (so the dashboard can fetch)

## Metric definitions

| Metric | Counts | Notes |
|---|---|---|
| `deploy-freq-prs` | Merged PRs into `main` per week | Overstates if PRs are batched into single deploys |
| `deploy-freq` | Successful deployments per week | Counts both `success` and `inactive` GitHub statuses |
| `lead-time` | Hours from first commit to merge | Mean / median / p90 per week |
| `change-failure-rate` | % of merged PRs labelled `caused-incident` | Requires label discipline |
| `hotfixes` | Recent `hotfix`-labelled PRs + their 3 preceding merges | Investigative — helps find causing PRs to backfill `caused-incident` |
| `summary` | Per-repo roll-up over the window | Used by the dashboard's summary tiles |

## Label conventions

- **`caused-incident`** — applied to the PR that SHIPPED a production defect. This is what `change-failure-rate` counts.
- **`hotfix`** — applied to the PR that FIXED a prior defect. Not counted in CFR (avoids double-counting one incident as two). Surfaced by `hotfixes`.

Do not apply both to the same PR.

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

deployments (repo, deployment_id) PK
  sha, environment, created_at, status
```

The DB is a rebuildable cache — not a source of truth. Drop it and re-pull at any time.

## Roadmap

See [`docs/superpowers/specs/2026-04-24-dora-project-design.md`](docs/superpowers/specs/2026-04-24-dora-project-design.md) § Future work — includes `dora merge`, a dashboard date-range filter, deploy-status-based CFR, and a multi-team manifest.

## License

BSD-3-Clause. See [LICENSE](LICENSE).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for the packaged project

Install via uv tool, install and adoption flow for other teams,
metric definitions, label conventions, development setup. Old
README referenced the three-script layout — replaced."
```

---

## Task 20: Final verification

- [ ] **Step 1: Run the full test suite one more time**

Run: `uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 2: `dora --help` works**

Run: `uv run dora --help`
Expected: subcommand list includes `pull`, `report`, `upload`.

- [ ] **Step 3: End-to-end dry run against the fixture**

Run:

```bash
uv run dora report --db tests/fixtures/$(ls tests/fixtures/*.sql | head -1 | xargs -I{} basename {} .sql).db --format json --weeks 52 2>/dev/null || true
# OR build a DB on the fly:
uv run python -c "
import sqlite3
from pathlib import Path
p = Path('/tmp/dora-check.db')
conn = sqlite3.connect(p)
conn.executescript(Path('tests/fixtures/seed.sql').read_text())
conn.commit()
"
uv run dora report --db /tmp/dora-check.db --weeks 52 --format json > /tmp/check-report.json
jq '.metrics[].metric' /tmp/check-report.json
```

Expected: the `jq` output lists all six metric names.

- [ ] **Step 4: Manual dashboard check**

Run: `cd dashboard && python -m http.server 8000`

Open `http://localhost:8000/?url=fixtures/sample.json`. Expected:
- No console errors
- Four charts render
- Summary tiles show values
- Detail tables expand and sort

- [ ] **Step 5: Confirm nothing is left untracked**

Run: `git status`
Expected output: `nothing to commit, working tree clean`.

- [ ] **Step 6: Final commit if anything was missed**

Only if Step 5 showed untracked files. Otherwise skip.

---

## Out of scope — deferred to future work

These are in the spec under Future Work; do not implement:

- `dora merge` subcommand
- Dashboard date-range filter
- `change-failure-rate-deploys` metric
- Multi-report manifest / team switcher
- MTTR pipeline
- PyPI release workflow
