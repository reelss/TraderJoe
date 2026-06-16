"""Phase 1 connection test. Run after filling in .env:

    python scripts/check_connections.py

Verifies all three integrations independently and prints a clear pass/fail
per service. No orders are placed.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script (not just `python -m`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import CREDS  # noqa: E402


def check_env() -> bool:
    missing = CREDS.missing()
    if missing:
        print(f"[ENV ]  FAIL — missing in .env: {', '.join(missing)}")
        return False
    print("[ENV ]  ok   — all keys present")
    return True


def check_alpaca() -> bool:
    try:
        from agent.broker import Broker
        acct = Broker().account()
        print(f"[ALPA]  ok   — paper account equity ${acct['equity']:.2f}, "
              f"cash ${acct['cash']:.2f}")
        return True
    except Exception as exc:
        print(f"[ALPA]  FAIL — {exc!r}")
        return False


def check_alpaca_news() -> bool:
    try:
        from agent.sources.alpaca_news_source import AlpacaNewsSource
        sigs = AlpacaNewsSource().discover()
        print(f"[NEWS]  ok   — Alpaca/Benzinga news: {len(sigs)} tickers in headlines")
        return True
    except Exception as exc:
        print(f"[NEWS]  FAIL — {exc!r}")
        return False


def check_stocktwits() -> bool:
    # Public, no key, best-effort — a soft failure is not fatal to the build.
    try:
        from agent.sources.stocktwits_source import StockTwitsSource
        syms = StockTwitsSource()._trending_symbols()
        if syms:
            print(f"[STWT]  ok   — StockTwits trending: {', '.join(syms[:6])}")
        else:
            print("[STWT]  warn — StockTwits returned nothing (rate-limited/gated); "
                  "Joe will skip it gracefully")
        return True
    except Exception as exc:
        print(f"[STWT]  warn — {exc!r} (non-fatal)")
        return True


def check_finnhub() -> bool:
    if not CREDS.finnhub_key:
        print("[FINN]  skip — no FINNHUB_API_KEY set (optional source disabled)")
        return True
    try:
        from agent.sources.finnhub_source import FinnhubSource
        sigs = FinnhubSource().discover()
        print(f"[FINN]  ok   — Finnhub news: {len(sigs)} tickers")
        return True
    except Exception as exc:
        print(f"[FINN]  FAIL — {exc!r}")
        return False


def check_reddit() -> bool:
    if not CREDS.has_reddit():
        print("[REDD]  skip — no Reddit creds set (source disabled)")
        return True
    try:
        import praw
        reddit = praw.Reddit(
            client_id=CREDS.reddit_client_id,
            client_secret=CREDS.reddit_client_secret,
            user_agent=CREDS.reddit_user_agent,
        )
        reddit.read_only = True
        title = next(reddit.subreddit("stocks").hot(limit=1)).title
        print(f"[REDD]  ok   — r/stocks reachable (top: {title[:50]!r})")
        return True
    except Exception as exc:
        print(f"[REDD]  FAIL — {exc!r}")
        return False


def check_anthropic() -> bool:
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=CREDS.anthropic_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "Reply with the word: ready"}],
        )
        print(f"[CLDE]  ok   — Claude responded: {resp.content[0].text.strip()!r}")
        return True
    except Exception as exc:
        print(f"[CLDE]  FAIL — {exc!r}")
        return False


def main() -> None:
    print("Joe — connection check\n" + "-" * 40)
    if not check_env():
        print("\nFill in .env (copy from .env.example) and re-run.")
        sys.exit(1)
    results = [check_alpaca(), check_alpaca_news(), check_stocktwits(),
               check_finnhub(), check_reddit(), check_anthropic()]
    print("-" * 40)
    if all(results):
        print("ALL GREEN — Joe is ready. Try: python -m agent.main cycle --force")
    else:
        print("Some checks failed — see above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
