# `review-latency` Metric Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `review-latency` metric that measures `merged − COALESCE(ready_for_review, opened)` per PR, bucketed by `changed_files` (XS=1, S=2-3, M=4-9, L+=10+), reported as median (chart) and p90 (table) per repo/week/bucket.

**Architecture:** Schema gets four new nullable columns on `pull_requests` (`additions`, `deletions`, `changed_files`, `ready_for_review_at`). `github.py` extends the unknown-PR branch of `fetch_prs` with two new API calls: `/pulls/{n}` for size, `/issues/{n}/timeline` for the `ready_for_review` event. A new pure function `m_review_latency` lives next to the existing metrics. The dashboard gets a 5th panel rendering one line per bucket via Chart.js.

**Tech Stack:** Python 3.11+, SQLite (sqlite3 stdlib), `requests`, pytest + `requests-mock`, vanilla JS + Chart.js@4 (CDN, no build step).

**Spec:** `docs/superpowers/specs/2026-04-25-review-latency-metric-design.md`

---

## File Structure

| File | Role |
|------|------|
| `src/dora/db.py` | Schema DDL + ALTER-TABLE migration; extend `upsert_pr` to write 4 new columns |
| `src/dora/github.py` | New helper `_fetch_ready_for_review_at()`; extend `fetch_prs` with `/pulls/{n}` + timeline calls |
| `src/dora/metrics.py` | New `BUCKETS` constant; new `m_review_latency()`; register in `METRICS` dict |
| `tests/fixtures/seed.sql` | Schema gains 4 new columns; fixture rows include size + draft data for bucket tests |
| `tests/test_db.py` | Migration idempotency on fresh + legacy DB; `upsert_pr` handles new columns |
| `tests/test_github.py` | New tests: `/pulls/{n}` size fetch, timeline helper (3 cases), known-PR skip |
| `tests/test_metrics.py` | New `test_review_latency_*` tests; update registry assertion |
| `tests/test_cli.py` | New smoke test for `--metric review-latency --format json` |
| `dashboard/index.html` | New `<div class="panel">` for review latency, with canvas + legend |
| `dashboard/app.js` | New `renderReviewLatencyChart()`, wire into `renderForRepo()` |
| `dashboard/fixtures/sample.json` | Add a `review-latency` block so the demo dashboard shows the new chart |
| `README.md` | Add metric to the list; add coverage caveat to known limitations |

`pull.py` does NOT change. Its `db.upsert_pr(conn, repo, pr)` call passes the whole dict; once `fetch_prs` yields the new fields and `upsert_pr` knows about them, the rest just works. The `known_prs` query keeps its current `first_commit_at IS NOT NULL` predicate — per the spec, we ramp coverage forward, not backwards.

---

## Task 1: Schema migration — add 4 nullable columns

**Files:**
- Modify: `src/dora/db.py`
- Test: `tests/test_db.py`

The migration runs inside `init_db()` and must be idempotent: a fresh DB gets the columns from `CREATE TABLE`; a pre-existing DB gets them from `ALTER TABLE ADD COLUMN`. SQLite has no `ADD COLUMN IF NOT EXISTS`, so we read `PRAGMA table_info(pull_requests)` first.

- [ ] **Step 1: Write the failing test for fresh-DB schema**

Add this test to `tests/test_db.py`:

```python
def test_init_db_includes_review_latency_columns(tmp_path):
    """Fresh DB has the four columns added for review-latency."""
    conn = db.init_db(tmp_path / "fresh.db")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(pull_requests)")}
    assert "additions"           in cols
    assert "deletions"           in cols
    assert "changed_files"       in cols
    assert "ready_for_review_at" in cols
    conn.close()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_db.py::test_init_db_includes_review_latency_columns -v
```
Expected: FAIL — columns don't exist yet.

- [ ] **Step 3: Write the failing test for legacy-DB migration**

Add this test to `tests/test_db.py`. It builds the OLD schema by hand, then calls `init_db` and asserts the columns appear (i.e., ALTER ran).

```python
def test_init_db_migrates_legacy_db_in_place(tmp_path):
    """A DB created with the pre-migration schema gets the new columns."""
    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.executescript("""
        CREATE TABLE pull_requests (
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
    """)
    legacy.commit()
    legacy.close()

    conn = db.init_db(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(pull_requests)")}
    assert {"additions", "deletions", "changed_files", "ready_for_review_at"} <= cols
    conn.close()


def test_init_db_migration_is_idempotent_on_already_migrated(tmp_path):
    """Calling init_db twice on a migrated DB doesn't error or duplicate."""
    path = tmp_path / "twice.db"
    db.init_db(path).close()
    db.init_db(path).close()  # must not raise
    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(pull_requests)")]
    assert cols.count("changed_files") == 1
    conn.close()
```

- [ ] **Step 4: Run all three new tests to confirm they fail**

```bash
uv run pytest tests/test_db.py -v -k "review_latency_columns or legacy_db_in_place or already_migrated"
```
Expected: 3 FAIL.

- [ ] **Step 5: Update `SCHEMA` and add migration to `src/dora/db.py`**

Replace the `SCHEMA` constant and `init_db` function:

```python
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
    additions INTEGER,
    deletions INTEGER,
    changed_files INTEGER,
    ready_for_review_at TEXT,
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

# Columns added after the initial release. SQLite has no
# ADD COLUMN IF NOT EXISTS, so we check PRAGMA table_info first.
_PR_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("additions",           "INTEGER"),
    ("deletions",           "INTEGER"),
    ("changed_files",       "INTEGER"),
    ("ready_for_review_at", "TEXT"),
)


def _migrate_pr_table(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(pull_requests)")}
    for name, type_ in _PR_MIGRATIONS:
        if name not in existing:
            conn.execute(f"ALTER TABLE pull_requests ADD COLUMN {name} {type_}")


def init_db(path: str | Path) -> sqlite3.Connection:
    """Open (or create) the SQLite DB and ensure the schema is present."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    _migrate_pr_table(conn)
    return conn
```

- [ ] **Step 6: Run the three migration tests to confirm they pass**

```bash
uv run pytest tests/test_db.py -v -k "review_latency_columns or legacy_db_in_place or already_migrated"
```
Expected: 3 PASS.

- [ ] **Step 7: Run the full db test module to catch regressions**

