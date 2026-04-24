"""Dora CLI — argparse dispatch. Subcommands filled in later tasks."""

import sys


def main(argv: list[str] | None = None) -> int:
    """Entry point referenced by pyproject.toml [project.scripts].

    Subcommands added in later tasks (pull, report, upload).
    """
    argv = argv if argv is not None else sys.argv[1:]
    print("dora: no subcommands wired up yet (skeleton)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
