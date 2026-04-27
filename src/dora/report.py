"""Metric runner and output formatters.

`run_report(conn, since, metrics=None, exclude_bots=None)` returns a tuple
`(bot_policy, results)` where `results` is a list of dicts:
    [{"metric", "description", "exclude_bots", "headers", "rows"}, ...]

`bot_policy` is one of "default", "all-excluded", "all-included" and reflects
the user-supplied `exclude_bots` argument, NOT the resolved per-metric values.

Formatters (`print_table`, `print_csv`, `print_json`) take `bot_policy`, the
results list, the `since` string, and an output stream. Keeping them as pure
functions lets the CLI pick a stream (stdout or a file) without formatters
needing to know about files.
"""

import csv
import json
import sqlite3
import sys
from typing import IO

from .metrics import DEFAULT_EXCLUDE_BOTS, METRICS


def run_report(
    conn: sqlite3.Connection,
    since: str,
    metrics: list[str] | None = None,
    exclude_bots: bool | None = None,
) -> tuple[str, list[dict]]:
    """Run the listed metrics. exclude_bots:
        None  → per-metric defaults (DEFAULT_EXCLUDE_BOTS)
        True  → force-exclude bots from every metric
        False → force-include bots in every metric

    Returns (bot_policy, results). bot_policy is one of "default",
    "all-excluded", "all-included" — derived from the user-supplied
    exclude_bots, NOT from the resolved per-metric values (a default-mode
    run on a single metric whose default is True must still report
    "default", not "all-excluded").
    """
    names = metrics or list(METRICS)
    if exclude_bots is True:
        bot_policy = "all-excluded"
    elif exclude_bots is False:
        bot_policy = "all-included"
    else:
        bot_policy = "default"

    results = []
    for name in names:
        func, description = METRICS[name]
        registry = DEFAULT_EXCLUDE_BOTS[name]
        # Each branch resolves what to pass to the metric function (or whether
        # to call it without the kwarg at all) and what to surface in the JSON.
        if name == "summary":
            # summary takes a tri-state arg and resolves per-component itself.
            headers, rows = func(conn, since, exclude_bots=exclude_bots)
            resolved: bool | None = exclude_bots
        elif registry is None:
            # Metric doesn't read the author column (e.g. deploy-freq).
            # Calling with exclude_bots=... would TypeError; skip the kwarg.
            # Still surface the user's choice when forced so the dashboard's
            # policy banner stays consistent across all metrics.
            headers, rows = func(conn, since)
            resolved = None if exclude_bots is None else exclude_bots
        else:
            policy_arg = registry if exclude_bots is None else exclude_bots
            headers, rows = func(conn, since, exclude_bots=policy_arg)
            resolved = policy_arg
        results.append({
            "metric":       name,
            "description":  description,
            "exclude_bots": resolved,
            "headers":      headers,
            "rows":         rows,
        })
    return bot_policy, results


def print_table(bot_policy: str, results: list[dict], since: str,
                stream: IO[str] = sys.stdout) -> None:
    # bot_policy unused by the table formatter (terminal users see metric-
    # level info elsewhere). Keeping the parameter for API uniformity.
    for i, r in enumerate(results):
        if i:
            stream.write("\n")
        stream.write(f"# {r['metric']}  (since {since[:10]})\n")
        stream.write(f"# {r['description']}\n")
        headers, rows = r["headers"], r["rows"]
        if not rows:
            stream.write("  (no data)\n")
            continue
        widths = [len(h) for h in headers]
        for row in rows:
            for j, val in enumerate(row):
                widths[j] = max(widths[j], len(str(val if val is not None else "-")))
        fmt = "  ".join(f"{{:<{w}}}" for w in widths)
        stream.write(fmt.format(*headers) + "\n")
        stream.write(fmt.format(*("-" * w for w in widths)) + "\n")
        for row in rows:
            stream.write(fmt.format(*(str(v) if v is not None else "-" for v in row)) + "\n")


def print_csv(bot_policy: str, results: list[dict], since: str,
              stream: IO[str] = sys.stdout) -> None:
    # bot_policy unused by the CSV formatter. Keeping the parameter for API uniformity.
    w = csv.writer(stream)
    for i, r in enumerate(results):
        if i:
            stream.write("\n")
        stream.write(f"# metric: {r['metric']}\n")
        stream.write(f"# description: {r['description']}\n")
        stream.write(f"# since: {since[:10]}\n")
        w.writerow(r["headers"])
        w.writerows(r["rows"])


def print_json(bot_policy: str, results: list[dict], since: str,
               stream: IO[str] = sys.stdout) -> None:
    payload = {
        "since":      since[:10],
        "bot_policy": bot_policy,
        "metrics": [
            {
                "metric":       r["metric"],
                "description":  r["description"],
                "exclude_bots": r["exclude_bots"],
                "data":         [dict(zip(r["headers"], row)) for row in r["rows"]],
            }
            for r in results
        ],
    }
    json.dump(payload, stream, default=str, indent=2)
    stream.write("\n")


FORMATTERS = {
    "table": print_table,
    "csv":   print_csv,
    "json":  print_json,
}
