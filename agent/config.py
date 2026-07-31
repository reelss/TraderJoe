"""Central configuration for Joe: credentials, risk rules, and universe filters.

All secrets come from the .env file (never hard-coded). All tunable behavior
lives here so the rest of the codebase reads, never guesses.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Project root = the folder that contains this `agent/` package.
ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"
PLAYBOOK_PATH = ROOT / "playbook.md"
PRINCIPLES_PATH = ROOT / "principles.md"  # durable rules — not rewritten nightly
STRATEGY_PATH = ROOT / "strategy.md"
DASHBOARD_PATH = ROOT / "dashboard.md"
HWM_PATH = ROOT / "logs" / "hwm.json"  # peak unrealized gain per open position
PEAKS_PATH = ROOT / "logs" / "peaks.json"  # peak plpc per position for trailing exit

# Load .env from the project root. override=True so Joe's own .env is the single
# source of truth — otherwise an empty/shadowing OS var (e.g. a harness-set
# ANTHROPIC_API_KEY="") would silently win and break the Claude calls.
load_dotenv(ROOT / ".env", override=True)


def _require(name: str) -> str:
    """Fetch an env var, returning '' if missing (connection check reports it)."""
    return os.getenv(name, "").strip()


@dataclass(frozen=True)
class Credentials:
    alpaca_key: str = field(default_factory=lambda: _require("ALPACA_API_KEY"))
    alpaca_secret: str = field(default_factory=lambda: _require("ALPACA_SECRET_KEY"))
    reddit_client_id: str = field(default_factory=lambda: _require("REDDIT_CLIENT_ID"))
    reddit_client_secret: str = field(default_factory=lambda: _require("REDDIT_CLIENT_SECRET"))
    reddit_user_agent: str = field(default_factory=lambda: _require("REDDIT_USER_AGENT") or "joe-trader/0.1")
    anthropic_key: str = field(default_factory=lambda: _require("ANTHROPIC_API_KEY"))
    # Optional — Finnhub source auto-activates only if this is present.
    finnhub_key: str = field(default_factory=lambda: _require("FINNHUB_API_KEY"))
    # Optional — Slack incoming-webhook URL for the daily digest.
    slack_webhook: str = field(default_factory=lambda: _require("SLACK_WEBHOOK_URL"))

    @staticmethod
    def _unset(v: str) -> bool:
        # Empty or still a .env.example placeholder ("your_..._here").
        return not v or v.lower().startswith("your_")

    def missing(self) -> list[str]:
        """REQUIRED credentials that are unset: the account + the brain.
        Reddit and Finnhub are optional sources, checked separately."""
        required = {
            "ALPACA_API_KEY": self.alpaca_key,
            "ALPACA_SECRET_KEY": self.alpaca_secret,
            "ANTHROPIC_API_KEY": self.anthropic_key,
        }
        return [k for k, v in required.items() if self._unset(v)]

    def has_reddit(self) -> bool:
        return not (self._unset(self.reddit_client_id)
                    or self._unset(self.reddit_client_secret))


@dataclass(frozen=True)
class RiskRules:
    """Hard guardrails. Joe may reason within these but never outside them."""
    starting_equity: float = 10_000.0
    max_position_pct: float = 0.10        # <= 10% of equity per position (~$1,000)
    max_open_positions: int = 8
    stop_loss_pct: float = 0.08           # exit a position down 8% from entry
    take_profit_pct: float = 0.15         # exit a position up 15% from entry
    daily_loss_breaker_pct: float = 0.05  # halt new trades if account -5% on the day
    # Stale position exit: capital recycling. If a position has barely moved after
    # a month it's dead money — exit and redeploy where there's actual momentum.
    stale_flag_days: int = 21             # brain sees stale=True flag; can exit early
    stale_exit_days: int = 35             # hard auto-exit threshold
    stale_exit_max_gain_pct: float = 0.02 # only triggers if gain < 2% (not a slow winner)
    # Re-entry cooldown: don't buy back a name we just stopped out of.
    cooldown_days: int = 5                # days after a stop-loss before re-entry allowed
    # Whole-share entries (not fractional): required so the broker can attach
    # bracket stop-loss/take-profit orders, which it can't do on fractional shares.
    allow_fractional: bool = False


@dataclass(frozen=True)
class StrategyConfig:
    """Researched, evidence-based edges encoded into Joe's strategy (2026-06-02).
    - Regime filter: only open new longs when the market (SPY) is above its
      200-day SMA — trend-following research shows this slashes drawdowns.
    - Momentum: prefer names with strong 12-1 relative momentum (Jegadeesh-Titman).
    - Volatility sizing/stops (ATR): size each position to its own risk and set
      stops by volatility, so jumpy names get smaller positions + wider stops.
    """
    regime_symbol: str = "SPY"
    regime_sma: int = 200                 # SPY above its 200-day SMA = risk-on
    bars_lookback_days: int = 420         # enough trading days for 200-SMA + 12-1 mom
    risk_per_trade_pct: float = 0.02      # risk ~2% of equity from entry to stop
    atr_stop_mult: float = 2.5            # stop distance = 2.5 x ATR(14)
    min_stop_pct: float = 0.05            # clamp the ATR stop to this floor
    max_stop_pct: float = 0.09            # ...and this ceiling
    # Deployment floor: in a risk-on regime with room for more positions, don't
    # let the 2%-risk formula alone leave capital idle. Scale sizing toward the
    # position cap until at least this fraction of equity is deployed.
    min_deploy_pct: float = 0.50          # target >= 50% of equity deployed when risk-on


@dataclass(frozen=True)
class UniverseFilters:
    """Sanity filters applied to Reddit-discovered tickers before Joe considers them."""
    min_price: float = 3.0                # avoid sub-$3 penny noise
    max_price: float = 2_000.0
    min_avg_dollar_volume: float = 5_000_000.0  # needs real liquidity
    max_candidates: int = 12              # cap how many names go to the brain per cycle


@dataclass(frozen=True)
class SocialConfig:
    subreddits: tuple[str, ...] = (
        "wallstreetbets",
        "stocks",
        "swingtrading",
        "StockMarket",
    )
    posts_per_sub: int = 40               # hot posts scanned per subreddit
    min_mentions: int = 3                 # ticker must appear at least this often


@dataclass(frozen=True)
class SourceConfig:
    """Multi-source discovery. Weights reflect reliability — they scale a
    source's contribution to a ticker's aggregate 'attention' score, so a
    newswire mention counts far more than a Reddit shout."""
    enable_reddit: bool = False           # Reddit API requires formal approval as of 2026 — not worth it for 0.6-weight signal
    enable_stocktwits: bool = False       # Cloudflare-gated (403) as of 2026 — opt-in only
    enable_alpaca_news: bool = True
    enable_finnhub: bool = True           # only fires if FINNHUB_API_KEY is set
    enable_sector_rs: bool = True         # momentum-leader screen from top RS sectors
    enable_watchlist: bool = True         # playbook priority names re-enter candidates
    enable_sector_etf: bool = True        # leading sector ETFs as deployment vehicles

    weight_alpaca_news: float = 1.5       # professional newswire (Benzinga)
    weight_sector_rs: float = 1.2         # sector momentum leaders (not news-reactive)
    weight_watchlist: float = 1.1         # Joe's own playbook priorities
    weight_sector_etf: float = 1.0        # fallback vehicle — ranks below single names
    weight_finnhub: float = 1.4           # structured news + insider sentiment
    weight_stocktwits: float = 1.0        # purpose-built, user bull/bear tags
    weight_reddit: float = 0.6            # noisiest, most hype-prone

    news_lookback_hours: int = 24         # how far back the news feeds look
    news_limit: int = 50                  # articles pulled per news source
    stocktwits_top_n: int = 10            # trending symbols enriched with sentiment
    min_weighted_mentions: float = 2.0    # aggregate floor to be a candidate


@dataclass(frozen=True)
class ModelConfig:
    # Sonnet for per-cycle decisions (upgraded from Haiku 2026-07-06): one bad
    # hourly judgment costs more than a month of the API-fee difference.
    decision_model: str = "claude-sonnet-4-6"
    # Stronger model for the nightly reflection that rewrites the playbook.
    reflection_model: str = "claude-sonnet-4-6"
    max_tokens: int = 4_000
    # Reflection/weekly emit two full documents in one response; 4k truncated
    # the principles file mid-sentence on 2026-07-30 and silently dropped four
    # sections of durable rules.
    reflection_max_tokens: int = 12_000


CREDS = Credentials()
RISK = RiskRules()
STRATEGY = StrategyConfig()
UNIVERSE = UniverseFilters()
SOCIAL = SocialConfig()
SOURCES = SourceConfig()
MODELS = ModelConfig()
