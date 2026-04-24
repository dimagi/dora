"""Metric runner and output formatters.

`run_report(conn, since, metrics=None)` returns a list of dicts:
    [{"metric", "description", "headers", "rows"}, ...]

Formatters (`print_table`, `print_csv`, `print_json`) take that list plus
the `since` string and an output stream. Keeping them as pure functions
of list→stream lets the CLI pick a stream (stdout or a file) without
formatters needing to know about files.
"""

import csv
import json
import sqlite3
import sys
from typing import IO

from .metrics import METRICS


def run_report(
    conn: sqlite3.Connection,
    since: str,
    metrics: list[str] | None = None,
) -> list[dict]:
    names = metrics or list(METRICS)
    results = []
    for name in names:
        func, description = METRICS[name]
        headers, rows = func(conn, since)
        results.append({
            "metric":      name,
            "description": description,
            "headers":     headers,
            "rows":        rows,
        })
    return results


def print_table(results: list[dict], since: str, stream: IO[str] = sys.stdout) -> None:
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


def print_csv(results: list[dict], since: str, stream: IO[str] = sys.stdout) -> None:
    w = csv.writer(stream)
    for i, r in enumerate(results):
        if i:
            stream.write("\n")
        stream.write(f"# metric: {r['metric']}\n")
        stream.write(f"# description: {r['description']}\n")
        stream.write(f"# since: {since[:10]}\n")
        w.writerow(r["headers"])
        w.writerows(r["rows"])


def print_json(results: list[dict], since: str, stream: IO[str] = sys.stdout) -> None:
    payload = {
        "since": since[:10],
        "metrics": [
            {
                "metric":      r["metric"],
                "description": r["description"],
                "data":        [dict(zip(r["headers"], row)) for row in r["rows"]],
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
