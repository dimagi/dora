"""Tests for examples/setup-aws.sh."""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "examples" / "setup-aws.sh"


def test_help_flag_prints_usage_and_exits_zero():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "--repo" in result.stdout
    assert "--bucket" in result.stdout
    assert "--existing-bucket" in result.stdout
    assert "--region" in result.stdout
    assert "--branch" in result.stdout
    assert "--role-name" in result.stdout


import pytest


@pytest.mark.parametrize(
    "argv, expected_substr",
    [
        # missing required
        (["--region", "us-east-1", "--bucket", "b"], "--repo is required"),
        (["--repo", "o/n", "--bucket", "b"], "--region is required"),
        (["--repo", "o/n", "--region", "us-east-1"], "exactly one of --bucket / --existing-bucket"),
        # both bucket flags
        (
            ["--repo", "o/n", "--region", "us-east-1", "--bucket", "b", "--existing-bucket", "c"],
            "exactly one of --bucket / --existing-bucket",
        ),
        # malformed --repo
        (
            ["--repo", "no-slash", "--region", "us-east-1", "--bucket", "b"],
            "--repo must be OWNER/NAME",
        ),
        (
            ["--repo", "a/b/c", "--region", "us-east-1", "--bucket", "b"],
            "--repo must be OWNER/NAME",
        ),
    ],
)
def test_argument_validation(argv, expected_substr):
    result = subprocess.run(
        ["bash", str(SCRIPT), *argv],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert expected_substr in result.stderr
