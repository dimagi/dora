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
