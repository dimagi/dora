"""Tests for src/dora/db.py — schema init and upserts."""

import sqlite3

import pytest

from dora import db


def test_init_db_creates_both_tables(tmp_path):
    path = tmp_path / "empty.db"
    conn = db.init_db(path)
    tables = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "pull_requests" in tables
    assert "deployments"   in tables
    conn.close()


def test_init_db_creates_indexes(tmp_path):
    conn = db.init_db(tmp_path / "a.db")
    idx = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
    }
    assert "idx_pr_merged"   in idx
    assert "idx_dep_created" in idx
    conn.close()


def test_init_db_is_idempotent(tmp_path):
    path = tmp_path / "b.db"
    db.init_db(path).close()
    # Second call must not raise.
    db.init_db(path).close()


def test_upsert_pr_inserts(tmp_path):
    conn = db.init_db(tmp_path / "c.db")
    pr = {
        "number": 1, "title": "t", "author": "alice", "base": "main",
        "opened_at": "2025-10-01T00:00:00Z",
        "merged_at": "2025-10-02T00:00:00Z",
        "first_commit_at": "2025-10-01T00:00:00Z",
        "merge_sha": "abc", "labels": "",
    }
    db.upsert_pr(conn, "acme/api", pr)
    conn.commit()
    row = conn.execute(
        "SELECT number, title, first_commit_at FROM pull_requests"
    ).fetchone()
    assert row == (1, "t", "2025-10-01T00:00:00Z")


def test_upsert_pr_preserves_first_commit_on_update(tmp_path):
    """COALESCE: when an update passes first_commit_at=None, keep the old one."""
    conn = db.init_db(tmp_path / "d.db")
    pr = {
        "number": 1, "title": "v1", "author": "alice", "base": "main",
        "opened_at": "2025-10-01T00:00:00Z",
        "merged_at": "2025-10-02T00:00:00Z",
        "first_commit_at": "2025-10-01T00:00:00Z",
        "merge_sha": "abc", "labels": "",
    }
    db.upsert_pr(conn, "acme/api", pr)
    pr_update = {**pr, "title": "v2", "first_commit_at": None}
    db.upsert_pr(conn, "acme/api", pr_update)
    conn.commit()
    title, fca = conn.execute(
        "SELECT title, first_commit_at FROM pull_requests"
    ).fetchone()
    assert title == "v2"
    assert fca   == "2025-10-01T00:00:00Z"  # preserved


def test_upsert_deployment_preserves_status_on_null_update(tmp_path):
    conn = db.init_db(tmp_path / "e.db")
    d = {
        "deployment_id": 100, "sha": "abc", "environment": "production",
        "created_at": "2025-10-01T00:00:00Z", "status": "success",
    }
    db.upsert_deployment(conn, "acme/api", d)
    db.upsert_deployment(conn, "acme/api", {**d, "status": None})
    conn.commit()
    (status,) = conn.execute("SELECT status FROM deployments").fetchone()
    assert status == "success"


def test_init_db_includes_review_latency_columns(tmp_path):
    """Fresh DB has the four columns added for review-latency."""
    conn = db.init_db(tmp_path / "fresh.db")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(pull_requests)")}
    assert "additions"           in cols
    assert "deletions"           in cols
    assert "changed_files"       in cols
    assert "ready_for_review_at" in cols
    conn.close()


def test_init_db_migrates_legacy_db_in_place(tmp_path):
    """A DB created with the pre-migration schema gets the new columns."""
    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.executescript("""
        CREATE TABLE pull_requests (
            repo TEXT NOT NULL,
            number INTEGER NOT NULL,
            title TEXT,
            author TEXT,
            base TEXT,
            opened_at TEXT NOT NULL,
            merged_at TEXT,
            first_commit_at TEXT,
            merge_sha TEXT,
            labels TEXT,
            PRIMARY KEY (repo, number)
        );
    """)
    legacy.commit()
    legacy.close()

    conn = db.init_db(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(pull_requests)")}
    assert {"additions", "deletions", "changed_files", "ready_for_review_at"} <= cols
    conn.close()


def test_init_db_migration_is_idempotent_on_already_migrated(tmp_path):
    """Calling init_db twice on a migrated DB doesn't error or duplicate."""
    path = tmp_path / "twice.db"
    db.init_db(path).close()
    db.init_db(path).close()  # must not raise
    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(pull_requests)")]
    assert cols.count("changed_files") == 1
    conn.close()
