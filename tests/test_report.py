"""Tests for src/dora/report.py — runner and formatters."""

import json
from io import StringIO

from dora import report
from dora import metrics  # noqa: F401 — used in new tests


def test_run_report_returns_all_metrics_by_default(fixture_conn):
    _, out = report.run_report(fixture_conn, since="2025-10-01T00:00:00+00:00")
    names = {r["metric"] for r in out}
    assert names == {
        "deploy-freq-prs", "deploy-freq", "lead-time",
        "change-failure-rate", "change-failure-prs", "hotfixes", "summary",
        "review-latency",
        "large-prs", "hotfix-count", "weekend-merges",
    }


def test_run_report_filters_by_metric_names(fixture_conn):
    _, out = report.run_report(
        fixture_conn,
        since="2025-10-01T00:00:00+00:00",
        metrics=["lead-time"],
    )
    assert [r["metric"] for r in out] == ["lead-time"]


def test_json_formatter_has_expected_top_level(fixture_conn):
    bot_policy, out = report.run_report(
        fixture_conn,
        since="2025-10-01T00:00:00+00:00",
        metrics=["deploy-freq-prs"],
    )
    buf = StringIO()
    report.print_json(bot_policy, out, "2025-10-01T00:00:00+00:00", buf)
    data = json.loads(buf.getvalue())
    assert data["since"] == "2025-10-01"
    assert isinstance(data["metrics"], list)
    assert data["metrics"][0]["metric"] == "deploy-freq-prs"
    assert all({"repo", "week", "deploys"} <= set(r)
               for r in data["metrics"][0]["data"])


def test_csv_formatter_emits_comment_metadata(fixture_conn):
    bot_policy, out = report.run_report(
        fixture_conn,
        since="2025-10-01T00:00:00+00:00",
        metrics=["deploy-freq-prs"],
    )
    buf = StringIO()
    report.print_csv(bot_policy, out, "2025-10-01T00:00:00+00:00", buf)
    text = buf.getvalue()
    assert "# metric: deploy-freq-prs" in text
    assert "# since: 2025-10-01"       in text
    # Header row is present after the metadata comments.
    assert "repo,week,deploys" in text


def test_table_formatter_emits_header_and_rows(fixture_conn):
    bot_policy, out = report.run_report(
        fixture_conn,
        since="2025-10-01T00:00:00+00:00",
        metrics=["deploy-freq-prs"],
    )
    buf = StringIO()
    report.print_table(bot_policy, out, "2025-10-01T00:00:00+00:00", buf)
    text = buf.getvalue()
    assert "deploy-freq-prs" in text
    assert "repo"            in text
    assert "acme/api"        in text


def test_run_report_default_uses_per_metric_bot_defaults(fixture_conn):
    bot_policy, out = report.run_report(fixture_conn, since="2025-10-01T00:00:00+00:00")
    by_metric = {r["metric"]: r for r in out}
    assert by_metric["deploy-freq-prs"]["exclude_bots"]   is False
    assert by_metric["large-prs"]["exclude_bots"]         is True
    assert by_metric["weekend-merges"]["exclude_bots"]    is True
    assert by_metric["lead-time"]["exclude_bots"]         is True
    # summary is composite — surface as None in default mode.
    assert by_metric["summary"]["exclude_bots"]           is None
    # deploy-freq doesn't read the author column — surface as None.
    assert by_metric["deploy-freq"]["exclude_bots"]       is None
    assert bot_policy == "default"


def test_run_report_force_exclude_overrides_all(fixture_conn):
    bot_policy, out = report.run_report(
        fixture_conn, since="2025-10-01T00:00:00+00:00", exclude_bots=True,
    )
    by_metric = {r["metric"]: r for r in out}
    assert by_metric["deploy-freq-prs"]["exclude_bots"]      is True
    assert by_metric["change-failure-rate"]["exclude_bots"]  is True
    assert by_metric["summary"]["exclude_bots"]              is True
    assert bot_policy == "all-excluded"
    # deploy-freq has no `author` column; the call must succeed under force-True
    # (no TypeError on the kwarg-less dispatch) and surface the user's choice.
    assert by_metric["deploy-freq"]["exclude_bots"] is True
    assert by_metric["deploy-freq"]["headers"] == [
        "repo", "environment", "week", "deploys"
    ]


def test_run_report_force_include_overrides_all(fixture_conn):
    bot_policy, out = report.run_report(
        fixture_conn, since="2025-10-01T00:00:00+00:00", exclude_bots=False,
    )
    by_metric = {r["metric"]: r for r in out}
    assert by_metric["large-prs"]["exclude_bots"]      is False
    assert by_metric["weekend-merges"]["exclude_bots"] is False
    assert by_metric["summary"]["exclude_bots"]        is False
    assert bot_policy == "all-included"
    # Same dispatch sanity-check for the force-False branch.
    assert by_metric["deploy-freq"]["exclude_bots"] is False
    assert by_metric["deploy-freq"]["headers"] == [
        "repo", "environment", "week", "deploys"
    ]


def test_json_formatter_emits_bot_policy_and_per_metric_flag(fixture_conn):
    bot_policy, out = report.run_report(
        fixture_conn, since="2025-10-01T00:00:00+00:00",
        metrics=["deploy-freq-prs"],
    )
    buf = StringIO()
    report.print_json(bot_policy, out, "2025-10-01T00:00:00+00:00", buf)
    payload = json.loads(buf.getvalue())
    assert payload["bot_policy"] == "default"
    assert payload["metrics"][0]["exclude_bots"] is False


def test_json_formatter_bot_policy_reflects_force(fixture_conn):
    bp_excl, out_excl = report.run_report(
        fixture_conn, since="2025-10-01T00:00:00+00:00", exclude_bots=True,
        metrics=["large-prs"],
    )
    buf = StringIO()
    report.print_json(bp_excl, out_excl, "2025-10-01T00:00:00+00:00", buf)
    payload = json.loads(buf.getvalue())
    assert payload["bot_policy"] == "all-excluded"
    assert payload["metrics"][0]["exclude_bots"] is True

    bp_incl, out_incl = report.run_report(
        fixture_conn, since="2025-10-01T00:00:00+00:00", exclude_bots=False,
        metrics=["large-prs"],
    )
    buf2 = StringIO()
    report.print_json(bp_incl, out_incl, "2025-10-01T00:00:00+00:00", buf2)
    assert json.loads(buf2.getvalue())["bot_policy"] == "all-included"
