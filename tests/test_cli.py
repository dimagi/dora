"""CLI smoke tests — parse + dispatch + end-to-end JSON output."""

import json
import subprocess
import sys

import pytest

from dora import cli


def test_no_args_shows_help():
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
