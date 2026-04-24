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


def run_pull(
    *,
    repos: list[str],
    since: str,
    db_path: str,
    base: str,
    environment: str,
    skip_prs: bool,
    skip_deployments: bool,
) -> None:
    """Pull signals for one or more repos into the SQLite DB."""
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

            if not skip_deployments:
                placeholders = ",".join("?" * len(TERMINAL_DEPLOY_STATUSES))
                known_deployments = {
                    row[0] for row in conn.execute(
                        f"SELECT deployment_id FROM deployments "
                        f"WHERE repo = ? AND environment = ? "
                        f"AND status IN ({placeholders})",
                        (repo, environment, *TERMINAL_DEPLOY_STATUSES),
                    )
                }
                print(
                    f"  fetching deployments ({environment})… "
                    f"({len(known_deployments)} cached, statuses call skipped)",
                    file=sys.stderr,
                )
                tick, done = _make_progress(f"deployments ({environment})")
                n_cached = 0
                for d in github.fetch_deployments(
                    session, repo, since_dt, environment, known_deployments
                ):
                    db.upsert_deployment(conn, repo, d)
                    if d["deployment_id"] in known_deployments:
                        n_cached += 1
                    tick()
                done()
                if n_cached:
                    print(f"    ({n_cached} reused from cache)", file=sys.stderr)
                conn.commit()
    finally:
        conn.close()
