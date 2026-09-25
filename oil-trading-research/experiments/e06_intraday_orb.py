"""E06-A  Opening-range breakout (ORB) on XTIUSD / XNGUSD 1-minute Oanda CFD mids, 2005-2020-05.

Rules (all decisions causal, resting stop orders simulated on the minute OHLC path):
  * Range = high/low of the first N minutes after the anchor (08:00 / 09:00 / 09:30 NY), N in 15/30/60.
  * Buy stop at range high, sell stop at range low, active from the end of the range until 60 minutes
    before the exit.  At most one trade per day, optionally one reversal (opposite stop entry after
    the first trade is stopped out).
  * Protective stop: none / opposite range edge / range midpoint.
  * Exit at 14:30 NY (settlement) or 16:55 by market order (next bar open).
  * Filters (chosen on IS): narrow range (width / trailing-20-day mean width < 1.0 or < 0.75),
    prior-day trend (trade only in the direction of the previous session's close-to-close return).
  * "stretch" family = Crabel ORB as tested by Holmberg, Lonnbark & Lundstrom (2013): stop entries at
    anchor open +/- k * (trailing 10-day mean of min(high-open, open-low)), k in 0.5/1/2.
Costs: 2 x COST_PER_SIDE + STOP_SLIPPAGE per stop-type side (entry stop, protective stop).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from src import intraday as ix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results")
SYMS = ["XTIUSD", "XNGUSD"]

STOPS = {"none": (0, False), "opp": (1, False), "mid": (2, False), "opp_rev": (1, True), "mid_rev": (2, True)}
FILTERS = ["none", "narrow1.0", "narrow0.75", "trend", "trend+narrow1.0"]


def day_levels(S, a, N):
    """Opening range [a, a+N) high/low with a minimum bar count (NG is sparse)."""
    sl = slice(a, a + N)
    cnt = (~np.isnan(S.C[:, sl])).sum(axis=1)
    with np.errstate(all="ignore"):
        hi = np.nanmax(S.H[:, sl], axis=1)
        lo = np.nanmin(S.L[:, sl], axis=1)
    ok = S.valid & (cnt >= max(3, N // 5)) & (hi > lo)
    return np.where(ok, hi, np.nan), np.where(ok, lo, np.nan)


def prior_day_sign(S):
    """Sign of the most recent completed session's close-to-close (17:00 -> 17:00) return."""
    s = pd.Series(np.where(S.valid, ix.daily_close(S).to_numpy(), np.nan))
    vv = s.dropna()
    r = np.log(vv / vv.shift(1))
    prev = r.reindex(s.index).ffill().shift(1)  # known before today's session opens
    return np.sign(prev).fillna(0).to_numpy()


def run_orb(S, hi, lo, start, exit_c, stop_mode, rev, dir_allowed, last_entry=None):
    last_entry = exit_c - 60 if last_entry is None else last_entry
    st = np.full(S.n, start, dtype=np.int64) if np.ndim(start) == 0 else start.astype(np.int64)
    res = ix.orb_kernel(S.O, S.H, S.L, S.C, hi.astype(np.float64), lo.astype(np.float64), st,
                        int(last_entry), int(exit_c), int(stop_mode), bool(rev), dir_allowed.astype(np.int64))
    rows, d, ep, xp, ec, xc, ns = res
    return ix.make_trades(S, rows, d, ep, xp, ec, xc, n_stop=ns)


