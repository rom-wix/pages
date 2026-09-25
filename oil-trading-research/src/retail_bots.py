"""Retail-style grid / martingale / DCA bots on a CFD account (risk demonstration, E07).

Account model (ESMA retail CFD rules for commodities)
  * equity starts at 1.0 (read: 10,000 USD); leverage 1:10  => margin = 10% of notional
  * stop-out when margin level = equity / used margin <= 50%: every position is closed (the bot stops)
  * negative-balance protection: equity after a stop-out is floored at 0
  * spread/slippage `cps` per side on every fill; financing markup `fin` p.a. on |notional| per calendar day
  * the price path is the futures total-return index (TRI), so holding costs/gains from the roll
    (contango / backwardation) are already in the P&L, as with a futures-referenced CFD's swap

Timing / fills (daily bars)
  * the bot is evaluated once per day at the close.  Resting limit orders (grid entries, take-profits)
    fill at their level price if the close is through the level (so never better than the close),
    market actions (first entry, stop-out liquidation) fill at the close.  Stop-losses (martingale)
    fill at the stop level (optimistic for the bot) or at the open when the bar gaps through it
    (OHLC mode only).
  * use_hl=True: the stop-out is also checked against the intraday low/high (adverse extreme) and
    liquidates at the price where the margin level hits 50% (or at the open if it gapped through).

Bots
  grid        symmetric ("hedged") grid: a long lot every `step` lower, a short lot every `step` higher,
              each lot takes profit one step away, no stop, at most `nmax` lots per side;
              lot size fixed in units at the start (like a fixed MT4 lot)
  martingale  one position at a time, direction = sign of 20-day momentum, TP = SL = `step`;
              size doubles after each loss, resets after a win or after `kmax` consecutive losses;
              size capped so that margin <= 90% of equity
  dca         long-only "safety order" bot: base order, then a buy every `step` below the last fill with
              size x `vmult`, up to `mmax` safety orders; take profit when price >= average * (1+tp);
              no stop; restarts immediately after a take-profit; order sizes fixed in account currency
"""
from __future__ import annotations

import numpy as np
from numba import njit

MARGIN = 0.10      # 1:10
STOP_OUT = 0.50    # margin level


@njit(cache=True)
def _stop_price(A, B, M, so):
    """Price P where (A + B*P) / (M*P) = so, i.e. equity = so * margin.  Returns -1 if none."""
    den = so * M - B
    if abs(den) < 1e-15:
        return -1.0
    p = A / den
    return p if p > 0 else -1.0


