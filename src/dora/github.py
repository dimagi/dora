"""GitHub API client: auth, paginated fetch, rate-limit handling.

Factored out of dora_pull.py so pull logic and HTTP plumbing can be
tested independently. Uses `requests.Session` for connection reuse.
"""

import os
import subprocess
import sys
import time
from collections.abc import Generator, Iterator
from datetime import datetime
from typing import Any

import requests

API = "https://api.github.com"


def get_token() -> str:
    """Return a GitHub token. Prefers `gh auth token`, falls back to GITHUB_TOKEN."""
    try:
        r = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, check=True, timeout=5,
        )
        token = r.stdout.strip()
        if token:
            return token
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    sys.exit("No GitHub auth found. Run `gh auth login`, or set GITHUB_TOKEN.")


def make_session(token: str) -> requests.Session:
    """Configured Session with GitHub auth headers."""
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    return s


def gh(
    session: requests.Session,
    path: str,
    params: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Iterate a paginated GitHub endpoint, handling rate limits.

    Yields items one at a time. Follows Link: rel="next" for pagination.
    On 403 with "rate limit" in the body, sleeps until X-RateLimit-Reset
    and retries the same URL.
    """
    url = f"{API}{path}"
    while url:
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            reset = int(r.headers.get("X-RateLimit-Reset", "0"))
            wait = max(reset - int(time.time()), 0) + 1
            print(f"  rate-limited; sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        r.raise_for_status()
        for item in r.json():
            yield item
        url = r.links.get("next", {}).get("url")
        params = None  # next URL already carries the query string


def iso_to_dt(s: str) -> datetime:
    """Parse an ISO-8601 timestamp (GitHub uses trailing Z) to aware datetime."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _fetch_ready_for_review_at(
    session: requests.Session,
    repo: str,
    number: int,
) -> str | None:
    """Return the timestamp of the first `ready_for_review` event, or None.

    A PR that was never a draft has no `ready_for_review` event in its
    timeline; we return None and let the metric COALESCE down to opened_at.
    A PR toggled draft → ready → draft → ready returns the FIRST ready
    event (most conservative — longest review window).
    """
    for ev in gh(session, f"/repos/{repo}/issues/{number}/timeline"):
        if ev.get("event") == "ready_for_review":
            return ev.get("created_at")
    return None


def fetch_prs(
    session: requests.Session,
    repo: str,
    since: datetime,
    base: str,
    known_prs: set[int],
) -> Generator[dict, None, None]:
    """Yield merged PRs against `base` merged on/after `since`.

    The /pulls API doesn't filter by merged_at, so we page in updated-desc
    order, stop when we page past `since`, and filter merged_at within.

    PRs whose number is in `known_prs` skip the per-PR API calls
    (commits + pull detail + timeline) — the four corresponding fields
    stay None so the upsert COALESCE preserves the stored values.
    """
    params = {
        "state":     "closed",
        "sort":      "updated",
        "direction": "desc",
        "base":      base,
        "per_page":  100,
    }
    for pr in gh(session, f"/repos/{repo}/pulls", params):
        if iso_to_dt(pr["updated_at"]) < since:
            return
        if not pr["merged_at"] or iso_to_dt(pr["merged_at"]) < since:
            continue

        if pr["number"] in known_prs:
            first_commit_at     = None  # cached
            additions           = None
            deletions           = None
            changed_files       = None
            ready_for_review_at = None
        else:
            commits = list(
                gh(session, f"/repos/{repo}/pulls/{pr['number']}/commits", {"per_page": 100})
            )
            first_commit_at = (
                commits[0]["commit"]["author"]["date"] if commits else pr["created_at"]
            )

            detail = session.get(
                f"{API}/repos/{repo}/pulls/{pr['number']}", timeout=30
            )
            detail.raise_for_status()
            d = detail.json()
            additions     = d.get("additions")
            deletions     = d.get("deletions")
            changed_files = d.get("changed_files")

            ready_for_review_at = _fetch_ready_for_review_at(
                session, repo, pr["number"]
            )

        yield {
            "number":              pr["number"],
            "title":               pr["title"],
            "author":              (pr.get("user") or {}).get("login"),
            "base":                pr["base"]["ref"],
            "opened_at":           pr["created_at"],
            "merged_at":           pr["merged_at"],
            "first_commit_at":     first_commit_at,
            "merge_sha":           pr["merge_commit_sha"],
            "labels":              ",".join(l["name"] for l in pr.get("labels") or []),
            "additions":           additions,
            "deletions":           deletions,
            "changed_files":       changed_files,
            "ready_for_review_at": ready_for_review_at,
        }


def fetch_deployments(
    session: requests.Session,
    repo: str,
    since: datetime,
    environment: str,
    known_deployments: set[int],
) -> Generator[dict, None, None]:
    """Yield deployments for `environment` created on/after `since`.

    Deployments in `known_deployments` (already have a terminal status)
    skip the /statuses call; yielded status is None so COALESCE preserves
    the stored value. Transient statuses (pending/queued/in_progress) are
    always re-fetched because they can change.
    """
    params = {"environment": environment, "per_page": 100}
    for d in gh(session, f"/repos/{repo}/deployments", params):
        if iso_to_dt(d["created_at"]) < since:
            return  # API returns newest first

        if d["id"] in known_deployments:
            status = None
        else:
            statuses = list(
                gh(session, f"/repos/{repo}/deployments/{d['id']}/statuses", {"per_page": 1})
            )
            status = statuses[0]["state"] if statuses else None

        yield {
            "deployment_id": d["id"],
            "sha":           d["sha"],
            "environment":   d["environment"],
            "created_at":    d["created_at"],
            "status":        status,
        }


def fetch_releases(
    session: requests.Session,
    repo: str,
    since: datetime,
    known_releases: set[int],
) -> Generator[dict, None, None]:
    """Yield published GitHub releases on/after `since` as deployment-shaped dicts.

    Skips drafts, pre-releases, and releases already in `known_releases`.
    Releases are immutable post-publish, so cached IDs are skipped entirely
    (no status to refresh, unlike fetch_deployments).
    """
    for r in gh(session, f"/repos/{repo}/releases", {"per_page": 100}):
        if r["draft"] or r["prerelease"]:
            continue
        if r["published_at"] is None:
            continue
        if iso_to_dt(r["published_at"]) < since:
            return  # /releases is newest-first
        if r["id"] in known_releases:
            continue
        yield {
            "deployment_id": r["id"],
            "sha":           r["target_commitish"],
            "environment":   "production",
            "created_at":    r["published_at"],
            "status":        "success",
        }
