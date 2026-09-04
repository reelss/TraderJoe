"""One trading cycle — the loop Joe runs once an hour during market hours.

Reddit scan -> build candidates (trending + current holdings) -> fetch bars ->
indicators -> brain decision -> protective exits + risk vetting -> execute -> log.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import logbook as log
from .brain import Brain
from .broker import Broker
from .config import STRATEGY, UNIVERSE
from .earnings import earnings_context
from .economic import upcoming_macro_events
from .indicators import snapshot
from .insider import insider_signal
from .counterfactual import log_passes, resolve_pending
from .risk import (vet_orders, daily_loss_tripped, pdt_locked,
                   cooling_off_symbols, desired_stops)
from .regime import market_regime
from .sectors import sector_exposure, is_sector_etf
from .sources import scan_all


def _passes_filters(tech: dict) -> bool:
    if tech.get("insufficient_data"):
        return False
    price = tech.get("price", 0)
    dv = tech.get("avg_dollar_vol_20d", 0)
    return (UNIVERSE.min_price <= price <= UNIVERSE.max_price
            and dv >= UNIVERSE.min_avg_dollar_volume)


def _refresh_live_dashboard() -> None:
    """Regenerate + publish the dashboard so the live page tracks each cycle."""
    try:
        from .dashboard_page import build_dashboard
        build_dashboard()
        from .publish import publish_dashboard
        publish_dashboard()
    except Exception as exc:
        log.info(f"Dashboard refresh/publish failed: {exc!r}")


def run_cycle(force: bool = False, eod_mode: bool = False) -> None:
    broker = Broker()
    if not force and not broker.is_market_open():
        log.info("Market closed — skipping cycle.")
        return
    # Always refresh the live dashboard after a market-hours cycle, even on
    # no-trade hours, so positions and P&L stay current.
    try:
        _trade(broker, eod_mode=eod_mode)
    except Exception as e:
        # Surface cycle failures immediately — a silent exception means Joe
        # stopped trading without anyone knowing. Alert, then re-raise so the
        # scheduler records a non-zero exit code.
        try:
            from .digest import send_to_slack
            send_to_slack(f"🚨 Joe cycle FAILED: {type(e).__name__}: {e}")
        except Exception as alert_exc:
            log.info(f"Cycle-failure Slack alert also failed: {alert_exc!r}")
        raise
    finally:
        _refresh_live_dashboard()


def _trade(broker: Broker, eod_mode: bool = False) -> None:
    if eod_mode:
        log.info("EOD mode: exits and management only — no new buys")
    account = broker.account()
    positions = broker.positions()
    log.log_equity(account["equity"], account["cash"], len(positions))
    log.info(f"Equity ${account['equity']:.2f} | cash ${account['cash']:.2f} "
             f"| {len(positions)} open positions")

    # Enrich positions with hold_days (days since entry) and a stale flag.
    # Used by vet_orders for the time-based stale exit and by the brain to
    # flag positions that are dead money and should be re-evaluated.
    from .config import RISK as _RISK
    for p in positions:
        buy_ts = log.buy_date_for(p["symbol"])
        if buy_ts:
            try:
                hd = (datetime.now(timezone.utc) - datetime.fromisoformat(buy_ts)).days
                p["hold_days"] = hd
                p["stale"] = (hd >= _RISK.stale_flag_days
                               and p["unrealized_plpc"] < _RISK.stale_exit_max_gain_pct * 2)
            except Exception:
                p["hold_days"] = None
                p["stale"] = False
        else:
            p["hold_days"] = None
            p["stale"] = False

    # Market regime: SPY trend + VIX fear filter.
    regime = market_regime(broker)
    vix_str = f" | VIX {regime.get('vix')} ({regime.get('vix_tier')})" if regime.get('vix') else ""
    log.info(f"Regime: {regime['regime']} (SPY {regime.get('price')} vs "
             f"{regime.get('sma_window')}d SMA {regime.get('sma')}){vix_str}")

    # Sector concentration across current holdings, measured against TOTAL
    # EQUITY (not invested-only) so cash doesn't make every sector read as
    # concentrated and self-lock new deployment.
    exposure = sector_exposure(positions, equity=account["equity"])
    if exposure["concentrated"]:
        log.info(f"Sector concentration warning: {exposure['concentrated']} >= 30% of equity")
    regime["sector_exposure"] = exposure

    # Deployment context: idle cash in a risk-on regime is a decision with a
    # cost, not a neutral default. Surface it so the brain (and the nightly
    # reflection) treat under-deployment as something to justify.
    invested = sum(p["market_value"] for p in positions)
    deployed_pct = round(invested / account["equity"], 3) if account["equity"] else 0.0
    regime["deployment"] = {
        "deployed_pct": deployed_pct,
        "target_pct": STRATEGY.min_deploy_pct,
        "under_target": regime["risk_on"] and deployed_pct < STRATEGY.min_deploy_pct,
    }
    if regime["deployment"]["under_target"]:
        log.info(f"Deployment {deployed_pct:.0%} < {STRATEGY.min_deploy_pct:.0%} target (risk-on) "
                 "— brain should name what's blocking capital")

    # Economic calendar — upcoming high-impact macro events (Fed, CPI, NFP).
    # Surfaced in regime so the brain factors them into sizing and risk.
    try:
        macro_events = upcoming_macro_events()
        if macro_events:
            regime["upcoming_macro_events"] = macro_events
            log.info(f"Upcoming macro events: {[e['event'] for e in macro_events[:3]]}")
    except Exception as exc:
        log.info(f"Economic calendar unavailable ({exc!r}).")

    # PDT awareness: positions opened today can't be sold today (same-day round
    # trip = a day trade). Stops/targets/sells only act on prior-day positions.
    opened_today = broker.symbols_bought_today()
    if not regime["risk_on"]:
        log.info("Market risk-off — managing exits only, no new entries.")
    if pdt_locked(account):
        log.info(f"PDT day-trade limit reached (count={account.get('daytrade_count')}) "
                 f"— no new entries until day trades age off (~5 business days).")
    if daily_loss_tripped(account):
        log.info("Daily loss breaker tripped — no new buys this session.")

    # Re-entry cooldown: symbols stopped out in the last N days are blocked.
    # Filter before discovery so the brain never wastes reasoning on them.
    cooling_off = cooling_off_symbols()
    if cooling_off:
        log.info(f"Re-entry cooldown active: {', '.join(sorted(cooling_off))}")

    # 1) Discover candidates across all sources (news + Reddit + Finnhub).
    #    Pass the existing broker so sources needing bars (e.g. sector_rs) reuse
    #    it rather than opening a second Alpaca client + duplicate bar fetch.
    ranked = scan_all(broker)
    trending = ranked[: UNIVERSE.max_candidates]
    # Guaranteed seats past the news-driven cap. Attention-ranked discovery buries
    # both of these — watchlist names and sector ETFs carry no headline volume, so
    # they land in the 30s while news names fill the top 12. A priority Joe can't
    # see is a priority he can't buy, and the ETF can't close the deployment gap
    # from outside the candidate list.
    trending += [t for t in ranked[UNIVERSE.max_candidates:]
                 if "watchlist" in t.get("sources", {})
                 or is_sector_etf(t["symbol"])]
    signal_by_sym = {t["symbol"]: t for t in trending}
    symbols = sorted(set([t["symbol"] for t in trending]
                         + [p["symbol"] for p in positions]))
    if not symbols:
        log.info("No candidates this cycle.")
        return

    # 2) Technicals. SPY is included for relative-strength computation but
    #    never added to candidates — it's stripped out before the loop.
    bars = broker.daily_bars(sorted(set(symbols) | {"SPY"}))
    spy_df = bars.get("SPY")
    spy_ret_20d: float | None = None
    if spy_df is not None and len(spy_df) >= 21:
        spy_ret_20d = float(spy_df["close"].iloc[-1] / spy_df["close"].iloc[-21] - 1)

    candidates = []
    tech_by_sym: dict[str, dict] = {}
    for sym in symbols:
        tech = snapshot(bars.get(sym), spy_ret_20d=spy_ret_20d)
        tech_by_sym[sym] = tech  # held positions need this for exit stops too
        is_held = any(p["symbol"] == sym for p in positions)
        if not is_held and not _passes_filters(tech):
            continue  # new names must clear liquidity/price filters
        candidates.append({
            "symbol": sym,
            "held": is_held,
            "technicals": tech,
            "signal": signal_by_sym.get(sym, {"weighted_mentions": 0,
                                              "sentiment": 0.0, "sources": {}}),
        })

    # 2b) Live intraday price overlay — replace yesterday's close with the current
    #     trade price, and add today's change % and volume so the brain sees fresh
    #     data rather than a price that may be 24 hours stale.
    try:
        live = broker.intraday_quotes(symbols)
        for sym, q in live.items():
            if sym not in tech_by_sym or not q.get("price"):
                continue
            tech = tech_by_sym[sym]
            tech["price"] = q["price"]
            tech["change_today_pct"] = q.get("change_today_pct")
            tech["intraday_high"] = q.get("intraday_high")
            tech["intraday_low"] = q.get("intraday_low")
            ct = q.get("change_today_pct") or 0.0
            tech["already_extended_today"] = ct > 0.10
            # Rough intraday vol activity: log if running 2x+ normal even partially
            vol_today = q.get("vol_today")
            avg_dv = tech.get("avg_dollar_vol_20d", 0)
            if vol_today and avg_dv and q.get("price"):
                tech["vol_today"] = vol_today
        if live:
            log.info(f"Live price overlay applied for {len(live)} symbols.")
    except Exception as exc:
        log.info(f"Intraday price overlay failed ({exc!r}) — using prior-day closes.")

    # 2c) Earnings calendar — fetch in parallel for all candidates.
    # Best-effort: if Yahoo Finance is unreliable this cycle, data is None and
    # Joe ignores it; the cycle never fails due to an earnings lookup.
    candidate_syms = [c["symbol"] for c in candidates]
    earns = earnings_context(candidate_syms)
    for c in candidates:
        c["earnings"] = earns.get(c["symbol"], {"days_to_earnings": None, "earnings_soon": False})
    # Log any imminent earnings so they're visible in the log
    soon = [c["symbol"] for c in candidates if c["earnings"].get("earnings_soon")]
    if soon:
        log.info(f"Earnings within 5 days: {', '.join(soon)}")

    # 2d) Insider buying — flag candidates with recent open-market purchases.
    try:
        insider_data = insider_signal(candidate_syms)
        for c in candidates:
            c["insider"] = insider_data.get(c["symbol"], {"net_buying": False})
        buying = [c["symbol"] for c in candidates if c.get("insider", {}).get("net_buying")]
        if buying:
            log.info(f"Insider net buying (last 30d): {', '.join(buying)}")
    except Exception as exc:
        log.info(f"Insider signal unavailable ({exc!r}).")

    # Remove cooling-off symbols from candidates (held positions are never filtered —
    # we still need to manage something we own, we just won't re-enter it).
    if cooling_off:
        before = len(candidates)
        candidates = [c for c in candidates if c["held"] or c["symbol"] not in cooling_off]
        removed = before - len(candidates)
        if removed:
            log.info(f"Filtered {removed} cooling-off symbol(s) from candidates.")

    if not candidates:
        log.info("No candidates passed filters.")
        return
    log.info(f"{len(candidates)} candidates -> brain")

    # 3) Brain decision.
    result = Brain().decide(account, positions, candidates, regime)
    log.info(f"Market note: {result.get('market_note', '')}")
    decisions = result.get("decisions", [])
    for d in decisions:
        log.log_decision(d.get("symbol", "?"), d.get("action", "?"),
                         d.get("reasoning", ""), conviction=d.get("conviction"),
                         target_pct=d.get("target_pct"))

    # 3b) Counterfactual tracking: log passes, resolve pending ones.
    try:
        log_passes(candidates, decisions)
        resolve_pending(tech_by_sym)
    except Exception as exc:
        log.info(f"Counterfactual logging failed (non-fatal): {exc!r}")

    # 4) Risk-vet (PDT-aware) and execute. Whole-share market buys; in-cycle
    #    stop/target/brain exits on prior-day positions only.
    #    Build per-candidate hard-gate metadata so the risk module enforces the
    #    SMA200 / earnings / sector gates in code (not just in the brain prompt).
    meta_by_sym = {
        c["symbol"].upper(): {
            "above_sma200": c.get("technicals", {}).get("above_sma200"),
            "earnings_soon": bool(c.get("earnings", {}).get("earnings_soon")),
        }
        for c in candidates
    }
    orders = vet_orders(decisions, account, positions,
                        tech_by_sym, opened_today, risk_on=regime["risk_on"],
                        meta_by_sym=meta_by_sym, eod_mode=eod_mode,
                        pending_buys=broker.pending_buys())
    for o in orders:
        try:
            if o["side"] == "buy":
                res = broker.buy_market(o["symbol"], o["qty"])
                px = tech_by_sym.get(o["symbol"], {}).get("price")
                # Record which discovery source(s) surfaced this name so the
                # weekly review can measure which signals actually make money —
                # source weights were guesses until now.
                srcs = sorted(signal_by_sym.get(o["symbol"], {})
                              .get("sources", {}).keys())
                log.log_trade(o["symbol"], "buy", o["qty"], None, res["status"],
                              reason=o["reason"], conviction=o.get("conviction"),
                              stop_pct=o.get("stop_pct"),
                              sources=srcs or ["held_or_unknown"])
                log.info(f"BUY {o['qty']} {o['symbol']} @~${px:.2f} "
                         f"(stop {o.get('stop_pct', 0):.1%}) -> {res['status']}")
            else:
                exit_fraction = o.get("exit_fraction", 1.0)
                exit_qty = o.get("exit_qty")
                is_partial = exit_fraction < 1.0 and exit_qty is not None
                if is_partial:
                    res = broker.partial_exit(o["symbol"], exit_qty)
                else:
                    res = broker.exit_position(o["symbol"])
                buy_ts = log.buy_date_for(o["symbol"])
                hold_days: int | None = None
                if buy_ts:
                    try:
                        hold_days = (datetime.now(timezone.utc)
                                     - datetime.fromisoformat(buy_ts)).days
                    except Exception:
                        pass
                log.log_trade(o["symbol"], "sell",
                              exit_qty if is_partial else None,
                              None, res["status"],
                              reason=o["reason"], conviction=o.get("conviction"),
                              plpc=o.get("plpc"),
                              entry_price=o.get("entry_price"),
                              exit_price=tech_by_sym.get(o["symbol"], {}).get("price"),
                              hold_days=hold_days,
                              partial=is_partial,
                              exit_fraction=exit_fraction if is_partial else None)
                action_str = f"PARTIAL EXIT {exit_fraction:.0%}" if is_partial else "EXIT"
                log.info(f"{action_str} {o['symbol']} ({o['reason']}, "
                         f"{o.get('plpc',0):+.1%}) -> {res['status']}")
        except Exception as exc:
            log.log_trade(o["symbol"], o["side"], o.get("qty"), None,
                          "error", error=str(exc))
            log.info(f"Order FAILED {o['symbol']}: {exc}")

    _sync_protective_stops(broker, tech_by_sym, opened_today)

    log.info("Cycle complete.")


def _pending_sell_symbols(broker: Broker) -> set[str]:
    """Symbols with an unfilled SELL order — already on their way out."""
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        orders = broker.trading.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=200))
        return {o.symbol for o in orders if str(o.side).endswith("SELL")}
    except Exception:
        return set()


def _sync_protective_stops(broker: Broker, tech_by_sym: dict[str, dict],
                           opened_today: set[str]) -> None:
    """Keep a resting GTC stop at the broker for every prior-day position.

    Joe's in-cycle stop check only runs hourly during market hours, so an
    overnight gap-down blows straight through the intended exit — that's how
    AVGO closed at -14% against a 9% stop ceiling (2026-06-04). A resting stop
    fires at the open instead. The price tracks the same ladder the in-cycle
    logic uses, so it ratchets up as a winner runs.

    Best-effort throughout: protection failures are logged, never fatal.
    """
    try:
        positions = broker.positions()          # re-read: exits may have closed some
        if not positions:
            return
        want = desired_stops(positions, tech_by_sym, opened_today)
        have = broker.resting_stops()
        qty_by_sym = {p["symbol"]: int(float(p["qty"])) for p in positions}
        # Skip anything with a pending SELL: this cycle's exits still show as
        # open positions, but their shares are reserved for the sell order, so
        # a stop is both impossible ("insufficient qty available") and pointless.
        for sym in _pending_sell_symbols(broker):
            want.pop(sym, None)

        px_by_sym = {p["symbol"]: p.get("current_price") for p in positions}
        for sym, stop_price in want.items():
            qty = qty_by_sym.get(sym, 0)
            if qty < 1:
                continue
            # A sell-stop must sit below the market. If the position has already
            # traded through its stop level, a resting order is invalid (broker
            # rejects it) and the wrong tool anyway — the in-cycle exit check
            # closes it on this same pass.
            cur = px_by_sym.get(sym)
            if cur and stop_price >= cur:
                log.info(f"{sym} already below stop level "
                         f"(${cur:.2f} <= ${stop_price:.2f}) — exit handles it, "
                         "no resting stop placed")
                continue
            existing = have.get(sym)
            if existing:
                px, eqty = existing.get("stop_price"), existing.get("qty")
                # RATCHET INVARIANT: a protective stop only ever moves UP.
                # Never widen it — missing/degraded technicals would otherwise
                # compute a looser stop and silently reduce protection on a
                # position that is already protected.
                if px and stop_price < px and eqty == qty:
                    continue
                # Otherwise replace only on meaningful upward drift (>0.5%) or a
                # qty mismatch after a partial exit — avoids per-cycle churn.
                if (px and abs(px - stop_price) / stop_price < 0.005
                        and eqty == qty):
                    continue
                broker.cancel_order(existing["id"])
            if broker.place_stop(sym, qty, stop_price):
                log.info(f"protective stop {sym} @ ${stop_price:.2f} ({qty}sh)")

        # Drop stale stops for symbols no longer held.
        for sym, o in have.items():
            if sym not in qty_by_sym:
                broker.cancel_order(o["id"])
    except Exception as exc:
        log.info(f"Protective stop sync failed (non-fatal): {exc!r}")