@njit(cache=True)
def sim_grid(C, L, H, O, days, cps, fin, step, lot, nmax, i0, i1, use_hl):
    n = i1 - i0 + 1
    eq = np.full(n, np.nan)
    expo = np.zeros(n)
    le = np.zeros(nmax)
    se = np.zeros(nmax)
    nl = 0
    ns = 0
    cash = 1.0
    u = lot / C[i0]  # units per lot, fixed at the start
    ntr = 0
    nwin = 0
    stop_t = -1
    stop_eq = np.nan
    for t in range(i0, i1 + 1):
        P = C[t]
        if t > i0 and (nl + ns) > 0:
            cash -= u * (nl + ns) * C[t - 1] * fin * days[t] / 365.0
        # ---- stop-out checks
        A = cash - u * le[:nl].sum() + u * se[:ns].sum()   # equity(P) = A + B*P
        B = u * (nl - ns)
        M = MARGIN * u * (nl + ns)
        liq = -1.0
        if (nl + ns) > 0:
            if use_hl:
                pa = L[t] if B > 0 else H[t]
                if (A + B * pa) < STOP_OUT * M * pa or pa <= 0:
                    ps = _stop_price(A, B, M, STOP_OUT)
                    if ps <= 0:
                        ps = pa
                    po = O[t]
                    if B > 0:
                        liq = min(ps, po) if po > 0 else ps
                    else:
                        liq = max(ps, po)
            if liq < 0 and ((A + B * P) < STOP_OUT * M * P or P <= 0):
                liq = P
        if liq > 0 or ((nl + ns) > 0 and P <= 0):
            if liq <= 0:
                liq = max(P, 1e-9)
            e = A + B * liq - cps * u * (nl + ns) * abs(liq)
            e = max(e, 0.0)
            eq[t - i0:] = e
            stop_t = t
            stop_eq = e
            nl = 0
            ns = 0
            break
        # ---- take profits
        k = 0
        while k < nl:
            tp = le[k] * (1.0 + step)
            if P >= tp:
                pnl = u * (tp - le[k]) - cps * u * tp
                cash += pnl
                ntr += 1
                if pnl > 0:
                    nwin += 1
                le[k] = le[nl - 1]
                nl -= 1
            else:
                k += 1
        k = 0
        while k < ns:
            tp = se[k] * (1.0 - step)
            if P <= tp:
                pnl = u * (se[k] - tp) - cps * u * tp
                cash += pnl
                ntr += 1
                if pnl > 0:
                    nwin += 1
                se[k] = se[ns - 1]
                ns -= 1
            else:
                k += 1
        # ---- new lots (free margin must cover the new lot's margin)
        for side in range(2):
            while True:
                if side == 0:
                    if nl >= nmax:
                        break
                    if nl == 0:
                        px = P
                    else:
                        lo = le[:nl].min()
                        px = lo * (1.0 - step)
                        if P > px:
                            break
                else:
                    if ns >= nmax:
                        break
                    if ns == 0:
                        px = P
                    else:
                        hi = se[:ns].max()
                        px = hi * (1.0 + step)
                        if P < px:
                            break
                equity = cash + u * (P * nl - le[:nl].sum()) + u * (se[:ns].sum() - P * ns)
                used = MARGIN * u * (nl + ns) * P
                if equity - used < MARGIN * u * px:
                    break
                cash -= cps * u * px
                if side == 0:
                    le[nl] = px
                    nl += 1
                else:
                    se[ns] = px
                    ns += 1
        eq[t - i0] = cash + u * (P * nl - le[:nl].sum()) + u * (se[:ns].sum() - P * ns)
        expo[t - i0] = u * (nl + ns) * P / max(eq[t - i0], 1e-9)
    return eq, expo, stop_t, stop_eq, ntr, nwin


@njit(cache=True)
def sim_martingale(C, L, H, O, days, cps, fin, step, base, kmax, i0, i1, use_hl, mom_lb):
    n = i1 - i0 + 1
    eq = np.full(n, np.nan)
    expo = np.zeros(n)
    cash = 1.0
    in_pos = False
    d = 0.0
    units = 0.0
    entry = 0.0
    k = 0
    u0 = base / C[i0]
    ntr = 0
    nwin = 0
    nseq = 0
    nseq_win = 0
    stop_t = -1
    stop_eq = np.nan
    for t in range(i0, i1 + 1):
        P = C[t]
        if t > i0 and in_pos:
            cash -= units * C[t - 1] * fin * days[t] / 365.0
        if in_pos:
            A = cash - d * units * entry
            B = d * units
            M = MARGIN * units
            liq = -1.0
            if use_hl:
                pa = L[t] if d > 0 else H[t]
                if (A + B * pa) < STOP_OUT * M * pa or pa <= 0:
                    ps = _stop_price(A, B, M, STOP_OUT)
                    if ps <= 0:
                        ps = pa
                    liq = min(ps, O[t]) if d > 0 else max(ps, O[t])
            if liq < 0 and ((A + B * P) < STOP_OUT * M * P or P <= 0):
                liq = max(P, 1e-9)
            if liq > 0:
                e = max(A + B * liq - cps * units * liq, 0.0)
                eq[t - i0:] = e
                stop_t = t
                stop_eq = e
                in_pos = False
                break
            # TP / SL
            tp = entry * (1.0 + d * step)
            sl = entry * (1.0 - d * step)
            hit_tp = (P >= tp) if d > 0 else (P <= tp)
            hit_sl = (P <= sl) if d > 0 else (P >= sl)
            if use_hl:
                # adverse extreme first (conservative): an intraday touch of the stop counts
                if d > 0 and L[t] <= sl:
                    hit_sl = True
                    hit_tp = False
                if d < 0 and H[t] >= sl:
                    hit_sl = True
                    hit_tp = False
            if hit_tp or hit_sl:
                if hit_sl:
                    px = sl
                    if use_hl:
                        px = min(sl, O[t]) if d > 0 else max(sl, O[t])
                else:
                    px = tp
                pnl = d * units * (px - entry) - cps * units * px
                cash += pnl
                ntr += 1
                in_pos = False
                if pnl > 0:
                    nwin += 1
                    nseq += 1
                    nseq_win += 1
                    k = 0
                else:
                    k += 1
                    if k > kmax:
                        nseq += 1
                        k = 0
        if not in_pos:
            j = t - mom_lb if t - mom_lb >= 0 else 0
            d = 1.0 if C[t] >= C[j] else -1.0
            equity = cash
            want = u0 * (2.0 ** k)
            cap = 0.9 * equity / (MARGIN * P)
            units = min(want, cap)
            if units > 0 and equity > 0:
                entry = P
                cash -= cps * units * P
                in_pos = True
        e_now = cash + (d * units * (P - entry) if in_pos else 0.0)
        eq[t - i0] = e_now
        expo[t - i0] = (units * P / max(e_now, 1e-9)) if in_pos else 0.0
    return eq, expo, stop_t, stop_eq, ntr, nwin, nseq, nseq_win


