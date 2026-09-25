"""The recommended system as explicit, reusable rules.

SYSTEM 1 — "Oil Flag Breakout" (daily bars; WTI or Brent)
  1. Impulse : a net close-to-close move over 4, 5 or 6 trading days of at least 1.5 x ATR(20)
               (ATR measured the day before the move starts).
  2. Pause   : the next 4, 5 or 6 daily bars form a box (high R, low S) whose height is <= 50% of the impulse
               and which gives back <= 61.8% of it.
  3. Entry   : buy-stop at R after an up-impulse (sell-stop at S after a down-impulse), valid 10 trading days.
               Cancel if the opposite edge of the box breaks first.
  4. Stop    : opposite edge of the box (never closer than 0.5 x ATR).
  5. Exit    : half the position at the measured move (entry +/- 1.0 x impulse size, 20-day time stop);
               the other half trails at 3.5 x ATR from the daily close (60-day time stop).
  One position at a time per market.
  A+ filter  : take the setup only if ATR(20)/price is above its median of the previous 252 days
               (i.e. the market is "in play").  Recommended default.

All (n, m) combinations are scanned; overlapping setups are resolved by the one-position rule.
"""
import itertools
import numpy as np, pandas as pd
from ogslib import Market, detect_flags, run_tickets, non_overlap, set_costs
import strategies as S

PARAMS = dict(imp_n=(4, 5, 6), imp_k=1.5, cons_m=(4, 5, 6), box_f=0.5, max_ret=0.618, E=10)
EXITS = {
    'MM1': dict(stop='box', tgt=('mm', 1.0), T=20),
    'R2': dict(stop='box', tgt=('R', 2.0), T=20),
    'TR': dict(stop='box', tgt=('none',), trail=3.5, T=60),
}


def vol_percentile(mk, lookback=252):
    atrp = pd.Series(mk.atr / mk.c)
    return atrp.rolling(lookback, min_periods=126).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True).values


def setups(mk, params=None):
    p = dict(PARAMS, **(params or {}))
    ns = p['imp_n'] if isinstance(p['imp_n'], (tuple, list)) else (p['imp_n'],)
    ms = p['cons_m'] if isinstance(p['cons_m'], (tuple, list)) else (p['cons_m'],)
    ks = p['imp_k'] if isinstance(p['imp_k'], (tuple, list)) else (p['imp_k'],)
    sts = [detect_flags(mk.h, mk.l, mk.c, mk.atr, n, k, m, p['box_f'], p['max_ret'])
           for n, k, m in itertools.product(ns, ks, ms)]
    sts = [s for s in sts if len(s)]
    if not sts:
        return np.empty((0, 10))
    st = np.vstack(sts)
    return st[np.argsort(st[:, 0], kind='stable')]


def filter_vol(mk, st):
    if not len(st):
        return st
    vp = vol_percentile(mk)
    return st[vp[st[:, 0].astype(int)] >= 0.5]


def trades_from_setups(mk, st, exit='HYB', E=10, cost_mult=1.0):
    if exit == 'HYB':
        a = run_tickets(mk, S.cont_breakout(st, E=E, **EXITS['MM1']), cost_mult)
        b = run_tickets(mk, S.cont_breakout(st, E=E, **EXITS['TR']), cost_mult)
        tr = a.copy()
        tr['R'] = 0.5 * a.R.values + 0.5 * b.R.values
        tr['exit_f'] = np.maximum(a.exit_f.values, b.exit_f.values)
        tr['exit_c'] = np.maximum(a.exit_c.values, b.exit_c.values)
        tr['exit_px_mm'] = a.exit_px.values
        tr['exit_px_tr'] = b.exit_px.values
        tr['exit_c_mm'] = a.exit_c.values
        tr['exit_c_tr'] = b.exit_c.values
        tr['R_mm'] = a.R.values
        tr['R_tr'] = b.R.values
        tr['why_mm'] = a.reason.values
        tr['why_tr'] = b.reason.values
    else:
        tr = run_tickets(mk, S.cont_breakout(st, E=E, **EXITS[exit]), cost_mult)
    return tr


def run_system(mk, exit='HYB', vol_filter=True, regime='futures', params=None, cost_mult=1.0):
    """Non-overlapping trades (one position at a time) with full detail."""
    p = dict(PARAMS, **(params or {}))
    st = setups(mk, p)
    if vol_filter:
        st = filter_vol(mk, st)
    set_costs(mk, regime)
    tr = trades_from_setups(mk, st, exit, p['E'], cost_mult)
    tr = non_overlap(tr)
    if len(tr) == 0:
        return tr
    k = tr.setup.values.astype(int)
    tr['entry_t'] = mk.t[tr.entry_c.values.astype(int)]
    tr['exit_t'] = mk.t[tr.exit_c.values.astype(int)]
    tr['arm_t'] = mk.t[st[k, 0].astype(int)]
    tr['imp_start_t'] = mk.t[st[k, 7].astype(int)]
    tr['imp_end_t'] = mk.t[st[k, 8].astype(int)]
    tr['dir'] = st[k, 1]
    tr['P0'] = st[k, 2]
    tr['P1'] = st[k, 3]
    tr['box_hi'] = st[k, 4]
    tr['box_lo'] = st[k, 5]
    tr['impulse'] = st[k, 9]
    tr['atr'] = st[k, 6]
    lvl = np.where(tr['dir'] > 0, st[k, 4], st[k, 5])
    stop = np.where(tr['dir'] > 0, st[k, 5], st[k, 4])
    tr['stop_px'] = np.where(tr['dir'] > 0, np.minimum(stop, lvl - 0.5 * st[k, 6]), np.maximum(stop, lvl + 0.5 * st[k, 6]))
    tr['target_px'] = lvl + tr['dir'] * st[k, 9]
    return tr.reset_index(drop=True)


def equity(tr, risk=0.01):
    """Compounded equity at fixed-fractional risk per trade, stepped at exit dates."""
    if len(tr) == 0:
        return pd.Series(dtype=float)
    x = tr.sort_values('exit_t')
    return pd.Series(np.cumprod(1 + risk * x.R.values), index=x.exit_t.values)


def perf(tr, risk=0.01, start=None, end=None):
    if len(tr) == 0:
        return dict(n=0)
    R = tr.R.values
    eq = equity(tr, risk)
    start = pd.Timestamp(start) if start is not None else tr.entry_t.min()
    end = pd.Timestamp(end) if end is not None else tr.exit_t.max()
    yrs = max((end - start).days / 365.25, 0.5)
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    dd = (1 - eq / np.maximum.accumulate(np.r_[1.0, eq.values])[1:]).max()
    ddR = (np.maximum.accumulate(np.r_[0, np.cumsum(R)]) - np.r_[0, np.cumsum(R)]).max()
    w = R[R > 0].sum(); l = -R[R < 0].sum()
    return dict(n=len(R), per_yr=len(R) / yrs, win=(R > 0).mean(), avgR=R.mean(), medR=np.median(R),
                pf=w / l if l > 0 else np.inf, sumR=R.sum(), maxddR=ddR, cagr=cagr, maxdd=dd,
                best=R.max(), worst=R.min(), t=R.mean() / R.std(ddof=1) * np.sqrt(len(R)) if len(R) > 2 else np.nan)
