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
    assert {"repo": "acme/api", "week": "2025-W42", "deploys": 3} in out
    # Was 2 before the bot fixture row; now 3 (PR 4, PR 5, + bot PR 8, all merged in W42).
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
    # acme/api: 7 merged PRs over 3 weeks (PR 1-5, 7 + bot PR 8).
    api = next(r for r in out if r["repo"] == "acme/api")
    assert api["prs"] == 7
    assert api["cfr"] == "14.3%"
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

    # PR 5 (changed_files=25) + bot PR 8 (changed_files=15) → both L+ in W42.
    # Bot filtering is not yet applied (Task 2); n_prs=2 until then.
    lplus_w42 = next(r for r in out
                     if r["repo"] == "acme/api" and r["week"] == "2025-W42"
                     and r["bucket"] == "L+")
    assert lplus_w42["n_prs"]    == 2
    assert lplus_w42["median_h"] == 7.8


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
    # PR 5 (changed_files=25) + bot PR 8 (changed_files=15) both qualify in W42.
    # Bot filtering is not yet applied (Task 2); count=2 until then.
    assert {"repo": "acme/api", "week": "2025-W42", "large_prs": 2} in out
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
        "weekend-merges",
    }


def test_default_exclude_bots_covers_every_metric():
    """DEFAULT_EXCLUDE_BOTS must have an entry for every key in METRICS."""
    assert set(metrics.DEFAULT_EXCLUDE_BOTS) == set(metrics.METRICS)


def test_author_filter_returns_empty_when_not_excluding():
    assert metrics._author_filter(False) == ""


def test_author_filter_emits_sql_fragment_when_excluding():
    assert metrics._author_filter(True) == "AND author NOT LIKE '%[bot]'"


def _insert_pr(conn, **kw):
    """Helper: insert a single PR row using the seed schema column order."""
    cols = ["repo", "number", "title", "author", "base",
            "opened_at", "merged_at", "first_commit_at", "merge_sha",
            "labels", "additions", "deletions", "changed_files",
            "ready_for_review_at"]
    placeholders = ",".join("?" * len(cols))
    conn.execute(
        f"INSERT INTO pull_requests ({','.join(cols)}) VALUES ({placeholders})",
        tuple(kw.get(c) for c in cols),
    )


