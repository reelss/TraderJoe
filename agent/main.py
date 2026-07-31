"""Joe's entrypoint.

Usage:
  python -m agent.main cycle        # one trading cycle (skips if market closed)
  python -m agent.main cycle --force  # run even if market is closed (testing)
  python -m agent.main cycle --eod  # end-of-day: manage exits only, no new buys
  python -m agent.main reflect      # nightly reflection / playbook update
  python -m agent.main billing --set 25.00  # record Console balance after a top-up
  python -m agent.main audit        # self-audit: assert invariants, alert on breaks
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
    parser.add_argument("mode", choices=["cycle", "reflect", "digest", "weekly",
                                         "billing", "audit"])
    parser.add_argument("--force", action="store_true",
                        help="run a cycle even when the market is closed")
    parser.add_argument("--eod", action="store_true",
                        help="end-of-day cycle: process exits and management "
                             "only — no new buys (avoids unprotected late buys)")
    parser.add_argument("--set", type=float, metavar="BALANCE",
                        help="billing mode: record the current Console credit "
                             "balance (run this right after every top-up)")
    args = parser.parse_args()

    try:
        if args.mode == "cycle":
            from .cycle import run_cycle
            run_cycle(force=args.force, eod_mode=args.eod)
        elif args.mode == "reflect":
            from .reflect import run_reflection
            run_reflection()
        elif args.mode == "digest":
            from .digest import run_digest
            run_digest()
        elif args.mode == "audit":
            from .audit import run_audit
            findings = run_audit()
            if not findings:
                print("All invariants OK.")
            for sev, msg in findings:
                print(f"{sev}: {msg}")
        elif args.mode == "billing":
            if args.set is None:
                print("Usage: python -m agent.main billing --set <balance>")
                sys.exit(1)
            from .billing import set_checkpoint
            set_checkpoint(args.set)
            print(f"Billing checkpoint set: ${args.set:.2f}")
        else:
            from .weekly import run_weekly_review
            run_weekly_review()
    except Exception as exc:  # never let a crash go unlogged
        log.info(f"FATAL in {args.mode}: {exc!r}")
        raise


if __name__ == "__main__":
    main()
