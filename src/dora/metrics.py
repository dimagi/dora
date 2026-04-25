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


def m_change_failure_prs(conn: sqlite3.Connection, since: str):
    """Individual PRs labelled `caused-incident`, with week + PR number.

    Drill-down for change-failure-rate: the rate metric tells you how
    often things go wrong; this metric tells you exactly which PRs.
    Dashboard renders these as clickable links to the GitHub PR pages.
    """
    fail_expr = " OR ".join(f"labels LIKE '%{lab}%'" for lab in FAILURE_LABELS)
    cur = conn.execute(
        f"""
        SELECT repo,
               strftime('%Y-W%W', merged_at) AS week,
               number AS pr,
               author,
               title,
               substr(merged_at, 1, 10) AS merged
        FROM pull_requests
        WHERE merged_at IS NOT NULL
          AND merged_at >= ?
          AND ({fail_expr})
        ORDER BY repo, week DESC, number DESC
        """,
        (since,),
    )
    return [c[0] for c in cur.description], cur.fetchall()


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
        if bucket is None or hours < 0:
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
    "change-failure-prs": (
        m_change_failure_prs,
        "Individual `caused-incident` PRs (drill-down for change-failure-rate)",
    ),
    "hotfixes": (
        m_hotfixes,
        "Recent hotfix PRs with their preceding merges (investigative)",
    ),
    "summary": (
        m_summary,
        "Per-repo roll-up over the whole window",
    ),
    "review-latency": (
        m_review_latency,
        "Weekly review latency in hours (merged − ready_for_review_at | opened_at), bucketed by changed_files (XS=1, S=2-3, M=4-9, L+=10+)",
    ),
}
