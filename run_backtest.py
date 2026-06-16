"""CLI entry point for backtesting Joe's strategy against historical data.

Usage
-----
  python run_backtest.py                            # 2-year default
  python run_backtest.py --start 2022-01-01
  python run_backtest.py --start 2022-01-01 --end 2024-01-01
  python run_backtest.py --start 2023-01-01 --out results/bt_2023.json

Results are always written to results/backtest_<timestamp>.json (or --out).
A summary is printed to stdout.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.backtest import Backtester


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest Joe's swing strategy")
    p.add_argument(
        "--start",
        default=(datetime.now(timezone.utc) - timedelta(days=730)).date().isoformat(),
        help="Start date YYYY-MM-DD (default: 2 years ago)",
    )
    p.add_argument("--end",    default=None,      help="End date YYYY-MM-DD (default: today)")
    p.add_argument("--equity", type=float, default=10_000.0, help="Starting equity (default 10000)")
    p.add_argument("--out",    default=None,      help="Output JSON path (optional)")
    args = p.parse_args()

    bt = Backtester(start_date=args.start, end_date=args.end, starting_equity=args.equity)
    results = bt.run()

    # Separate heavy arrays for clean stdout summary
    equity_curve = results.pop("equity_curve", [])
    trades       = results.pop("trades",       [])

    print("\n" + "=" * 50)
    print("  BACKTEST RESULTS")
    print("=" * 50)
    skip = {"exits_by_reason", "note"}
    for k, v in results.items():
        if k not in skip:
            label = k.replace("_", " ").title()
            print(f"  {label:<28} {v}")

    print("\n  Exits by Reason:")
    for reason, stats in results.get("exits_by_reason", {}).items():
        print(f"    {reason:<30} "
              f"count={stats['count']:>3}  "
              f"win={stats['win_rate']:.0%}  "
              f"avg={stats['avg_plpc_pct']:+.2f}%")

    if results.get("note"):
        print(f"\n  Note: {results['note']}")
    print("=" * 50)

    # Write JSON
    out_path = Path(args.out) if args.out else (
        Path("results") / f"backtest_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    full = {**results, "equity_curve": equity_curve, "trades": trades}
    out_path.write_text(json.dumps(full, indent=2), encoding="utf-8")
    print(f"\n  Full results → {out_path}")
    print(f"  {len(trades)} trades · {len(equity_curve)} equity snapshots\n")


if __name__ == "__main__":
    main()
