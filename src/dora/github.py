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
