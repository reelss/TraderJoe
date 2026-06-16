"""Joe's entrypoint.

Usage:
  python -m agent.main cycle        # one trading cycle (skips if market closed)
  python -m agent.main cycle --force  # run even if market is closed (testing)
  python -m agent.main reflect      # nightly reflection / playbook update
"""
from __future__ import annotations

import argparse
import sys

from . import logbook as log

# Windows Task Scheduler runs with a cp1252 console; force UTF-8 so emoji or
# other non-Latin chars in any log line can never crash a scheduled run.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(prog="joe")
    parser.add_argument("mode", choices=["cycle", "reflect", "digest", "weekly"])
    parser.add_argument("--force", action="store_true",
                        help="run a cycle even when the market is closed")
    args = parser.parse_args()

    try:
        if args.mode == "cycle":
            from .cycle import run_cycle
            run_cycle(force=args.force)
        elif args.mode == "reflect":
            from .reflect import run_reflection
            run_reflection()
        elif args.mode == "digest":
            from .digest import run_digest
            run_digest()
        else:
            from .weekly import run_weekly_review
            run_weekly_review()
    except Exception as exc:  # never let a crash go unlogged
        log.info(f"FATAL in {args.mode}: {exc!r}")
        raise


if __name__ == "__main__":
    main()
