"""Shared pytest fixtures."""

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
