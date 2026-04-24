"""SQLite schema, connections, upserts for pull_requests + deployments.

Used by both `dora pull` (writes) and `dora report` (reads). Schema is
kept small and stable — the DB is treated as a cache, rebuildable from
the GitHub API at any time.
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS pull_requests (
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

CREATE TABLE IF NOT EXISTS deployments (
    repo TEXT NOT NULL,
    deployment_id INTEGER NOT NULL,
    sha TEXT NOT NULL,
    environment TEXT,
    created_at TEXT NOT NULL,
    status TEXT,
    PRIMARY KEY (repo, deployment_id)
);

CREATE INDEX IF NOT EXISTS idx_pr_merged   ON pull_requests(repo, merged_at);
CREATE INDEX IF NOT EXISTS idx_dep_created ON deployments(repo, created_at);
"""


def init_db(path: str | Path) -> sqlite3.Connection:
    """Open (or create) the SQLite DB and ensure the schema is present."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def upsert_pr(conn: sqlite3.Connection, repo: str, pr: dict) -> None:
    """Insert or update a PR row.

    COALESCE on first_commit_at: a subsequent upsert that omits the field
    (pr["first_commit_at"] is None) preserves the existing value. Lets the
    pull script skip the expensive /pulls/{n}/commits call for PRs it has
    already seen.
    """
    conn.execute(
        """
        INSERT INTO pull_requests
            (repo, number, title, author, base, opened_at, merged_at,
             first_commit_at, merge_sha, labels)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(repo, number) DO UPDATE SET
            title           = excluded.title,
            merged_at       = excluded.merged_at,
            first_commit_at = COALESCE(excluded.first_commit_at, pull_requests.first_commit_at),
            merge_sha       = excluded.merge_sha,
            labels          = excluded.labels
        """,
        (
            repo, pr["number"], pr["title"], pr["author"], pr["base"],
            pr["opened_at"], pr["merged_at"], pr["first_commit_at"],
            pr["merge_sha"], pr["labels"],
        ),
    )


def upsert_deployment(conn: sqlite3.Connection, repo: str, d: dict) -> None:
    """Insert or update a deployment row.

    COALESCE on status: lets the pull script skip the /statuses call for
    deployments that already have a terminal status.
    """
    conn.execute(
        """
        INSERT INTO deployments
            (repo, deployment_id, sha, environment, created_at, status)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(repo, deployment_id) DO UPDATE SET
            status = COALESCE(excluded.status, deployments.status)
        """,
        (
            repo, d["deployment_id"], d["sha"], d["environment"],
            d["created_at"], d["status"],
        ),
    )
