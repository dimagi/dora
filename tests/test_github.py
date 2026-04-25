"""Tests for src/dora/github.py — auth + paginated fetch + rate limits."""

import subprocess
from unittest.mock import patch

import pytest
import requests

from dora import github


# --- get_token ------------------------------------------------------------

def test_get_token_uses_gh_cli_first():
    completed = subprocess.CompletedProcess(
        args=["gh", "auth", "token"], returncode=0, stdout="ghp_abc\n", stderr=""
    )
    with patch("dora.github.subprocess.run", return_value=completed):
        assert github.get_token() == "ghp_abc"


def test_get_token_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env_token")
    # Force gh lookup to "fail" (FileNotFoundError simulates gh not installed)
    with patch("dora.github.subprocess.run", side_effect=FileNotFoundError):
        assert github.get_token() == "env_token"


def test_get_token_exits_when_nothing_available(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with patch("dora.github.subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(SystemExit):
            github.get_token()


# --- gh() paginator -------------------------------------------------------

def test_gh_yields_items_across_pages(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/pulls",
        json=[{"id": 1}, {"id": 2}],
        headers={"Link": f'<{base}/repos/x/y/pulls?page=2>; rel="next"'},
    )
    requests_mock.get(
        f"{base}/repos/x/y/pulls?page=2",
        json=[{"id": 3}],
    )
    session = requests.Session()
    ids = [it["id"] for it in github.gh(session, "/repos/x/y/pulls")]
    assert ids == [1, 2, 3]


def test_gh_sleeps_and_retries_on_rate_limit(requests_mock, monkeypatch):
    base = "https://api.github.com"
    requests_mock.register_uri(
        "GET", f"{base}/foo",
        [
            {
                "status_code": 403,
                "text": "rate limit exceeded for this request",
                "headers": {"X-RateLimit-Reset": "1000"},
            },
            {"status_code": 200, "json": [{"id": 1}]},
        ],
    )

    # Freeze time so computed sleep is predictable, patch sleep to no-op.
    monkeypatch.setattr("dora.github.time.time",  lambda: 995)
    slept = []
    monkeypatch.setattr("dora.github.time.sleep", lambda s: slept.append(s))

    session = requests.Session()
    items = list(github.gh(session, "/foo"))
    assert items == [{"id": 1}]
    assert slept and slept[0] >= 5


def test_fetch_ready_for_review_at_first_page(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/issues/1/timeline",
        json=[
            {"event": "labeled",            "created_at": "2025-10-10T00:00:00Z"},
            {"event": "ready_for_review",   "created_at": "2025-10-10T05:00:00Z"},
            {"event": "reviewed",           "created_at": "2025-10-10T08:00:00Z"},
        ],
    )
    session = requests.Session()
    out = github._fetch_ready_for_review_at(session, "x/y", 1)
    assert out == "2025-10-10T05:00:00Z"


def test_fetch_ready_for_review_at_no_event(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/issues/2/timeline",
        json=[
            {"event": "labeled",  "created_at": "2025-10-10T00:00:00Z"},
            {"event": "reviewed", "created_at": "2025-10-10T08:00:00Z"},
        ],
    )
    session = requests.Session()
    out = github._fetch_ready_for_review_at(session, "x/y", 2)
    assert out is None


def test_fetch_ready_for_review_at_paginates(requests_mock):
    """Event lives on page 2 — the paginator must follow Link rel=next."""
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/issues/3/timeline",
        json=[{"event": "labeled", "created_at": "2025-10-10T00:00:00Z"}],
        headers={"Link": f'<{base}/repos/x/y/issues/3/timeline?page=2>; rel="next"'},
    )
    requests_mock.get(
        f"{base}/repos/x/y/issues/3/timeline?page=2",
        json=[{"event": "ready_for_review", "created_at": "2025-10-11T03:00:00Z"}],
    )
    session = requests.Session()
    out = github._fetch_ready_for_review_at(session, "x/y", 3)
    assert out == "2025-10-11T03:00:00Z"


# --- fetch_prs ------------------------------------------------------------

def test_fetch_prs_filters_to_merged_within_window(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/pulls",
        json=[
            {   # in window, merged → kept
                "number": 1, "title": "t1", "user": {"login": "a"},
                "base": {"ref": "main"}, "labels": [],
                "created_at": "2025-10-10T00:00:00Z",
                "updated_at": "2025-10-10T00:00:00Z",
                "merged_at":  "2025-10-10T00:00:00Z",
                "merge_commit_sha": "s1",
            },
            {   # in window, NOT merged → skipped
                "number": 2, "title": "t2", "user": {"login": "a"},
                "base": {"ref": "main"}, "labels": [],
                "created_at": "2025-10-10T00:00:00Z",
                "updated_at": "2025-10-10T00:00:00Z",
                "merged_at": None,
                "merge_commit_sha": None,
            },
            {   # before window → paginator should stop
                "number": 3, "title": "t3", "user": {"login": "a"},
                "base": {"ref": "main"}, "labels": [],
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "merged_at":  "2024-01-01T00:00:00Z",
                "merge_commit_sha": "s3",
            },
        ],
    )
    requests_mock.get(
        f"{base}/repos/x/y/pulls/1/commits",
        json=[{"commit": {"author": {"date": "2025-10-09T00:00:00Z"}}}],
    )
    requests_mock.get(
        f"{base}/repos/x/y/pulls/1",
        json={"additions": 5, "deletions": 0, "changed_files": 1},
    )
    requests_mock.get(
        f"{base}/repos/x/y/issues/1/timeline",
        json=[],  # never a draft
    )

    session = requests.Session()
    since = github.iso_to_dt("2025-10-01T00:00:00+00:00")
    out = list(github.fetch_prs(session, "x/y", since, "main", known_prs=set()))
    assert [p["number"] for p in out] == [1]
    assert out[0]["first_commit_at"]     == "2025-10-09T00:00:00Z"
    assert out[0]["changed_files"]       == 1
    assert out[0]["ready_for_review_at"] is None


def test_fetch_prs_skips_commits_for_known(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/pulls",
        json=[{
            "number": 1, "title": "t", "user": {"login": "a"},
            "base": {"ref": "main"}, "labels": [{"name": "L1"}],
            "created_at": "2025-10-10T00:00:00Z",
            "updated_at": "2025-10-10T00:00:00Z",
            "merged_at":  "2025-10-10T00:00:00Z",
            "merge_commit_sha": "s1",
        }],
    )
    # If the implementation tried /commits, /pulls/1, or /issues/1/timeline,
    # requests-mock would 404.
    session = requests.Session()
    since = github.iso_to_dt("2025-10-01T00:00:00+00:00")
    out = list(github.fetch_prs(session, "x/y", since, "main", known_prs={1}))
    assert out[0]["first_commit_at"]     is None
    assert out[0]["additions"]           is None
    assert out[0]["deletions"]           is None
    assert out[0]["changed_files"]       is None
    assert out[0]["ready_for_review_at"] is None
    assert out[0]["labels"] == "L1"


def test_fetch_prs_unknown_pr_includes_size_and_draft(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/pulls",
        json=[{
            "number": 1, "title": "t", "user": {"login": "a"},
            "base": {"ref": "main"}, "labels": [],
            "created_at": "2025-10-10T00:00:00Z",
            "updated_at": "2025-10-10T00:00:00Z",
            "merged_at":  "2025-10-10T00:00:00Z",
            "merge_commit_sha": "s1",
        }],
    )
    requests_mock.get(
        f"{base}/repos/x/y/pulls/1/commits",
        json=[{"commit": {"author": {"date": "2025-10-09T00:00:00Z"}}}],
    )
    requests_mock.get(
        f"{base}/repos/x/y/pulls/1",
        json={"additions": 100, "deletions": 30, "changed_files": 7},
    )
    requests_mock.get(
        f"{base}/repos/x/y/issues/1/timeline",
        json=[{"event": "ready_for_review", "created_at": "2025-10-09T12:00:00Z"}],
    )

    session = requests.Session()
    since = github.iso_to_dt("2025-10-01T00:00:00+00:00")
    out = list(github.fetch_prs(session, "x/y", since, "main", known_prs=set()))
    assert len(out) == 1
    pr = out[0]
    assert pr["additions"]           == 100
    assert pr["deletions"]           == 30
    assert pr["changed_files"]       == 7
    assert pr["ready_for_review_at"] == "2025-10-09T12:00:00Z"


# --- fetch_deployments ----------------------------------------------------

def test_fetch_deployments_skips_statuses_for_known(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/deployments",
        json=[{
            "id": 100, "sha": "s1", "environment": "production",
            "created_at": "2025-10-10T00:00:00Z",
        }],
    )
    session = requests.Session()
    since = github.iso_to_dt("2025-10-01T00:00:00+00:00")
    out = list(github.fetch_deployments(
        session, "x/y", since, "production", known_deployments={100}
    ))
    assert out[0]["status"] is None  # preserved via COALESCE in upsert


def test_fetch_deployments_fetches_status_for_unknown(requests_mock):
    base = "https://api.github.com"
    requests_mock.get(
        f"{base}/repos/x/y/deployments",
        json=[{
            "id": 100, "sha": "s1", "environment": "production",
            "created_at": "2025-10-10T00:00:00Z",
        }],
    )
    requests_mock.get(
        f"{base}/repos/x/y/deployments/100/statuses",
        json=[{"state": "success"}],
    )
    session = requests.Session()
    since = github.iso_to_dt("2025-10-01T00:00:00+00:00")
    out = list(github.fetch_deployments(
        session, "x/y", since, "production", known_deployments=set()
    ))
    assert out[0]["status"] == "success"
