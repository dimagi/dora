"""Smoke tests — confirm the package imports and CLI entry point exists."""

import subprocess
import sys

import dora
from dora import cli


def test_package_version():
    assert dora.__version__ == "0.1.0"


def test_cli_main_is_callable():
    assert callable(cli.main)


def test_cli_skeleton_exits_nonzero():
    """The skeleton should exit non-zero (no subcommands wired yet)."""
    rc = cli.main([])
    assert rc != 0


def test_cli_module_runnable_as_script():
    """`python -m dora.cli` should run and exit with the same non-zero code."""
    result = subprocess.run(
        [sys.executable, "-m", "dora.cli"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