@njit(cache=True)
def sim_dca(C, L, H, O, days, cps, fin, step, tp, vmult, mmax, gross, i0, i1, use_hl):
    n = i1 - i0 + 1
    eq = np.full(n, np.nan)
    expo = np.zeros(n)
    s = 0.0
    for i in range(mmax + 1):
        s += vmult ** i
    base = gross / s   # base-order notional as a fraction of initial equity
    cash = 1.0
    norders = 0
    units = 0.0
    cost = 0.0
    last = 0.0
    ndeal = 0
    nwin = 0
    stop_t = -1
    stop_eq = np.nan
    for t in range(i0, i1 + 1):
        P = C[t]
        if t > i0 and norders > 0:
            cash -= units * C[t - 1] * fin * days[t] / 365.0
        if norders > 0:
            A = cash - cost
            B = units
            M = MARGIN * units
            liq = -1.0
            if use_hl:
                pa = L[t]
                if (A + B * pa) < STOP_OUT * M * pa or pa <= 0:
                    ps = _stop_price(A, B, M, STOP_OUT)
                    if ps <= 0:
                        ps = pa
                    liq = min(ps, O[t])
            if liq < 0 and ((A + B * P) < STOP_OUT * M * P or P <= 0):
                liq = max(P, 1e-9)
            if liq > 0:
                e = max(A + B * liq - cps * units * liq, 0.0)
                eq[t - i0:] = e
                stop_t = t
                stop_eq = e
                norders = 0
                break
            avg = cost / units
            if P >= avg * (1.0 + tp):
                px = avg * (1.0 + tp)
                pnl = units * (px - avg) - cps * units * px
                cash += pnl
                ndeal += 1
                if pnl > 0:
                    nwin += 1
                norders = 0
                units = 0.0
                cost = 0.0
        if norders > 0:
            while norders <= mmax and P <= last * (1.0 - step):
                px = last * (1.0 - step)
                notional = base * (vmult ** norders)
                equity = cash + units * P - cost
                used = MARGIN * units * P
                if equity - used < MARGIN * notional:
                    break
                du = notional / px
                units += du
                cost += du * px
                cash -= cps * notional
                last = px
                norders += 1
        if norders == 0:
            equity = cash
            notional = base
            if equity > MARGIN * notional:
                du = notional / P
                units = du
                cost = du * P
                cash -= cps * notional
                last = P
                norders = 1
        e_now = cash + units * P - cost
        eq[t - i0] = e_now
        expo[t - i0] = units * P / max(e_now, 1e-9)
    return eq, expo, stop_t, stop_eq, ndeal, nwin
