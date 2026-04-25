"""Tests for src/dora/report.py — runner and formatters."""

import json
from io import StringIO

from dora import report


def test_run_report_returns_all_metrics_by_default(fixture_conn):
    out = report.run_report(fixture_conn, since="2025-10-01T00:00:00+00:00")
    names = {r["metric"] for r in out}
    assert names == {
        "deploy-freq-prs", "deploy-freq", "lead-time",
        "change-failure-rate", "change-failure-prs", "hotfixes", "summary",
        "review-latency",
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
