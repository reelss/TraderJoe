# Joe Trading System — Security Audit Report

**Date:** June 16, 2026  
**Auditor:** Claude (Cowork)  
**Status:** 4 Critical Issues Identified, 2 N/A

---

## Executive Summary

Joe has **moderate-to-good security hygiene** compared to the 25 AI-generated apps reviewed. The system handles secrets properly, has defensive error handling, and is a single-user autonomous agent (no multi-user auth risks). However, **three critical gaps exist** that should be remediated before expanding the system:

1. **Infisical migration pending** (secrets still in .env)
2. **No rate limiting on API calls** (could spike cloud costs)
3. **API error handling gaps** in some sources (crashes possible)
4. **GitHub Actions git authentication failure** (blocking scheduled jobs)

---

## Findings by Issue

### ✅ Issue #1: Auth Tokens in Repo
**Status:** GOOD (with caveats)

**What Joe Does Right:**
- `.env` is properly listed in `.gitignore`
- Secrets loaded via `dotenv` with `override=True` (prevents shadowing)
- Credentials are never hard-coded
- GitHub Actions uses GitHub Secrets (correct practice)

**What Needs Work:**
- `.env` file exists on disk with real credentials — **not yet migrated to Infisical**
- CLAUDE.md notes: "Secrets in `.env` — migrate to Infisical `trading-project` (pending)"
- Local development still uses plaintext `.env` (acceptable for paper trading, but risky if real money added)

**Remediation:**
1. **Complete Infisical migration:** Move to `infisical run --env=prod -- python -m agent.main cycle`
2. Add `Infisical/.env` pattern to docs for local dev setup
3. Rotate all credentials after migration as a precaution

**Risk Level:** 🟡 MEDIUM (mitigated by paper trading + local-only access)

---

### ❌ Issue #2: RLS Misconfigured
**Status:** N/A — Not Applicable

Joe is a single-user autonomous trading agent with no database or multi-user access control. RLS is not relevant. ✅

---

### ⚠️ Issue #3: No Rate Limiting on APIs
**Status:** CRITICAL GAP

**What Joe Calls:**
- **Alpaca API** (market data, orders, account state)
- **Claude API** (decision-making, reflection)
- **Finnhub API** (structured news, insider data)
- **Benzinga newswire** (via Alpaca News endpoint)
- **Reddit API** (optional, currently disabled)
- **StockTwits** (optional, currently disabled)

**Current Protections:**
- ✅ Claude API: `llm_retry.py` has exponential backoff on 429 RateLimitError
- ✅ Alpaca: Uses `alpaca-py` library (respects rate limits, but no explicit retry)
- ✅ Finnhub: Uses `requests.RequestException` catch (silent fail, no retry)
- ❌ **No circuit breaker** to stop requests if rate limits detected
- ❌ **No request queuing or throttling** between cycles
- ❌ **No cost monitoring** (could silently accumulate overages)

**Risk:**
- Runaway loop: If a cycle crashes mid-way and repeatedly retries, could hit rate limits
- Cost overruns: Finnhub has daily limits (e.g., 60 calls/min on Professional plan); exceeded calls may charge
- Alpaca data API: 1 connection per account; concurrent connections could fail silently

**Remediation:**
1. Add explicit retry logic for Alpaca data calls (similar to `llm_retry.py`)
2. Implement request throttling: add `time.sleep(0.5)` between API calls in sources
3. Add rate-limit detection in broker.py: catch 429/403 responses and halt gracefully
4. Log API costs/usage to `logs/api_usage.log` for monitoring
5. Set up alerts in GitHub Actions if a cycle makes >N API calls (anomaly detection)

**Risk Level:** 🔴 CRITICAL (impacts cost and reliability)

---

### ⚠️ Issue #4: Missing Error Handling Beyond Happy Path
**Status:** MOSTLY GOOD (with gaps)

**What Joe Does Right:**
- `cycle.py`: Dashboard refresh errors caught and logged, doesn't crash
- `sources/__init__.py`: Individual source failures caught, cycle continues with remaining sources
- `broker.py`: `intraday_quotes()` returns `{}` on error, never blocks
- `main.py`: Top-level catch-all logs fatal errors

**What's Missing:**
- ❌ **Alpaca news source** (`alpaca_news_source.py`): No try/except on `discover()` API call
  - If `self.client.get_news(req)` fails (timeout, 403, network error), whole source crashes
  - Fixed by: `try/except` around `self._items(self.client.get_news(req))`
  
