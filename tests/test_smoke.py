"""Smoke tests — package import + CLI help path."""

import subprocess
import sys

import dora
from dora import cli


def test_package_version():
    assert dora.__version__ == "0.1.0"


def test_cli_main_is_callable():
    assert callable(cli.main)


def test_help_does_not_crash():
    """`dora --help` exits 0 and prints the top-level help."""
    result = subprocess.run(
        [sys.executable, "-m", "dora", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "dora" in result.stdout
    assert "report" in result.stdout