```bash
uv run pytest tests/test_db.py -v
```
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/dora/db.py tests/test_db.py
git commit -m "feat(db): add review-latency columns + ALTER migration"
```

---

## Task 2: Extend `upsert_pr` to write the new columns

**Files:**
- Modify: `src/dora/db.py`
- Test: `tests/test_db.py`

`upsert_pr` reads four new keys from the PR dict and writes them with `COALESCE` so a known-PR upsert (passing `None`) preserves the stored value — same pattern as `first_commit_at` today.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_upsert_pr_writes_size_and_draft_columns(tmp_path):
    conn = db.init_db(tmp_path / "size.db")
    pr = {
        "number": 1, "title": "t", "author": "alice", "base": "main",
        "opened_at": "2025-10-01T00:00:00Z",
        "merged_at": "2025-10-02T00:00:00Z",
        "first_commit_at": "2025-10-01T00:00:00Z",
        "merge_sha": "abc", "labels": "",
        "additions": 50, "deletions": 10, "changed_files": 4,
        "ready_for_review_at": "2025-10-01T12:00:00Z",
    }
    db.upsert_pr(conn, "acme/api", pr)
    conn.commit()
    row = conn.execute(
        "SELECT additions, deletions, changed_files, ready_for_review_at "
        "FROM pull_requests"
    ).fetchone()
    assert row == (50, 10, 4, "2025-10-01T12:00:00Z")


def test_upsert_pr_preserves_size_on_null_update(tmp_path):
    """COALESCE: passing None for size fields preserves stored values."""
    conn = db.init_db(tmp_path / "preserve.db")
    pr = {
        "number": 1, "title": "v1", "author": "a", "base": "main",
        "opened_at": "2025-10-01T00:00:00Z",
        "merged_at": "2025-10-02T00:00:00Z",
        "first_commit_at": "2025-10-01T00:00:00Z",
        "merge_sha": "abc", "labels": "",
        "additions": 50, "deletions": 10, "changed_files": 4,
        "ready_for_review_at": "2025-10-01T12:00:00Z",
    }
    db.upsert_pr(conn, "acme/api", pr)
    update = {**pr, "title": "v2",
              "additions": None, "deletions": None,
              "changed_files": None, "ready_for_review_at": None}
    db.upsert_pr(conn, "acme/api", update)
    conn.commit()
    title, adds, dels, files, rfra = conn.execute(
        "SELECT title, additions, deletions, changed_files, ready_for_review_at "
        "FROM pull_requests"
    ).fetchone()
    assert title == "v2"
    assert adds  == 50
    assert dels  == 10
    assert files == 4
    assert rfra  == "2025-10-01T12:00:00Z"
```

- [ ] **Step 2: Run to confirm it fails**

```bash
uv run pytest tests/test_db.py::test_upsert_pr_writes_size_and_draft_columns tests/test_db.py::test_upsert_pr_preserves_size_on_null_update -v
```
Expected: FAIL — `KeyError` on the new dict keys, since `upsert_pr` doesn't read them yet.

- [ ] **Step 3: Update `upsert_pr` in `src/dora/db.py`**

Replace the existing `upsert_pr` function:

```python
def upsert_pr(conn: sqlite3.Connection, repo: str, pr: dict) -> None:
    """Insert or update a PR row.

    COALESCE on first_commit_at, additions, deletions, changed_files, and
    ready_for_review_at: a subsequent upsert that omits these (passes None)
    preserves the existing value. Lets the pull script skip the expensive
    per-PR API calls for PRs it has already seen.
    """
    conn.execute(
        """
        INSERT INTO pull_requests
            (repo, number, title, author, base, opened_at, merged_at,
             first_commit_at, merge_sha, labels,
             additions, deletions, changed_files, ready_for_review_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(repo, number) DO UPDATE SET
            title               = excluded.title,
            merged_at           = excluded.merged_at,
            first_commit_at     = COALESCE(excluded.first_commit_at,     pull_requests.first_commit_at),
            merge_sha           = excluded.merge_sha,
            labels              = excluded.labels,
            additions           = COALESCE(excluded.additions,           pull_requests.additions),
            deletions           = COALESCE(excluded.deletions,           pull_requests.deletions),
            changed_files       = COALESCE(excluded.changed_files,       pull_requests.changed_files),
            ready_for_review_at = COALESCE(excluded.ready_for_review_at, pull_requests.ready_for_review_at)
        """,
        (
            repo, pr["number"], pr["title"], pr["author"], pr["base"],
            pr["opened_at"], pr["merged_at"], pr["first_commit_at"],
            pr["merge_sha"], pr["labels"],
            pr["additions"], pr["deletions"], pr["changed_files"],
            pr["ready_for_review_at"],
        ),
    )
```

- [ ] **Step 4: Update existing tests in `tests/test_db.py` to include new keys**

The existing `test_upsert_pr_inserts` and `test_upsert_pr_preserves_first_commit_on_update` tests build PR dicts that no longer have all required keys. Add the four new keys (set to `None` is fine — the assertions don't read them):

In `test_upsert_pr_inserts`, change the `pr` dict to:

```python
    pr = {
        "number": 1, "title": "t", "author": "alice", "base": "main",
        "opened_at": "2025-10-01T00:00:00Z",
        "merged_at": "2025-10-02T00:00:00Z",
        "first_commit_at": "2025-10-01T00:00:00Z",
        "merge_sha": "abc", "labels": "",
        "additions": None, "deletions": None,
        "changed_files": None, "ready_for_review_at": None,
    }
```

In `test_upsert_pr_preserves_first_commit_on_update`, do the same to its `pr` dict.

- [ ] **Step 5: Run all db tests**

```bash
uv run pytest tests/test_db.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/dora/db.py tests/test_db.py
git commit -m "feat(db): upsert_pr writes new size + draft columns"
```

---

## Task 3: Update fixture seed.sql with size + draft data

**Files:**
- Modify: `tests/fixtures/seed.sql`

The seed needs two things: (a) the new schema with 4 columns, (b) realistic values on enough PRs to populate all four buckets in the existing W41/W42/W43 timeline. We also add **one PR with `ready_for_review_at` later than `opened_at`** to exercise the COALESCE in the metric formula.

- [ ] **Step 1: Replace `tests/fixtures/seed.sql` with the updated content**

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
--
-- review-latency values (merged_at - COALESCE(ready_for_review_at, opened_at) in hours):
--   PR 1: changed_files=1  → bucket XS, 34h
--   PR 2: changed_files=3  → bucket S,  44h  (ready_for_review_at = opened+10h, draft case)
--   PR 3: changed_files=7  → bucket M,  30h
--   PR 4: changed_files=1  → bucket XS, 5h
--   PR 5: changed_files=25 → bucket L+, 15h
--   PR 6: changed_files=2  → bucket S,  1h
--   PR 7: changed_files=NULL → excluded from metric

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
    additions INTEGER,
    deletions INTEGER,
    changed_files INTEGER,
    ready_for_review_at TEXT,
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
     'sha1', '',
     30, 5, 1, NULL),
    ('acme/api', 2, 'PR 2', 'bob',   'main',
     '2025-10-14T00:00:00Z', '2025-10-15T20:00:00Z', '2025-10-15T00:00:00Z',
     'sha2', 'caused-incident',
     120, 40, 3, '2025-10-14T10:00:00Z'),
    ('acme/api', 3, 'PR 3', 'carol', 'main',
     '2025-10-15T00:00:00Z', '2025-10-16T06:00:00Z', '2025-10-15T00:00:00Z',
     'sha3', '',
     200, 80, 7, NULL);

