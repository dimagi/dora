"""Tests for src/dora/metrics.py against the seeded fixture DB.

Fixture layout (from tests/fixtures/seed.sql): three activity weeks
across two repos. SQLite's strftime('%W') is zero-indexed (days before
the first Monday of the year are W00), so the dates in the fixture map
to these week labels:
  2025-10-13..2025-10-16  → 2025-W41  (3 PRs on acme/api)
  2025-10-20..2025-10-22  → 2025-W42  (2 PRs acme/api, 1 PR acme/web)
  2025-10-28              → 2025-W43  (1 PR acme/api)
"""

import pytest

from dora import metrics

SINCE = "2025-10-01T00:00:00+00:00"


def _row_dict(headers, row):
    return dict(zip(headers, row))


def test_deploy_freq_prs_counts_merged_per_week(fixture_conn):
    headers, rows = metrics.m_deploy_freq_prs(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    assert {"repo": "acme/api", "week": "2025-W41", "deploys": 3} in out
    assert {"repo": "acme/api", "week": "2025-W42", "deploys": 2} in out
    assert {"repo": "acme/api", "week": "2025-W43", "deploys": 1} in out
    assert {"repo": "acme/web", "week": "2025-W42", "deploys": 1} in out


def test_deploy_freq_counts_success_and_inactive(fixture_conn):
    headers, rows = metrics.m_deploy_freq(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    # W41: one success (id 100), one failure (id 101) → count 1
    # W42: one inactive (id 102)                       → count 1
    # (failure is excluded)
    assert {"repo": "acme/api", "environment": "production",
            "week": "2025-W41", "deploys": 1} in out
    assert {"repo": "acme/api", "environment": "production",
            "week": "2025-W42", "deploys": 1} in out
    assert not any(r["deploys"] == 2 for r in out)


def test_lead_time_excludes_rows_with_null_first_commit(fixture_conn):
    headers, rows = metrics.m_lead_time(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    # W41 acme/api: PRs 1,2,3 with lead times 10h, 20h, 30h
    w41 = next(r for r in out if r["repo"] == "acme/api" and r["week"] == "2025-W41")
    assert w41["prs"]      == 3
    assert w41["median_h"] == 20.0
    # W43 acme/api has only PR 7 (NULL first_commit_at) → no W43 row
    assert not any(r["repo"] == "acme/api" and r["week"] == "2025-W43" for r in out)


def test_change_failure_rate_uses_labels(fixture_conn):
    headers, rows = metrics.m_change_failure_rate(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    # W41: 3 merged, 1 caused-incident → 33.3%
    w41 = next(r for r in out if r["repo"] == "acme/api" and r["week"] == "2025-W41")
    assert w41["deploys"]     == 3
    assert w41["failures"]    == 1
    assert w41["failure_pct"] == 33.3
    # W42 acme/web: 1 merged, labelled `hotfix` (NOT counted)
    w42_web = next(r for r in out if r["repo"] == "acme/web" and r["week"] == "2025-W42")
    assert w42_web["failures"] == 0


def test_summary_rollup(fixture_conn):
    headers, rows = metrics.m_summary(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    # acme/api: 6 merged PRs over 3 weeks, 1 caused-incident → CFR 16.7%
    api = next(r for r in out if r["repo"] == "acme/api")
    assert api["prs"] == 6
    assert api["cfr"] == "16.7%"
    # acme/web: 1 merged PR, 0 caused-incident → CFR 0.0%
    web = next(r for r in out if r["repo"] == "acme/web")
    assert web["prs"] == 1
    assert web["cfr"] == "0.0%"


def test_change_failure_prs_lists_caused_incident(fixture_conn):
    headers, rows = metrics.m_change_failure_prs(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    # PR 2 is the only caused-incident in the fixture (acme/api, W41).
    assert len(out) == 1
    assert out[0]["pr"]     == 2
    assert out[0]["repo"]   == "acme/api"
    assert out[0]["week"]   == "2025-W41"
    assert out[0]["author"] == "bob"
    assert out[0]["merged"] == "2025-10-15"


def test_hotfixes_lists_hotfix_with_preceding(fixture_conn):
    headers, rows = metrics.m_hotfixes(fixture_conn, SINCE)
    # Expect PR 6 (acme/web, hotfix) as a 'hotfix' row, followed by up to 3
    # 'preceded-by' rows (acme/web has none before it → 1 row total).
    hotfix_rows = [r for r in rows if r[2] == "hotfix"]
    assert len(hotfix_rows) == 1
    assert hotfix_rows[0][1] == "#6"


@pytest.mark.parametrize("n,expected", [
    (None, None),
    (-1,   None),
    (0,    None),
    (1,    "XS"),
    (2,    "S"),
    (3,    "S"),
    (4,    "M"),
    (9,    "M"),
    (10,   "L+"),
    (1000, "L+"),
])
def test_assign_bucket_boundaries(n, expected):
    """Lock the bucket boundary table — protects against off-by-one regressions."""
    assert metrics._assign_bucket(n) == expected


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


def test_large_prs_counts_changed_files_gte_10(fixture_conn):
    """Weekly count of merged PRs with changed_files >= 10."""
    headers, rows = metrics.m_large_prs(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    # Only PR 5 (acme/api, W42, changed_files=25) qualifies in the fixture.
    assert {"repo": "acme/api", "week": "2025-W42", "large_prs": 1} in out
    # No other repo/week should appear.
    assert len(out) == 1


def test_large_prs_excludes_null_changed_files(fixture_conn):
    """PR 7 has changed_files=NULL — must be excluded."""
    headers, rows = metrics.m_large_prs(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    assert not any(r["repo"] == "acme/api" and r["week"] == "2025-W43" for r in out)


def test_large_prs_headers(fixture_conn):
    headers, _ = metrics.m_large_prs(fixture_conn, SINCE)
    assert headers == ["repo", "week", "large_prs"]


def test_hotfix_count_aggregates_hotfix_label(fixture_conn):
    """Weekly count of merged PRs labelled `hotfix` (same source as m_hotfixes)."""
    headers, rows = metrics.m_hotfix_count(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    # PR 6 (acme/web, hotfix, merged 2025-10-22 → W42) is the only hotfix.
    assert {"repo": "acme/web", "week": "2025-W42", "hotfix_count": 1} in out
    assert len(out) == 1


def test_hotfix_count_excludes_unmerged(fixture_conn):
    """A hotfix-labelled but unmerged PR must not be counted."""
    fixture_conn.execute(
        """
        INSERT INTO pull_requests
          (repo, number, title, author, base, opened_at, merged_at,
           first_commit_at, merge_sha, labels,
           additions, deletions, changed_files, ready_for_review_at)
        VALUES
          ('acme/api', 99, 'Open hotfix', 'eve', 'main',
           '2025-10-15T00:00:00Z', NULL, NULL, NULL, 'hotfix',
           NULL, NULL, NULL, NULL)
        """
    )
    headers, rows = metrics.m_hotfix_count(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    assert not any(r["repo"] == "acme/api" for r in out)


def test_hotfix_count_headers(fixture_conn):
    headers, _ = metrics.m_hotfix_count(fixture_conn, SINCE)
    assert headers == ["repo", "week", "hotfix_count"]


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
        "large-prs",
        "hotfix-count",
    }