def main():
    t0 = time.time()
    rows = []
    trades_store = {}
    for sym in SYMS:
        S = ix.session_matrix(sym)
        trend = prior_day_sign(S)
        both = np.zeros(S.n, dtype=np.int64)
        # ---------------- classic opening range ----------------
        for anchor in ["08:00", "09:00", "09:30"]:
            a = ix.col(anchor)
            for N in [15, 30, 60]:
                hi, lo = day_levels(S, a, N)
                width = (hi - lo) / ((hi + lo) / 2)
                ratio = width / ix.trailing_mean(width, np.isfinite(width), 20, 10)
                for exit_t in ["14:30", "16:55"]:
                    xc = ix.col(exit_t)
                    for sname, (smode, rev) in STOPS.items():
                        for filt in FILTERS:
                            h2, l2, da = hi.copy(), lo.copy(), both.copy()
                            if "narrow" in filt:
                                thr = float(filt.split("narrow")[1])
                                m = ~(ratio < thr)
                                h2[m] = np.nan
                                l2[m] = np.nan
                            if "trend" in filt:
                                da = trend.astype(np.int64)
                                h2[da == 0] = np.nan
                            tr = run_orb(S, h2, l2, a + N, xc, smode, rev, da)
                            ev = ix.evaluate(tr, S)
                            key = f"{sym}|orb|{anchor}|{N}|{exit_t}|{sname}|{filt}"
                            trades_store[key] = tr
                            rows.append({"key": key, "sym": sym, "family": "A_orb", "kind": "range", "anchor": anchor,
                                         "N": N, "exit": exit_t, "stop": sname, "filter": filt, **ev})
        # ---------------- Crabel stretch (Holmberg et al. 2013) ----------------
        for anchor in ["08:00", "09:00", "09:30"]:
            a = ix.col(anchor)
            o_anchor, _ = ix.px_exec(S, a, max_wait=10)
            for exit_t in ["14:30", "16:55"]:
                xc = ix.col(exit_t)
                with np.errstate(all="ignore"):
                    dh = np.nanmax(S.H[:, a:xc], axis=1)
                    dl = np.nanmin(S.L[:, a:xc], axis=1)
                stretch_raw = np.minimum(dh - o_anchor, o_anchor - dl) / o_anchor
                stretch = ix.trailing_mean(stretch_raw, S.valid & np.isfinite(stretch_raw), 10, 5)
                for k in [0.5, 1.0, 2.0]:
                    hi = np.where(S.valid, o_anchor * (1 + k * stretch), np.nan)
                    lo = np.where(S.valid, o_anchor * (1 - k * stretch), np.nan)
                    for sname in ["none", "opp_rev"]:
                        smode, rev = STOPS[sname]
                        tr = run_orb(S, hi, lo, a, xc, smode, rev, both)
                        ev = ix.evaluate(tr, S)
                        key = f"{sym}|stretch|{anchor}|k{k}|{exit_t}|{sname}|none"
                        trades_store[key] = tr
                        rows.append({"key": key, "sym": sym, "family": "A_orb", "kind": "stretch", "anchor": anchor,
                                     "N": k, "exit": exit_t, "stop": sname, "filter": "none", **ev})
        print(sym, "done", round(time.time() - t0, 1), "s", flush=True)
    G = pd.DataFrame(rows)
    G.to_csv(os.path.join(OUT, "e06_A_orb_grid.csv"), index=False)
    pd.to_pickle(trades_store, os.path.join(ix.CACHE, "e06_A_trades.pkl"))
    show = ["key", "is_sharpe", "oos_sharpe", "full_sharpe", "full_gross_sharpe", "full_trades_py", "full_avg_bps",
            "full_hit", "is_avg_gross_bps", "oos_avg_gross_bps"]
    pd.set_option("display.width", 250)
    for sym in SYMS:
        g = G[G.sym == sym].sort_values("is_sharpe", ascending=False)
        print(f"\n=== {sym}: {len(g)} variants; top 15 by IS net Sharpe")
        print(g[show].head(15).round(3).to_string(index=False))
        base = g[g.key == f"{sym}|orb|09:00|30|14:30|none|none"]
        print("canonical 09:00/30m/14:30/no stop:")
        print(base[show].round(3).to_string(index=False))
        print("share of variants with OOS net Sharpe > 0:", round((g.oos_sharpe > 0).mean(), 3),
              " gross > 0:", round((g.oos_sharpe_0x > 0).mean(), 3))


if __name__ == "__main__":
    main()