def test_weekend_merges_keeps_sat_sun_only(fixture_conn):
    """Only PRs whose merged_at falls on Sat (strftime %w='6') or Sun ('0')."""
    # 2025-10-18 is a Saturday, 2025-10-19 is a Sunday, 2025-10-20 is a Monday.
    _insert_pr(fixture_conn, repo="acme/api", number=20, title="sat merge",
               author="eve", base="main",
               opened_at="2025-10-17T00:00:00Z",
               merged_at="2025-10-18T12:00:00Z",
               first_commit_at="2025-10-17T00:00:00Z",
               merge_sha="shaSat", labels="",
               additions=10, deletions=2, changed_files=2,
               ready_for_review_at=None)
    _insert_pr(fixture_conn, repo="acme/api", number=21, title="sun merge",
               author="frank", base="main",
               opened_at="2025-10-18T00:00:00Z",
               merged_at="2025-10-19T18:00:00Z",
               first_commit_at="2025-10-18T00:00:00Z",
               merge_sha="shaSun", labels="",
               additions=5, deletions=1, changed_files=1,
               ready_for_review_at=None)
    _insert_pr(fixture_conn, repo="acme/api", number=22, title="mon merge",
               author="eve", base="main",
               opened_at="2025-10-19T00:00:00Z",
               merged_at="2025-10-20T09:00:00Z",
               first_commit_at="2025-10-19T00:00:00Z",
               merge_sha="shaMon", labels="",
               additions=5, deletions=1, changed_files=1,
               ready_for_review_at=None)

    headers, rows = metrics.m_weekend_merges(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    prs = sorted(r["pr"] for r in out)
    # PR 8 (bot, Sun 2025-10-26) also appears; bot filtering not yet applied (Task 2).
    assert prs == [8, 20, 21]                          # Mon excluded; bot included
    by_pr = {r["pr"]: r for r in out}
    assert by_pr[20]["dow"] == "Sat"
    assert by_pr[21]["dow"] == "Sun"
    assert by_pr[20]["author"] == "eve"
    assert by_pr[21]["author"] == "frank"
    assert by_pr[20]["merged"] == "2025-10-18"
    assert by_pr[20]["week"]   == "2025-W41"           # Sat falls in W41
    assert by_pr[21]["week"]   == "2025-W41"


def test_weekend_merges_excludes_unmerged(fixture_conn):
    _insert_pr(fixture_conn, repo="acme/api", number=30, title="open weekend",
               author="eve", base="main",
               opened_at="2025-10-17T00:00:00Z",
               merged_at=None, first_commit_at=None, merge_sha=None,
               labels="", additions=None, deletions=None,
               changed_files=None, ready_for_review_at=None)
    _, rows = metrics.m_weekend_merges(fixture_conn, SINCE)
    assert not any(r[2] == 30 for r in rows)           # column 2 = pr (number)


def test_weekend_merges_headers(fixture_conn):
    headers, _ = metrics.m_weekend_merges(fixture_conn, SINCE)
    assert headers == ["repo", "week", "pr", "author", "title", "merged", "dow"]


def test_deploy_freq_prs_counts_bot_merges_by_default(fixture_conn):
    """deploy-freq-prs INCLUDES bots by default (per the registry)."""
    headers, rows = metrics.m_deploy_freq_prs(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    # PR 8 (dependabot, W42) bumps acme/api W42 to 3.
    assert {"repo": "acme/api", "week": "2025-W42", "deploys": 3} in out


def test_deploy_freq_prs_drops_bots_when_exclude_bots_set(fixture_conn):
    headers, rows = metrics.m_deploy_freq_prs(fixture_conn, SINCE, exclude_bots=True)
    out = [_row_dict(headers, r) for r in rows]
    # Bot dropped → W42 acme/api back to 2 (PRs 1, 2, 3 only).
    assert {"repo": "acme/api", "week": "2025-W42", "deploys": 2} in out


def test_lead_time_drops_bots_when_exclude_bots_set(fixture_conn):
    """The bot PR has a 30-minute lead time that would skew the median."""
    headers, rows = metrics.m_lead_time(fixture_conn, SINCE, exclude_bots=True)
    out = [_row_dict(headers, r) for r in rows]
    # W42 (SQLite: 2025-10-20..2025-10-26) has PRs 4 (5h) and 5 (15h).
    # Bot PR 8 (0.5h) is excluded → prs=2, median=(5+15)/2=10h.
    w42 = next(r for r in out if r["repo"] == "acme/api" and r["week"] == "2025-W42")
    assert w42["prs"] == 2
    assert w42["median_h"] == 10.0


def test_lead_time_includes_bots_when_explicitly_included(fixture_conn):
    headers, rows = metrics.m_lead_time(fixture_conn, SINCE, exclude_bots=False)
    out = [_row_dict(headers, r) for r in rows]
    # With the bot PR 8 (0.5h), W42 has PRs 4, 5, 8 → prs=3.
    w42 = next(r for r in out if r["repo"] == "acme/api" and r["week"] == "2025-W42")
    assert w42["prs"] == 3


def test_review_latency_drops_bots_when_exclude_bots_set(fixture_conn):
    headers, rows = metrics.m_review_latency(fixture_conn, SINCE, exclude_bots=True)
    out = [_row_dict(headers, r) for r in rows]
    # PR 8 has changed_files=15 (L+) and lands in W42. Without it the W42 L+ row
    # should have only PR 5 (n_prs=1, median 15h) — the original pre-bot expectation.
    lplus_w42 = next(r for r in out
                     if r["repo"] == "acme/api" and r["week"] == "2025-W42"
                     and r["bucket"] == "L+")
    assert lplus_w42["n_prs"]    == 1
    assert lplus_w42["median_h"] == 15.0


def test_large_prs_drops_bots_when_exclude_bots_set(fixture_conn):
    headers, rows = metrics.m_large_prs(fixture_conn, SINCE, exclude_bots=True)
    out = [_row_dict(headers, r) for r in rows]
    # Without the bot, only PR 5 (W42, changed_files=25) qualifies.
    assert {"repo": "acme/api", "week": "2025-W42", "large_prs": 1} in out
    assert len(out) == 1


def test_large_prs_keeps_bots_when_explicitly_included(fixture_conn):
    headers, rows = metrics.m_large_prs(fixture_conn, SINCE, exclude_bots=False)
    out = [_row_dict(headers, r) for r in rows]
    # PR 5 (W42, 25 files) + PR 8 (W42, 15 files) → W42 count = 2.
    assert {"repo": "acme/api", "week": "2025-W42", "large_prs": 2} in out


def test_weekend_merges_drops_bots_when_exclude_bots_set(fixture_conn):
    """PR 8 merged Sunday; with exclude_bots it must not appear."""
    _, rows = metrics.m_weekend_merges(fixture_conn, SINCE, exclude_bots=True)
    assert not any(r[2] == 8 for r in rows)  # column 2 = pr (number)


def test_weekend_merges_keeps_bots_when_explicitly_included(fixture_conn):
    _, rows = metrics.m_weekend_merges(fixture_conn, SINCE, exclude_bots=False)
    assert any(r[2] == 8 for r in rows)


def test_change_failure_rate_keeps_bots_by_default(fixture_conn):
    """CFR includes bots: a bot-shipped defect is still a defect."""
    headers, rows = metrics.m_change_failure_rate(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    # Bot PR 8 lands in W42 (SQLite: 2025-10-20..2025-10-26) alongside PRs 4,5.
    # W42 acme/api: 3 merged (PRs 4,5 + bot 8), 0 caused-incident → 0.0%
    w42 = next(r for r in out if r["repo"] == "acme/api" and r["week"] == "2025-W42")
    assert w42["deploys"] == 3
    assert w42["failures"] == 0
    assert w42["failure_pct"] == 0.0


def test_change_failure_rate_drops_bots_when_excluded(fixture_conn):
    headers, rows = metrics.m_change_failure_rate(fixture_conn, SINCE, exclude_bots=True)
    out = [_row_dict(headers, r) for r in rows]
    # Bot dropped → W42 denominator = 2 (PRs 4,5); still 0 failures → 0.0%
    w42 = next(r for r in out if r["repo"] == "acme/api" and r["week"] == "2025-W42")
    assert w42["deploys"]     == 2
    assert w42["failures"]    == 0
    assert w42["failure_pct"] == 0.0


def test_hotfix_count_keeps_bots_by_default(fixture_conn):
    """hotfix-count includes bots — only relevant if a bot ever ships a hotfix."""
    fixture_conn.execute("""
        INSERT INTO pull_requests
          (repo, number, title, author, base, opened_at, merged_at,
           first_commit_at, merge_sha, labels,
           additions, deletions, changed_files, ready_for_review_at)
        VALUES
          ('acme/api', 50, 'bot hotfix', 'renovate[bot]', 'main',
           '2025-10-21T00:00:00Z', '2025-10-21T01:00:00Z',
           '2025-10-21T00:00:00Z', 'sha50', 'hotfix',
           5, 1, 1, NULL)
    """)
    headers, rows = metrics.m_hotfix_count(fixture_conn, SINCE)
    out = [_row_dict(headers, r) for r in rows]
    assert {"repo": "acme/api", "week": "2025-W42", "hotfix_count": 1} in out


def test_hotfix_count_drops_bots_when_exclude_bots_set(fixture_conn):
    fixture_conn.execute("""
        INSERT INTO pull_requests
          (repo, number, title, author, base, opened_at, merged_at,
           first_commit_at, merge_sha, labels,
           additions, deletions, changed_files, ready_for_review_at)
        VALUES
          ('acme/api', 50, 'bot hotfix', 'renovate[bot]', 'main',
           '2025-10-21T00:00:00Z', '2025-10-21T01:00:00Z',
           '2025-10-21T00:00:00Z', 'sha50', 'hotfix',
           5, 1, 1, NULL)
    """)
    headers, rows = metrics.m_hotfix_count(fixture_conn, SINCE, exclude_bots=True)
    out = [_row_dict(headers, r) for r in rows]
    assert not any(r["repo"] == "acme/api" and r["week"] == "2025-W42"
                   for r in out)


def test_change_failure_prs_drops_bot_authored_when_exclude_bots_set(fixture_conn):
    """A bot-authored caused-incident PR is filtered when exclude_bots=True."""
    fixture_conn.execute("""
        INSERT INTO pull_requests
          (repo, number, title, author, base, opened_at, merged_at,
           first_commit_at, merge_sha, labels,
           additions, deletions, changed_files, ready_for_review_at)
        VALUES
          ('acme/api', 60, 'bot ship that broke prod', 'dependabot[bot]', 'main',
           '2025-10-15T00:00:00Z', '2025-10-15T01:00:00Z',
           '2025-10-15T00:00:00Z', 'sha60', 'caused-incident',
           5, 1, 1, NULL)
    """)
    # Default: bot caused-incident PR is listed (CFR includes bots).
    _, default_rows = metrics.m_change_failure_prs(fixture_conn, SINCE)
    assert any(r[2] == 60 for r in default_rows)   # column 2 = pr (number)
    # exclude_bots=True: bot caused-incident PR is dropped.
    _, ex_rows = metrics.m_change_failure_prs(fixture_conn, SINCE, exclude_bots=True)
    assert not any(r[2] == 60 for r in ex_rows)
    # The pre-existing human-authored caused-incident PR (PR 2) still shows.
    assert any(r[2] == 2 for r in ex_rows)


def test_hotfixes_preceding_merges_drops_bots_when_exclude_bots_set(fixture_conn):
    """The inner preceding-merges query in m_hotfixes honors exclude_bots.

    Without bot-filter coverage on this inner query, a regression that
    only filtered the outer hotfix query would silently pass.
    """
    # Fixture has PR 6 (acme/web, hotfix, merged 2025-10-22). Insert a
    # bot-authored PR merged just before it so it would normally appear
    # in the "preceded-by" rows of the hotfix.
    fixture_conn.execute("""
        INSERT INTO pull_requests
          (repo, number, title, author, base, opened_at, merged_at,
           first_commit_at, merge_sha, labels,
           additions, deletions, changed_files, ready_for_review_at)
        VALUES
          ('acme/web', 70, 'bot dep bump', 'dependabot[bot]', 'main',
           '2025-10-21T00:00:00Z', '2025-10-21T12:00:00Z',
           '2025-10-21T00:00:00Z', 'sha70', '',
           10, 2, 2, NULL)
    """)
    # Default: bot PR 70 appears as preceded-by for hotfix PR 6.
    _, default_rows = metrics.m_hotfixes(fixture_conn, SINCE)
    assert any(r[1] == "#70" and r[2] == "preceded-by" for r in default_rows)
    # exclude_bots=True: bot PR 70 dropped from preceded-by list.
    _, ex_rows = metrics.m_hotfixes(fixture_conn, SINCE, exclude_bots=True)
    assert not any(r[1] == "#70" for r in ex_rows)
    # The hotfix PR itself still shows under "hotfix" relation.
    assert any(r[1] == "#6" and r[2] == "hotfix" for r in ex_rows)
