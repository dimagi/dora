"""Orchestration: fetch GitHub → upsert into SQLite, with caching + progress."""

import sys

from . import db, github

TERMINAL_DEPLOY_STATUSES = frozenset({"success", "failure", "error", "inactive"})


def _make_progress(label: str):
    """(tick, done) callbacks that print a running counter on stderr.

    On a TTY, overwrite a single line. Otherwise, every 10 ticks so log
    tails stay readable.
    """
    tty = sys.stderr.isatty()
    n = 0

    def tick():
        nonlocal n
        n += 1
        if tty:
            print(f"\r  {label}: {n}", file=sys.stderr, end="", flush=True)
        elif n % 10 == 0:
            print(f"  {label}: {n}", file=sys.stderr, flush=True)

    def done():
        if tty:
            print(f"\r  {label}: {n}", file=sys.stderr, flush=True)
        else:
            print(f"  {label}: {n} (done)", file=sys.stderr, flush=True)

    return tick, done


def _pull_prs(conn, session, repo, since_dt, base):
    known_prs = {
        row[0] for row in conn.execute(
            "SELECT number FROM pull_requests "
            "WHERE repo = ? AND first_commit_at IS NOT NULL",
            (repo,),
        )
    }
    print(
        f"  fetching merged PRs into {base}… "
        f"({len(known_prs)} cached, commits call skipped)",
        file=sys.stderr,
    )
    tick, done = _make_progress(f"merged PRs into {base}")
    n_cached = 0
    for pr in github.fetch_prs(session, repo, since_dt, base, known_prs):
        db.upsert_pr(conn, repo, pr)
        if pr["number"] in known_prs:
            n_cached += 1
        tick()
    done()
    if n_cached:
        print(f"    ({n_cached} reused from cache)", file=sys.stderr)
    conn.commit()


def _pull_deploy_signals(conn, session, repo, since_dt, environment, source):
    """Fetch deploy signals for `repo` and upsert them into `deployments`.

    Two source paths share the same upsert + progress scaffolding; only the
    cache query, fetcher, and log labels differ.
    """
    if source == "releases":
        known = {
            row[0] for row in conn.execute(
                "SELECT deployment_id FROM deployments "
                "WHERE repo = ? AND environment = 'production'",
                (repo,),
            )
        }
        label = "releases"
        cache_msg = (
            f"  fetching releases… ({len(known)} cached, skipped)"
        )
        fetcher = github.fetch_releases(session, repo, since_dt, known)
    else:
        placeholders = ",".join("?" * len(TERMINAL_DEPLOY_STATUSES))
        known = {
            row[0] for row in conn.execute(
                f"SELECT deployment_id FROM deployments "
                f"WHERE repo = ? AND environment = ? "
                f"AND status IN ({placeholders})",
                (repo, environment, *TERMINAL_DEPLOY_STATUSES),
            )
        }
        label = f"deployments ({environment})"
        cache_msg = (
            f"  fetching deployments ({environment})… "
            f"({len(known)} cached, statuses call skipped)"
        )
        fetcher = github.fetch_deployments(
            session, repo, since_dt, environment, known
        )

    print(cache_msg, file=sys.stderr)
    tick, done = _make_progress(label)
    n_cached = 0
    for d in fetcher:
        db.upsert_deployment(conn, repo, d)
        if d["deployment_id"] in known:
            n_cached += 1
        tick()
    done()
    if n_cached:
        print(f"    ({n_cached} reused from cache)", file=sys.stderr)
    conn.commit()


def run_pull(
    *,
    repos: list[str],
    since: str,
    db_path: str,
    base: str,
    environment: str,
    source: str,
    skip_prs: bool,
    skip_deployments: bool,
) -> None:
    """Pull signals for one or more repos into the SQLite DB.

    `source` selects the deploy-signal endpoint:
        "deployments" → /repos/.../deployments (default)
        "releases"    → /repos/.../releases (mapped to environment='production')
    """
    token = github.get_token()
    session = github.make_session(token)

    since_dt = github.iso_to_dt(
        since if "T" in since else since + "T00:00:00+00:00"
    )

    conn = db.init_db(db_path)
    try:
        for repo in repos:
            print(f"→ {repo}", file=sys.stderr)

            if not skip_prs:
                _pull_prs(conn, session, repo, since_dt, base)

            if not skip_deployments:
                _pull_deploy_signals(
                    conn, session, repo, since_dt, environment, source,
                )
    finally:
        conn.close()