- ❌ **Broker operations** (`broker.py`): Order submission has no timeout
  - `buy_market()`, `sell_market()`, etc. could hang indefinitely if network is slow
  - Fixed by: Add `timeout=30` to Alpaca client initialization
  
- ❌ **Brain reflection** (`reflect.py`, `digest.py`): No timeout on Claude API calls
  - If Claude is slow/overloaded, the cycle's "Persist logs" step could hang and fail
  - Fixed by: Use `timeout=60` parameter in `create_with_retry()`

- ❌ **Database operations** in reflection: If playbook.md is corrupted or in-use, could crash
  - Playbook is read/rewritten by the brain; no locking mechanism
  - Fixed by: Use `playbook.md.lock` to serialize writes

**Remediation:**
1. Add try/except to all API .discover() methods (wrap the request call)
2. Add `timeout=30` to Alpaca client and `timeout=60` to Claude client
3. Add file locking when rewriting playbook.md to prevent concurrent writes
4. Add "max wait time" check in Persist logs step: if `git pull --rebase` takes >30s, timeout and skip push

**Risk Level:** 🟡 MEDIUM (could cause stalled/failed cycles)

---

### ✅ Issue #5: N+1 Queries & Inefficient Database Access
**Status:** N/A — Not Applicable

Joe doesn't use a database. Data is persisted as JSON files (logs/, playbook.md, dashboard.md). File I/O is not loop-based. ✅

---

### ✅ Issue #6: Missing Authorization Checks
**Status:** N/A — Not Applicable

Joe is a single-user autonomous system with no web interface, API, or multi-user access. There are no authorization checks needed. ✅

---

## Additional Finding: GitHub Actions Git Failure

**Status:** CRITICAL (blocking scheduled jobs)

See `GITHUB_ACTIONS_FIX.md` for details. The "Persist logs" step fails with:
```
error: cannot pull with rebase: You have unstaged changes.
```

This prevents logs and dashboard from being committed, so digest/reflect jobs downstream cannot read today's trades.

**Fix Applied:** Modified workflow to use `git add -A` before rebase to capture all changes.

---

## Summary Table

| Issue | Joe's Status | Risk | Action |
|-------|---|---|---|
| #1: Auth tokens in repo | Good (migration pending) | 🟡 Medium | Complete Infisical migration |
| #2: RLS misconfigured | N/A | — | — |
| #3: No rate limiting | **Critical gap** | 🔴 Critical | Add retry/throttling + cost monitoring |
| #4: Error handling gaps | Good (with gaps) | 🟡 Medium | Add try/except + timeouts |
| #5: N+1 queries | N/A | — | — |
| #6: Missing authorization | N/A | — | — |

---

## Recommended Priority

**Immediate (this week):**
1. Fix GitHub Actions git failure (blocking all scheduled jobs)
2. Add Infisical migration + rotate credentials
3. Add error handling to Alpaca news source + all API calls

**Near-term (next 2 weeks):**
4. Add rate-limit retry logic + request throttling
5. Add API cost monitoring + alerts
6. Add file locking for playbook.md writes

**Later (backlog):**
7. Add comprehensive timeout handling
8. Set up anomaly detection for API call counts

---

## Brain Security Checklist

Add these checks to Joe's playbook/reflection to catch risky decisions:

```
SECURITY CHECKS (before executing each order):
- ✓ Order size respects max_position_pct (never >10% of equity)
- ✓ Total open positions < max_open_positions (never >8)
- ✓ Account equity >= $25k if day trading (PDT rule)
- ✓ Order symbol is valid (alphabetic, 1-5 chars, not OTC-pink)
- ✓ Stop loss is set (never leave naked long)
- ✓ Risk per trade <= 1% of equity
- ✓ No re-entry within 5 days of stop-loss (cooldown respected)
- ✓ Conviction level is appropriate for position size

API/SYSTEM CHECKS (daily digest):
- Check logs/api_usage.log: Are API calls within budget?
- Check GitHub Actions: Did all scheduled jobs run?
- Check git status: Are logs/playbook/dashboard committed?
```

---

## References

- Findings from: "6 Critical Issues in 25 AI-Generated Apps" (Raheel security review)
- Related docs: GITHUB_ACTIONS_FIX.md, CLAUDE.md, playbook.md
