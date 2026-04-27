"""Shared pytest fixtures."""

import os
import shutil
import sqlite3
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_db(tmp_path):
    """SQLite DB on disk, seeded from tests/fixtures/seed.sql.

    On-disk (not :memory:) so subprocess CLI tests can open the same file.
    """
    db_path = tmp_path / "dora.db"
    conn = sqlite3.connect(db_path)
    conn.executescript((FIXTURES / "seed.sql").read_text())
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def fixture_conn(fixture_db):
    """Open a connection to the seeded fixture DB."""
    conn = sqlite3.connect(fixture_db)
    yield conn
    conn.close()


@pytest.fixture
def fake_aws(tmp_path, monkeypatch):
    """Stub `aws` CLI on PATH that records its argv and returns canned JSON.

    Use `fake_aws.respond("iam list-open-id-connect-providers", json_str)` to register
    a response. Subcommand match is exact (first two argv tokens). Anything unmatched
    returns empty stdout and exit 0.

    Inspect calls via `fake_aws.calls` — a list of arg lists in invocation order.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "aws_calls.tsv"
    log_file.write_text("")
    responses_dir = tmp_path / "aws_responses"
    responses_dir.mkdir()

    aws_stub = bin_dir / "aws"
    aws_stub.write_text(
        f"""#!/usr/bin/env bash
set -e
# Record argv (TAB-separated, one line per call)
printf '%s\\n' "$(printf '%s\\t' "$@")" >> "{log_file}"

key="$1__$2"
resp_file="{responses_dir}/$key"
if [[ -f "$resp_file.exit" ]]; then
  exit_code=$(cat "$resp_file.exit")
else
  exit_code=0
fi
if [[ -f "$resp_file.out" ]]; then
  cat "$resp_file.out"
fi
exit "$exit_code"
"""
    )
    aws_stub.chmod(0o755)

    # Ensure jq is on PATH (real binary). Don't shadow it.
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    if shutil.which("jq") is None:
        pytest.skip("jq not installed (apt install jq)")

    class FakeAws:
        def respond(self, subcommand: str, stdout: str = "", exit_code: int = 0):
            key = subcommand.replace(" ", "__", 1)
            (responses_dir / f"{key}.out").write_text(stdout)
            (responses_dir / f"{key}.exit").write_text(str(exit_code))

        @property
        def calls(self) -> list[list[str]]:
            text = log_file.read_text()
            return [line.rstrip("\t").split("\t") for line in text.splitlines() if line]

    return FakeAws()