-- W42: acme/api deployments (1 success, 1 failure)
INSERT INTO deployments VALUES
    ('acme/api', 100, 'sha1', 'production', '2025-10-14T11:00:00Z', 'success'),
    ('acme/api', 101, 'sha2', 'production', '2025-10-15T21:00:00Z', 'failure');

-- W43: acme/api, 2 merged PRs
INSERT INTO pull_requests VALUES
    ('acme/api', 4, 'PR 4', 'alice', 'main',
     '2025-10-20T00:00:00Z', '2025-10-20T05:00:00Z', '2025-10-20T00:00:00Z',
     'sha4', '',
     15, 2, 1, NULL),
    ('acme/api', 5, 'PR 5', 'dave',  'main',
     '2025-10-21T00:00:00Z', '2025-10-21T15:00:00Z', '2025-10-21T00:00:00Z',
     'sha5', '',
     900, 200, 25, NULL);

-- W43: acme/api deployment (inactive = auto-superseded)
INSERT INTO deployments VALUES
    ('acme/api', 102, 'sha4', 'production', '2025-10-20T06:00:00Z', 'inactive');

-- W43: acme/web, 1 merged PR (hotfix)
INSERT INTO pull_requests VALUES
    ('acme/web', 6, 'PR 6 hotfix', 'alice', 'main',
     '2025-10-22T00:00:00Z', '2025-10-22T01:00:00Z', '2025-10-22T00:00:00Z',
     'sha6', 'hotfix',
     20, 5, 2, NULL);

-- W44: acme/api, 1 merged PR without first_commit_at (lead-time excluded)
-- Also no changed_files → review-latency excluded.
INSERT INTO pull_requests VALUES
    ('acme/api', 7, 'PR 7', 'alice', 'main',
     '2025-10-27T00:00:00Z', '2025-10-28T00:00:00Z', NULL,
     'sha7', '',
     NULL, NULL, NULL, NULL);
```

- [ ] **Step 2: Run all metric tests to confirm existing fixtures still work**

```bash
uv run pytest tests/test_metrics.py -v
```
Expected: all PASS (existing tests don't touch the new columns).

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/seed.sql
git commit -m "test(fixtures): add size + draft data to seed.sql"
```

---

## Task 4: Implement `m_review_latency` metric

**Files:**
- Modify: `src/dora/metrics.py`
- Test: `tests/test_metrics.py`

