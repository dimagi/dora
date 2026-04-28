"""Dora CLI — argparse + subcommand dispatch.

Subcommands (each in its own module):
  - pull    (dora.pull.run_pull)
  - report  (dora.report.run_report + formatters)
  - upload  (dora.upload.upload_s3 — optional, requires [s3] extra)
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Sequence

from . import pull as pull_mod
from . import report as report_mod
from .metrics import METRICS


def _add_pull(sub):
    p = sub.add_parser("pull", help="Fetch DORA signals from GitHub into SQLite.")
    p.add_argument("--repo", required=True, action="append", help="owner/name (repeatable)")
    p.add_argument("--since", required=True, help="ISO date, e.g. 2025-10-01")
    p.add_argument("--db", default="dora.db")
    p.add_argument("--base", default="main")
    p.add_argument("--environment", default="production")
    p.add_argument("--skip-prs", action="store_true")
    p.add_argument("--skip-deployments", action="store_true")


def _add_report(sub):
    p = sub.add_parser("report", help="Run metric queries, emit table/CSV/JSON.")
    p.add_argument("--db", default="dora.db")
    p.add_argument("--weeks", type=int, default=12)
    p.add_argument("--metric", choices=list(METRICS), action="append")
    p.add_argument("--format", choices=list(report_mod.FORMATTERS), default="table")
    p.add_argument("--output", help="Write output to FILE instead of stdout")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--exclude-bots", dest="exclude_bots", action="store_const",
                   const=True,
                   help="Exclude PRs whose author ends with `[bot]` from every metric")
    g.add_argument("--include-bots", dest="exclude_bots", action="store_const",
                   const=False,
                   help="Force-include bot PRs in every metric (override defaults)")
    p.set_defaults(exclude_bots=None)


def _add_upload(sub):
    p = sub.add_parser("upload", help="Upload a file to a target URL (e.g. s3://…).")
    p.add_argument("path", help="File to upload")
    p.add_argument("--target", required=True, help="Destination URL, e.g. s3://bucket/key")
    p.add_argument("--content-type", default="application/json")
    p.add_argument("--public-read", action="store_true",
                   help="Set public-read ACL on the object (S3 only)")


def _cmd_pull(args: argparse.Namespace) -> int:
    pull_mod.run_pull(
        repos=args.repo,
        since=args.since,
        db_path=args.db,
        base=args.base,
        environment=args.environment,
        skip_prs=args.skip_prs,
        skip_deployments=args.skip_deployments,
    )
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    since = (datetime.now(timezone.utc) - timedelta(weeks=args.weeks)).isoformat()
    conn = sqlite3.connect(args.db)
    try:
        bot_policy, results = report_mod.run_report(
            conn, since, metrics=args.metric, exclude_bots=args.exclude_bots,
        )
    finally:
        conn.close()
    fmt = report_mod.FORMATTERS[args.format]
    if args.output:
        with open(args.output, "w") as f:
            fmt(bot_policy, results, since, f)
    else:
        fmt(bot_policy, results, since, sys.stdout)
    return 0


def _cmd_upload(args: argparse.Namespace) -> int:
    from . import upload as upload_mod  # lazy: boto3 only needed for this path
    upload_mod.upload_s3(
        args.path, args.target,
        content_type=args.content_type,
        public_read=args.public_read,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dora",
        description="Collect DORA metrics from GitHub and report them.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    _add_pull(sub)
    _add_report(sub)
    _add_upload(sub)

    args = parser.parse_args(argv)

    dispatch = {
        "pull":   _cmd_pull,
        "report": _cmd_report,
        "upload": _cmd_upload,
    }
    return dispatch[args.command](args)
