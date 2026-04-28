"""Tests for src/dora/pull.py — orchestration + source dispatch."""

import sqlite3
from unittest.mock import patch

from dora import pull


def _release_dict(rid: int, published_at: str) -> dict:
    return {
        "deployment_id": rid,
        "sha":           "main",
        "environment":   "production",
        "created_at":    published_at,
        "status":        "success",
    }


def test_run_pull_releases_writes_rows_via_fetch_releases(tmp_path, monkeypatch):
    """source='releases' calls fetch_releases (not fetch_deployments) and
    persists the synthesized rows into the deployments table."""
    db_path = tmp_path / "dora.db"

    # Stub out token + session so no real network is touched.
    monkeypatch.setattr(pull.github, "get_token", lambda: "fake")
    monkeypatch.setattr(pull.github, "make_session", lambda token: object())

    fake_releases = [
        _release_dict(100, "2025-10-10T00:00:00Z"),
        _release_dict(200, "2025-10-12T00:00:00Z"),
    ]
    fetch_releases_mock = patch.object(
        pull.github, "fetch_releases", return_value=iter(fake_releases)
    )
    fetch_deployments_mock = patch.object(
        pull.github, "fetch_deployments",
        side_effect=AssertionError("must not be called for source=releases"),
    )

    with fetch_releases_mock, fetch_deployments_mock:
        pull.run_pull(
            repos=["x/y"],
            since="2025-10-01",
            db_path=str(db_path),
            base="main",
            environment="production",
            source="releases",
            skip_prs=True,
            skip_deployments=False,
        )

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT deployment_id, environment, status FROM deployments "
        "WHERE repo = ? ORDER BY deployment_id",
        ("x/y",),
    ).fetchall()
    conn.close()
    assert rows == [(100, "production", "success"), (200, "production", "success")]


def test_run_pull_deployments_default_calls_fetch_deployments(tmp_path, monkeypatch):
    """Default source preserves pre-existing behavior (calls fetch_deployments)."""
    db_path = tmp_path / "dora.db"
    monkeypatch.setattr(pull.github, "get_token", lambda: "fake")
    monkeypatch.setattr(pull.github, "make_session", lambda token: object())

    fake_deployments = [{
        "deployment_id": 7,
        "sha":           "abc",
        "environment":   "production",
        "created_at":    "2025-10-10T00:00:00Z",
        "status":        "success",
    }]
    fetch_deployments_mock = patch.object(
        pull.github, "fetch_deployments", return_value=iter(fake_deployments)
    )
    fetch_releases_mock = patch.object(
        pull.github, "fetch_releases",
        side_effect=AssertionError("must not be called for source=deployments"),
    )

    with fetch_deployments_mock, fetch_releases_mock:
        pull.run_pull(
            repos=["x/y"],
            since="2025-10-01",
            db_path=str(db_path),
            base="main",
            environment="production",
            source="deployments",
            skip_prs=True,
            skip_deployments=False,
        )

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT deployment_id FROM deployments WHERE repo = ?", ("x/y",),
    ).fetchall()
    conn.close()
    assert rows == [(7,)]
