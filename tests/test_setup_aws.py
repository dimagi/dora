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