Bucketing happens in Python (consistent with `m_lead_time`'s aggregation pattern). The function fetches `(repo, week, changed_files, review_window_hours)` rows, assigns each row to a bucket, then computes median + p90 per `(repo, week, bucket)`.

The fixture data, by bucket:

| Bucket | PRs | Per-PR review window (h) |
|--------|-----|---------------------------|
| W41 acme/api XS | PR 1 | 34h |
| W41 acme/api S  | PR 2 | 44h (uses ready_for_review_at, not opened_at) |
| W41 acme/api M  | PR 3 | 30h |
| W42 acme/api XS | PR 4 | 5h |
| W42 acme/api L+ | PR 5 | 15h |
| W42 acme/web S  | PR 6 | 1h |

Single-PR buckets have median = p90 = the only value.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_metrics.py`:

```python
def test_review_latency_buckets_and_window(fixture_conn):
    headers, rows = metrics.m_review_latency(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]

    # PR 1: opened 2025-10-13T00, merged 2025-10-14T10 → 34h, changed_files=1 (XS)
    xs_w41 = next(r for r in out
                  if r["repo"] == "acme/api" and r["week"] == "2025-W41"
                  and r["bucket"] == "XS")
    assert xs_w41["n_prs"]    == 1
    assert xs_w41["median_h"] == 34.0

    # PR 2: ready_for_review_at 2025-10-14T10, merged 2025-10-15T20 → 34h
    # NOT opened→merged (44h). Confirms COALESCE picks ready_for_review_at.
    s_w41 = next(r for r in out
                 if r["repo"] == "acme/api" and r["week"] == "2025-W41"
                 and r["bucket"] == "S")
    assert s_w41["median_h"] == 34.0

    # PR 5: changed_files=25 → L+
    lplus_w42 = next(r for r in out
                     if r["repo"] == "acme/api" and r["week"] == "2025-W42"
                     and r["bucket"] == "L+")
    assert lplus_w42["n_prs"]    == 1
    assert lplus_w42["median_h"] == 15.0


def test_review_latency_excludes_null_changed_files(fixture_conn):
    """PR 7 has changed_files=NULL — must not appear in any bucket."""
    headers, rows = metrics.m_review_latency(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    assert not any(r["repo"] == "acme/api" and r["week"] == "2025-W43" for r in out)


def test_review_latency_headers(fixture_conn):
    """Lock the output schema so the dashboard renderer is stable."""
    headers, _ = metrics.m_review_latency(fixture_conn, SINCE)
    assert headers == ["repo", "week", "bucket", "n_prs", "median_h", "p90_h"]


def test_metrics_registry_has_review_latency():
    assert "review-latency" in metrics.METRICS
```

Also update the existing registry test:

```python
def test_metrics_registry_has_all():
    assert set(metrics.METRICS) == {
        "deploy-freq-prs",
        "deploy-freq",
        "lead-time",
        "change-failure-rate",
        "change-failure-prs",
        "hotfixes",
        "summary",
        "review-latency",
    }
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_metrics.py -v -k "review_latency or registry_has_all"
```
Expected: 4 FAIL.

- [ ] **Step 3: Implement the metric in `src/dora/metrics.py`**

Add this constant near the top of `metrics.py` (next to the existing `FAILURE_LABELS` / `SUCCESS_DEPLOY_STATUSES`):

```python
# Review-latency size buckets, by `changed_files`.
# (label, lower_inclusive, upper_inclusive_or_None_for_open)
BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("XS", 1, 1),
    ("S",  2, 3),
    ("M",  4, 9),
    ("L+", 10, None),
)


def _assign_bucket(changed_files: int | None) -> str | None:
    """Return the bucket label for a given file count, or None if unbucketable."""
    if changed_files is None or changed_files < 1:
        return None
    for label, lo, hi in BUCKETS:
        if changed_files >= lo and (hi is None or changed_files <= hi):
            return label
    return None
```

Add this function after `m_summary` (and before `m_hotfixes` is fine; placement is your call):

```python
def m_review_latency(conn: sqlite3.Connection, since: str):
    """Weekly review latency in hours, bucketed by changed_files.

    review_window = merged_at − COALESCE(ready_for_review_at, opened_at)

    Buckets: XS=1, S=2-3, M=4-9, L+=10+ files. PRs with NULL changed_files
    are excluded (legacy DB rows from before the schema migration).

    Aggregation in Python because SQLite has no PERCENTILE_CONT; p90 is
    nearest-rank (fine for small weekly samples). Same shape as m_lead_time.
    """
    cur = conn.execute(
        """
        SELECT repo,
               strftime('%Y-W%W', merged_at) AS week,
               changed_files,
               (julianday(merged_at)
                - julianday(COALESCE(ready_for_review_at, opened_at))) * 24.0 AS hours
        FROM pull_requests
        WHERE merged_at     IS NOT NULL
          AND changed_files IS NOT NULL
          AND merged_at >= ?
        """,
        (since,),
    )
    buckets: dict[tuple[str, str, str], list[float]] = {}
    for repo, week, files, hours in cur:
        bucket = _assign_bucket(files)
        if bucket is None or hours is None or hours < 0:
            continue
        buckets.setdefault((repo, week, bucket), []).append(hours)

    bucket_order = {label: i for i, (label, _, _) in enumerate(BUCKETS)}
    rows = []
    for (repo, week, bucket), vals in sorted(
        buckets.items(),
        key=lambda kv: (kv[0][0], kv[0][1], bucket_order[kv[0][2]]),
    ):
        vals.sort()
        median = statistics.median(vals)
        p90    = vals[min(len(vals) - 1, int(len(vals) * 0.9))]
        rows.append((repo, week, bucket, len(vals),
                     round(median, 1), round(p90, 1)))
    return ["repo", "week", "bucket", "n_prs", "median_h", "p90_h"], rows
```

Finally, register the metric in the `METRICS` dict at the bottom of `metrics.py`:

```python
    "review-latency": (
        m_review_latency,
        "Weekly review latency in hours (merged − ready_for_review_at | opened_at), bucketed by changed_files (XS=1, S=2-3, M=4-9, L+=10+)",
    ),
```

- [ ] **Step 4: Run the new metric tests**

```bash
uv run pytest tests/test_metrics.py -v -k "review_latency or registry_has_all"
```
Expected: all PASS.

- [ ] **Step 5: Run the full metrics test module**

```bash
uv run pytest tests/test_metrics.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/dora/metrics.py tests/test_metrics.py
git commit -m "feat(metrics): add review-latency, bucketed by changed_files"
```

---

## Task 5: GitHub timeline helper for `ready_for_review_at`

**Files:**
- Modify: `src/dora/github.py`
- Test: `tests/test_github.py`

A small helper that walks `/repos/{repo}/issues/{number}/timeline` in chronological order and returns the timestamp of the first `event: "ready_for_review"`, or `None` if there isn't one. Pagination follow happens for free via the existing `gh()` paginator. Unknown event types are skipped, so the loop tolerates whatever GitHub adds in the future.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_github.py`:

```python
def test_fetch_ready_for_review_at_first_page(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/issues/1/timeline",
        json=[
            {"event": "labeled",            "created_at": "2025-10-10T00:00:00Z"},
            {"event": "ready_for_review",   "created_at": "2025-10-10T05:00:00Z"},
            {"event": "reviewed",           "created_at": "2025-10-10T08:00:00Z"},
        ],
    )
    session = requests.Session()
    out = github._fetch_ready_for_review_at(session, "x/y", 1)
    assert out == "2025-10-10T05:00:00Z"


def test_fetch_ready_for_review_at_no_event(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/issues/2/timeline",
        json=[
            {"event": "labeled",  "created_at": "2025-10-10T00:00:00Z"},
            {"event": "reviewed", "created_at": "2025-10-10T08:00:00Z"},
        ],
    )
    session = requests.Session()
    out = github._fetch_ready_for_review_at(session, "x/y", 2)
    assert out is None


def test_fetch_ready_for_review_at_paginates(requests_mock):
    """Event lives on page 2 — the paginator must follow Link rel=next."""
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/issues/3/timeline",
        json=[{"event": "labeled", "created_at": "2025-10-10T00:00:00Z"}],
        headers={"Link": f'<{base}/repos/x/y/issues/3/timeline?page=2>; rel="next"'},
    )
    requests_mock.get(
        f"{base}/repos/x/y/issues/3/timeline?page=2",
        json=[{"event": "ready_for_review", "created_at": "2025-10-11T03:00:00Z"}],
    )
    session = requests.Session()
    out = github._fetch_ready_for_review_at(session, "x/y", 3)
    assert out == "2025-10-11T03:00:00Z"
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_github.py -v -k "fetch_ready_for_review_at"
```
Expected: 3 FAIL — function doesn't exist.

- [ ] **Step 3: Implement the helper**

Add to `src/dora/github.py` (between `iso_to_dt` and `fetch_prs` is the natural spot):

```python
def _fetch_ready_for_review_at(
    session: requests.Session,
    repo: str,
    number: int,
) -> str | None:
    """Return the timestamp of the first `ready_for_review` event, or None.

    A PR that was never a draft has no `ready_for_review` event in its
    timeline; we return None and let the metric COALESCE down to opened_at.
    A PR toggled draft → ready → draft → ready returns the FIRST ready
    event (most conservative — longest review window).
    """
    for ev in gh(session, f"/repos/{repo}/issues/{number}/timeline"):
        if ev.get("event") == "ready_for_review":
            return ev.get("created_at")
    return None
```

- [ ] **Step 4: Run to confirm pass**

```bash
uv run pytest tests/test_github.py -v -k "fetch_ready_for_review_at"
```
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dora/github.py tests/test_github.py
git commit -m "feat(github): add _fetch_ready_for_review_at helper"
```

---

## Task 6: Wire size + timeline calls into `fetch_prs`

**Files:**
- Modify: `src/dora/github.py`
- Test: `tests/test_github.py`

For unknown PRs only, `fetch_prs` now makes two new calls in addition to the existing `/commits` call:

1. `GET /repos/{r}/pulls/{n}` for `additions`, `deletions`, `changed_files`.
2. `GET /repos/{r}/issues/{n}/timeline` via `_fetch_ready_for_review_at`.

The yielded dict gains four new keys. For known PRs, all four are `None` — `upsert_pr`'s COALESCE preserves the stored values.

- [ ] **Step 1: Write the failing test (unknown PR — full new payload)**

Add to `tests/test_github.py`:

```python
def test_fetch_prs_unknown_pr_includes_size_and_draft(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/pulls",
        json=[{
            "number": 1, "title": "t", "user": {"login": "a"},
            "base": {"ref": "main"}, "labels": [],
            "created_at": "2025-10-10T00:00:00Z",
            "updated_at": "2025-10-10T00:00:00Z",
            "merged_at":  "2025-10-10T00:00:00Z",
            "merge_commit_sha": "s1",
        }],
    )
    requests_mock.get(
        f"{base}/repos/x/y/pulls/1/commits",
        json=[{"commit": {"author": {"date": "2025-10-09T00:00:00Z"}}}],
    )
    requests_mock.get(
        f"{base}/repos/x/y/pulls/1",
        json={"additions": 100, "deletions": 30, "changed_files": 7},
    )
    requests_mock.get(
        f"{base}/repos/x/y/issues/1/timeline",
        json=[{"event": "ready_for_review", "created_at": "2025-10-09T12:00:00Z"}],
    )

    session = requests.Session()
    since = github.iso_to_dt("2025-10-01T00:00:00+00:00")
    out = list(github.fetch_prs(session, "x/y", since, "main", known_prs=set()))
    assert len(out) == 1
    pr = out[0]
    assert pr["additions"]           == 100
    assert pr["deletions"]           == 30
    assert pr["changed_files"]       == 7
    assert pr["ready_for_review_at"] == "2025-10-09T12:00:00Z"
```

- [ ] **Step 2: Write the failing test (known PR — all four are None)**

Replace the existing `test_fetch_prs_skips_commits_for_known` to also assert the new fields are None (the existing assertion stays — just extend it):

```python
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
    # If the implementation tried /commits, /pulls/1, or /issues/1/timeline,
    # requests-mock would 404.
    session = requests.Session()
    since = github.iso_to_dt("2025-10-01T00:00:00+00:00")
    out = list(github.fetch_prs(session, "x/y", since, "main", known_prs={1}))
    assert out[0]["first_commit_at"]     is None
    assert out[0]["additions"]           is None
    assert out[0]["deletions"]           is None
    assert out[0]["changed_files"]       is None
    assert out[0]["ready_for_review_at"] is None
    assert out[0]["labels"] == "L1"
```

Also update the existing `test_fetch_prs_filters_to_merged_within_window` test to include the new endpoints and assert the new fields. Replace its body with:

```python
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
    requests_mock.get(
        f"{base}/repos/x/y/pulls/1",
        json={"additions": 5, "deletions": 0, "changed_files": 1},
    )
    requests_mock.get(
        f"{base}/repos/x/y/issues/1/timeline",
        json=[],  # never a draft
    )

    session = requests.Session()
    since = github.iso_to_dt("2025-10-01T00:00:00+00:00")
    out = list(github.fetch_prs(session, "x/y", since, "main", known_prs=set()))
    assert [p["number"] for p in out] == [1]
    assert out[0]["first_commit_at"]     == "2025-10-09T00:00:00Z"
    assert out[0]["changed_files"]       == 1
    assert out[0]["ready_for_review_at"] is None
```

- [ ] **Step 3: Run to confirm failure**

```bash
uv run pytest tests/test_github.py -v -k "fetch_prs"
```
Expected: FAILs (yielded dict doesn't have the new keys).

- [ ] **Step 4: Update `fetch_prs` in `src/dora/github.py`**

Replace the whole `fetch_prs` function:

```python
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

    PRs whose number is in `known_prs` skip the per-PR API calls
    (commits + pull detail + timeline) — the four corresponding fields
    stay None so the upsert COALESCE preserves the stored values.
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
            first_commit_at     = None  # cached
            additions           = None
            deletions           = None
            changed_files       = None
            ready_for_review_at = None
        else:
            commits = list(
                gh(session, f"/repos/{repo}/pulls/{pr['number']}/commits", {"per_page": 100})
            )
            first_commit_at = (
                commits[0]["commit"]["author"]["date"] if commits else pr["created_at"]
            )

            detail = session.get(
                f"{API}/repos/{repo}/pulls/{pr['number']}", timeout=30
            )
            detail.raise_for_status()
            d = detail.json()
            additions     = d.get("additions")
            deletions     = d.get("deletions")
            changed_files = d.get("changed_files")

            ready_for_review_at = _fetch_ready_for_review_at(
                session, repo, pr["number"]
            )

        yield {
            "number":              pr["number"],
            "title":               pr["title"],
            "author":              (pr.get("user") or {}).get("login"),
            "base":                pr["base"]["ref"],
            "opened_at":           pr["created_at"],
            "merged_at":           pr["merged_at"],
            "first_commit_at":     first_commit_at,
            "merge_sha":           pr["merge_commit_sha"],
            "labels":              ",".join(l["name"] for l in pr.get("labels") or []),
            "additions":           additions,
            "deletions":           deletions,
            "changed_files":       changed_files,
            "ready_for_review_at": ready_for_review_at,
        }
```

The `/pulls/{n}` detail call uses `session.get` directly (not the `gh()` paginator) because it returns a single object, not a list. Rate-limit handling there is left to GitHub's standard 403 → raise behavior; the paginator's retry loop only applies to list endpoints. This matches existing patterns in the file.

- [ ] **Step 5: Run to confirm pass**

```bash
uv run pytest tests/test_github.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/dora/github.py tests/test_github.py
git commit -m "feat(github): fetch size + ready_for_review_at on unknown PRs"
```

---

## Task 7: CLI smoke test for `--metric review-latency`

**Files:**
- Test: `tests/test_cli.py`

Verify the new metric is end-to-end reachable through the CLI: report runs, exits 0, JSON parses, and the `review-latency` block exists in the output.

- [ ] **Step 1: Write the smoke test**

Open `tests/test_cli.py` and append the test below. If `json`, `subprocess`, or `sys` aren't already imported at the top of the file (most likely they are — check the file head), add the missing ones at module level. Per project convention, **imports go at module level**, not inside the function body.

```python
def test_cli_report_review_latency_json(fixture_db):
    """`dora report --metric review-latency --format json` exits 0
    and produces a parseable payload with the new metric."""
    result = subprocess.run(
        [sys.executable, "-m", "dora", "report",
         "--db", str(fixture_db),
         "--metric", "review-latency",
         "--format", "json",
         "--weeks", "12"],
        capture_output=True, text=True, check=True,
    )
    payload = json.loads(result.stdout)
    metric_names = [m["metric"] for m in payload["metrics"]]
    assert "review-latency" in metric_names
    rl = next(m for m in payload["metrics"] if m["metric"] == "review-latency")
    assert all(r["bucket"] in {"XS", "S", "M", "L+"} for r in rl["data"])
```

- [ ] **Step 2: Run to confirm pass**

```bash
uv run pytest tests/test_cli.py::test_cli_report_review_latency_json -v
```
Expected: PASS (everything underneath is already implemented).

- [ ] **Step 3: Commit**

```bash
git add tests/test_cli.py
git commit -m "test(cli): smoke test for review-latency metric"
```

---

## Task 8: Dashboard markup — add review-latency panel

**Files:**
- Modify: `dashboard/index.html`

Add a new `<div class="panel">` after the closing `</div>` of the existing `.row-2` (containing CFR + hotfixes). It sits as a sibling inside `<section class="panels">`. The existing `.panels` grid is `grid-template-columns: 1fr` — the panel takes a full row, same width as the Deploy frequency and Lead time panels above the `.row-2`.

- [ ] **Step 1: Locate the insertion point**

Find these lines in `dashboard/index.html` (around line 132-134):

```html
          <div class="panel">
            <div class="panel-head">
              <p class="panel-title">Recent hotfixes</p>
              <p class="panel-sub">Investigate which preceding PR caused each incident</p>
            </div>
            <div id="hotfixes"></div>
          </div>
        </div>     <!-- closes .row-2 -->
      </section>   <!-- closes .panels -->
```

- [ ] **Step 2: Insert the new panel between `</div>` (closing .row-2) and `</section>` (closing .panels)**

Replace this fragment:

```html
        </div>
      </section>
```

with:

```html
        </div>

        <div class="panel">
          <div class="panel-head">
            <p class="panel-title">Review latency</p>
            <p class="panel-sub" title="merged − ready_for_review_at (or opened_at, if never drafted). Buckets: XS=1, S=2-3, M=4-9, L+=10+ files.">Median hours waiting for review, by PR size</p>
          </div>
          <div class="legend">
            <span><i style="background: #2d5a8e;"></i>XS (1 file)</span>
            <span><i style="background: #4a86c7;"></i>S (2–3)</span>
            <span><i style="background: #b4450a;"></i>M (4–9)</span>
            <span><i style="background: #6a3d9a;"></i>L+ (10+)</span>
          </div>
          <div class="chart-wrap tall">
            <canvas id="reviewLatencyChart" role="img" aria-label="Weekly review latency by PR size">
              Review latency by PR size
            </canvas>
          </div>
        </div>
      </section>
```

The four colors are explicit hex values rather than CSS variables — there are only three `--chart-*` variables today (primary/secondary/accent), and adding a 4th + the JS plumbing to read it is more change than the panel needs. A future "promote to CSS variables" refactor is fine, parked.

- [ ] **Step 3: Verify locally**

```bash
cd dashboard && python -m http.server 8000 &
SERVER_PID=$!
sleep 1
curl -s http://localhost:8000/ | grep -c "reviewLatencyChart"
kill $SERVER_PID
```
Expected: `1` (the canvas exists; clicking through to a browser will show "No data yet" because the renderer doesn't exist yet).

- [ ] **Step 4: Commit**

```bash
git add dashboard/index.html
git commit -m "feat(dashboard): add review-latency panel markup"
```

---

## Task 9: Dashboard renderer — `renderReviewLatencyChart`

**Files:**
- Modify: `dashboard/app.js`

The renderer takes the `review-latency` rows for the current repo, groups by bucket, builds one Chart.js dataset per bucket, and renders a 4-line chart. Missing buckets in a given week show as gaps (Chart.js does this automatically when the data array contains `null`).

- [ ] **Step 1: Add the renderer function**

After the existing `renderCFRChart` function (around line 410), add:

```javascript
const REVIEW_LATENCY_BUCKETS = [
  { label: "XS", color: "#2d5a8e" },
  { label: "S",  color: "#4a86c7" },
  { label: "M",  color: "#b4450a" },
  { label: "L+", color: "#6a3d9a" },
];

function renderReviewLatencyChart(rows) {
  const ctx = document.getElementById("reviewLatencyChart");
  if (!rows.length) {
    ctx.parentElement.innerHTML = '<div class="empty">No data yet</div>';
    return;
  }

  // One sorted week axis spanning all buckets.
  const weeks = [...new Set(rows.map(r => r.week))].sort();

  // Per-bucket map: week → median_h.
  const byBucket = {};
  for (const r of rows) {
    (byBucket[r.bucket] = byBucket[r.bucket] || {})[r.week] = r.median_h;
  }

  const datasets = REVIEW_LATENCY_BUCKETS.map(({ label, color }) => ({
    label,
    data: weeks.map(w => {
      const v = byBucket[label]?.[w];
      return v == null ? null : v;
    }),
    borderColor: color,
    backgroundColor: color,
    borderWidth: 2,
    pointRadius: 2.5,
    tension: 0.25,
    spanGaps: false,
  }));

  const opts = baseOpts();
  opts.scales.y.title = {
    display: true,
    text: "hours",
    color: readVar("--chart-tick"),
    font: { size: 11 },
  };

  charts.push(new Chart(ctx, {
    type: "line",
    data: { labels: weeks, datasets },
    options: opts,
  }));
}
```

- [ ] **Step 2: Wire the renderer into `renderForRepo`**

In `renderForRepo` (around line 212-231), add a line that pulls the new metric and another that calls the renderer. Replace the function body's tail with:

```javascript
function renderForRepo(metrics, repo) {
  resetCharts();

  const freqPrs       = inRange(filterByRepo(metrics["deploy-freq-prs"]     || [], repo));
  const freqDeploys   = inRange(filterByRepo(metrics["deploy-freq"]         || [], repo));
  const leadTime      = inRange(filterByRepo(metrics["lead-time"]           || [], repo));
  const cfr           = inRange(filterByRepo(metrics["change-failure-rate"] || [], repo));
  const cfrPrs        = inRange(filterByRepo(metrics["change-failure-prs"]  || [], repo));
  const hotfixes      = inRangeHotfixes(filterByRepo(metrics["hotfixes"]    || [], repo));
  const reviewLatency = inRange(filterByRepo(metrics["review-latency"]      || [], repo));
  // summary is not date-filterable; renderKPIs uses it only as a fallback,
  // and that fallback is dropped when filtering is active (see renderKPIs).
  const summary       = filterByRepo(metrics["summary"] || [], repo);

  renderKPIs(summary, freqPrs, freqDeploys, leadTime, cfr);
  renderFreqChart(freqPrs, freqDeploys);
  renderLeadChart(leadTime);
  renderCFRChart(cfr);
  renderCfrPrs(cfrPrs);
  renderHotfixes(hotfixes);
  renderReviewLatencyChart(reviewLatency);
}
```

- [ ] **Step 3: Manual smoke (no automated test, per spec)**

```bash
cd dashboard && python -m http.server 8000
```

Open `http://localhost:8000/?url=fixtures/sample.json`. Expect: review-latency panel still shows "No data yet" because the fixture hasn't been updated yet (next task). Check the browser console for JS errors — there should be none.

Stop the server (Ctrl-C).

- [ ] **Step 4: Commit**

```bash
git add dashboard/app.js
git commit -m "feat(dashboard): add review-latency renderer"
```

---

## Task 10: Update `dashboard/fixtures/sample.json` with review-latency data

**Files:**
- Modify: `dashboard/fixtures/sample.json`

Append a `review-latency` metric block to the existing `metrics` array so the demo dashboard shows the new chart with realistic-looking data. Use the existing repo names already in the fixture so the repo dropdown filters correctly.

- [ ] **Step 1: Inspect the existing fixture to find the repo names + week range**

```bash
grep -m 1 '"repo"' dashboard/fixtures/sample.json
grep -m 1 '"week"' dashboard/fixtures/sample.json
```

Expected: a repo like `"acme/example"` and a week like `"2025-Wxx"`. Capture both for use below — the synthetic data must match.

- [ ] **Step 2: Append a review-latency block to `metrics`**

Open `dashboard/fixtures/sample.json` and find the `summary` metric block (around the end of the `metrics` array). Insert a new metric block immediately before it. The exact rows don't matter — they're demo data — but they should: (a) span at least 6 weeks, (b) cover all four buckets, (c) show realistic medians (single-digit XS, double-digit M, larger L+ to make the chart spread visible). Use the actual repo name and week labels from Step 1.

Example block (substitute the repo + weeks to match your fixture):

```json
    {
      "metric": "review-latency",
      "description": "Weekly review latency in hours (merged − ready_for_review_at | opened_at), bucketed by changed_files (XS=1, S=2-3, M=4-9, L+=10+)",
      "data": [
        {"repo": "acme/example", "week": "2025-W36", "bucket": "XS", "n_prs": 4, "median_h": 3.2,  "p90_h": 8.0},
        {"repo": "acme/example", "week": "2025-W36", "bucket": "S",  "n_prs": 3, "median_h": 6.5,  "p90_h": 14.0},
        {"repo": "acme/example", "week": "2025-W36", "bucket": "M",  "n_prs": 2, "median_h": 18.0, "p90_h": 28.0},
        {"repo": "acme/example", "week": "2025-W36", "bucket": "L+", "n_prs": 1, "median_h": 42.0, "p90_h": 42.0},
        {"repo": "acme/example", "week": "2025-W37", "bucket": "XS", "n_prs": 5, "median_h": 2.8,  "p90_h": 6.5},
        {"repo": "acme/example", "week": "2025-W37", "bucket": "S",  "n_prs": 4, "median_h": 7.1,  "p90_h": 16.0},
        {"repo": "acme/example", "week": "2025-W37", "bucket": "M",  "n_prs": 3, "median_h": 22.0, "p90_h": 35.0},
        {"repo": "acme/example", "week": "2025-W37", "bucket": "L+", "n_prs": 2, "median_h": 38.0, "p90_h": 50.0},
        {"repo": "acme/example", "week": "2025-W38", "bucket": "XS", "n_prs": 6, "median_h": 4.1,  "p90_h": 9.0},
        {"repo": "acme/example", "week": "2025-W38", "bucket": "S",  "n_prs": 4, "median_h": 8.0,  "p90_h": 18.0},
        {"repo": "acme/example", "week": "2025-W38", "bucket": "M",  "n_prs": 2, "median_h": 16.0, "p90_h": 24.0},
        {"repo": "acme/example", "week": "2025-W38", "bucket": "L+", "n_prs": 1, "median_h": 55.0, "p90_h": 55.0},
        {"repo": "acme/example", "week": "2025-W39", "bucket": "XS", "n_prs": 3, "median_h": 3.5,  "p90_h": 7.0},
        {"repo": "acme/example", "week": "2025-W39", "bucket": "S",  "n_prs": 5, "median_h": 6.2,  "p90_h": 13.0},
        {"repo": "acme/example", "week": "2025-W39", "bucket": "M",  "n_prs": 3, "median_h": 20.0, "p90_h": 32.0},
        {"repo": "acme/example", "week": "2025-W39", "bucket": "L+", "n_prs": 2, "median_h": 48.0, "p90_h": 60.0},
        {"repo": "acme/example", "week": "2025-W40", "bucket": "XS", "n_prs": 4, "median_h": 2.5,  "p90_h": 5.0},
        {"repo": "acme/example", "week": "2025-W40", "bucket": "S",  "n_prs": 3, "median_h": 5.8,  "p90_h": 12.0},
        {"repo": "acme/example", "week": "2025-W40", "bucket": "M",  "n_prs": 4, "median_h": 19.0, "p90_h": 30.0},
        {"repo": "acme/example", "week": "2025-W40", "bucket": "L+", "n_prs": 1, "median_h": 36.0, "p90_h": 36.0},
        {"repo": "acme/example", "week": "2025-W41", "bucket": "XS", "n_prs": 5, "median_h": 3.0,  "p90_h": 6.0},
        {"repo": "acme/example", "week": "2025-W41", "bucket": "S",  "n_prs": 4, "median_h": 7.5,  "p90_h": 15.0},
        {"repo": "acme/example", "week": "2025-W41", "bucket": "M",  "n_prs": 3, "median_h": 17.0, "p90_h": 26.0},
        {"repo": "acme/example", "week": "2025-W41", "bucket": "L+", "n_prs": 2, "median_h": 44.0, "p90_h": 58.0}
      ]
    },
```

Make sure the comma after the closing `]}` is correct: it goes BEFORE the next metric block (`summary`). If you're inserting before the last entry of the array, omit the trailing comma.

- [ ] **Step 2.5: Validate the JSON parses**

```bash
python -c "import json; json.load(open('dashboard/fixtures/sample.json'))"
```
Expected: no output (clean parse). If it fails, fix syntax errors before continuing.

- [ ] **Step 3: Verify the dashboard renders the new panel**

```bash
cd dashboard && python -m http.server 8000
```

Open `http://localhost:8000/?url=fixtures/sample.json`. Expect:
- A "Review latency" panel renders below the CFR/hotfixes row
- 4 colored lines (XS, S, M, L+)
- L+ noticeably higher than XS, S/M between
- No JS errors in browser console
- The detail table at the bottom (if expanded) includes the review-latency rows with `p90_h`

Stop the server.

- [ ] **Step 4: Commit**

```bash
git add dashboard/fixtures/sample.json
git commit -m "feat(dashboard): add review-latency demo data to sample fixture"
```

---

## Task 11: README updates

**Files:**
- Modify: `README.md`

Two small additions: list the new metric, and call out the coverage caveat.

- [ ] **Step 1: Find the metrics list in the README**

```bash
grep -n "lead-time\|change-failure-rate\|deploy-freq" README.md | head -10
```

This locates the table or bullet list of metrics (the README uses one or the other; match the existing format).

- [ ] **Step 2: Add `review-latency` to the metrics list**

If the metrics live in a table, add a row:

```markdown
| `review-latency` | Median hours waiting for review (`merged − ready_for_review \| opened`), bucketed by `changed_files` (XS=1, S=2-3, M=4-9, L+=10+). Tail (p90) is in the JSON output. |
```

If they live in a bullet list, add an item:

```markdown
- `review-latency` — Median hours waiting for review (`merged − ready_for_review_at` or `opened_at` if never drafted), bucketed by `changed_files`: **XS** (1 file), **S** (2–3), **M** (4–9), **L+** (10+). The chart shows median; the JSON output also includes p90.
```

- [ ] **Step 3: Add the coverage caveat to the limitations / known-issues section**

Find the section (search for "limitation" or "known"):

```bash
grep -n -i "known\|limitation\|caveat" README.md
```

Add:

```markdown
- **`review-latency` coverage ramps forward.** When you upgrade `dora` and run the next `dora pull`, only newly-merged PRs get their size + draft data fetched. Previously-cached PRs keep their `changed_files` and `ready_for_review_at` columns `NULL` and are excluded from the metric. Coverage fills in over time as new PRs merge. A `--rebuild` flag for forced backfill is parked as future work.
```

- [ ] **Step 4: Verify the README still renders cleanly**

```bash
# Optional: render with grip or any local markdown viewer if available
markdown README.md > /dev/null 2>&1 || true
# At minimum, eyeball it
head -80 README.md
```

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document review-latency metric + coverage caveat"
```

---

## Task 12: End-to-end smoke + final commit

**Files:** none modified — verification only.

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest
```
Expected: all PASS, no skips beyond what was skipping before.

- [ ] **Step 2: Sanity-check the CLI directly against the fixture**

```bash
uv run python -m dora report --db tests/fixtures/none.db --metric review-latency --format table 2>&1 || true
# That'll likely error (no DB). The point is to confirm the metric is registered.
uv run python -c "from dora.metrics import METRICS; print('review-latency' in METRICS)"
```
Expected: `True`.

- [ ] **Step 3: Verify dashboard one more time**

```bash
cd dashboard && python -m http.server 8000
```

Browser: `http://localhost:8000/?url=fixtures/sample.json`. Confirm:
- All 5 panels render
- Repo dropdown filters all charts (if multi-repo)
- Date range slider re-renders all charts
- Review latency panel shows 4 distinct lines with reasonable values
- p90 is preserved in the JSON payload (the dashboard chart renders median; p90 lives in the report.json output for anyone who wants the tail)

Stop the server.

- [ ] **Step 4: Confirm clean working tree**

```bash
git status
git log --oneline -15
```
Expected: working tree clean, ~11 new commits forming a clean implementation history.

---

## Summary

11 implementation tasks + 1 verification task. All tasks follow TDD where applicable. Frequent commits keep history clean and bisectable. No backwards-compatibility shims; the schema migration handles legacy DBs in place. All four new columns are nullable to allow forward-only coverage ramp, per the spec.
