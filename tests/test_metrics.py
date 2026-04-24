"""Tests for src/dora/metrics.py against the seeded fixture DB.

Fixture layout (from tests/fixtures/seed.sql): three activity weeks
across two repos. SQLite's strftime('%W') is zero-indexed (days before
the first Monday of the year are W00), so the dates in the fixture map
to these week labels:
  2025-10-13..2025-10-16  → 2025-W41  (3 PRs on acme/api)
  2025-10-20..2025-10-22  → 2025-W42  (2 PRs acme/api, 1 PR acme/web)
  2025-10-28              → 2025-W43  (1 PR acme/api)
"""

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
