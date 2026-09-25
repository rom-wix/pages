"""E06-B  Intraday momentum (Gao, Han, Li & Zhou 2018 JFE) adapted to NYMEX energy hours.

Target: r_last = ln P(14:30) - ln P(14:00)   (last 30 minutes before the 14:28-14:30 settlement)
Predictors (prices known at the time: last close strictly before the timestamp, max 20 min stale):
  on930  : prior session's 14:30 -> today's 09:30   (overnight + first half hour after the pit open)
  on1000 : prior session's 14:30 -> today's 10:00
  first30: 09:00 -> 09:30
  mid    : 09:00 -> 14:00
  r1330  : 13:30 -> 14:00   (analogue of Gao et al.'s 12th half-hour)
Regressions: OLS with Newey-West (5 lags) t-stats, IS 2005-2012 / OOS 2013-2020-05 / full.
Trading: at 14:00 enter (market, next bar open) in the sign of the predictor, exit 14:28 or 14:30 (market).
  variants: each predictor x {all days, |x| > trailing-250-day quantile q of |x|, q = 0.5/0.67/0.8}
  x exit {14:28, 14:30}, plus two sign-agreement combos (first30 & r1330, on930 & r1330).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from src import intraday as ix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results")
SYMS = ["XTIUSD", "XNGUSD"]
PREDS = ["on930", "on1000", "first30", "mid", "r1330"]


def build(S):
    P = lambda t: ix.px_before(S, ix.col(t), max_age=20)
    p1430 = P("14:30")
    prev1430 = ix.prev_valid(p1430, S.valid & np.isfinite(p1430))
    d = pd.DataFrame({
        "on930": np.log(P("09:30") / prev1430),
        "on1000": np.log(P("10:00") / prev1430),
        "first30": np.log(P("09:30") / P("09:00")),
        "mid": np.log(P("14:00") / P("09:00")),
        "r1330": np.log(P("14:00") / P("13:30")),
        "last": np.log(p1430 / P("14:00")),
    }, index=S.dates)
    d = d[S.valid]
    return d


def regressions(sym, d):
    rows = []
    for p, (a, b) in ix.PERIODS.items():
        x = d.copy()
        if a is not None:
            x = x[x.index >= a]
        if b is not None:
            x = x[x.index <= b]
        for pred in PREDS + ["ALL"]:
            cols = PREDS if pred == "ALL" else [pred]
            z = x[cols + ["last"]].dropna()
            # winsorise extreme returns (bad prints / 2020) at 1st/99th pct for the regression only
            lo, hi = z.quantile(0.005), z.quantile(0.995)
            z = z.clip(lo, hi, axis=1)
            res = ix.nw_ols(z["last"], z[cols], lags=5)
            for i, c in enumerate(cols):
                rows.append({"sym": sym, "period": p, "model": pred, "predictor": c, "slope": res.params[i + 1],
                             "t_nw": res.tvalues[i + 1], "r2": res.rsquared, "n": len(z)})
    return rows


def main():
    reg_rows, grid, store = [], [], {}
    for sym in SYMS:
        S = ix.session_matrix(sym)
        d = build(S)
        reg_rows += regressions(sym, d)
        rows = S.row_of(d.index)
        ep, ec = ix.px_exec(S, ix.col("14:00"), max_wait=10)
        ep, ec = ep[rows], ec[rows]
        exits = {}
        for xt in ["14:28", "14:30"]:
            xp, xc = ix.px_exec(S, ix.col(xt), max_wait=30, fallback_before=True)
            exits[xt] = (xp[rows], xc[rows])
        sig = {}
        for p in PREDS:
            x = d[p]
            sig[f"{p}|all"] = np.sign(x)
            for q in [0.5, 0.67, 0.8]:
                thr = x.abs().rolling(250, min_periods=120).quantile(q).shift(1)
                sig[f"{p}|q{q:g}"] = np.sign(x).where(x.abs() > thr, 0.0)
        sig["first30&r1330|all"] = np.sign(d["first30"]).where(np.sign(d["first30"]) == np.sign(d["r1330"]), 0.0)
        sig["on930&r1330|all"] = np.sign(d["on930"]).where(np.sign(d["on930"]) == np.sign(d["r1330"]), 0.0)
        for name, s in sig.items():
            s = s.fillna(0.0).to_numpy()
            for xt, (xp, xc) in exits.items():
                tr = ix.make_trades(S, rows, s, ep, xp, ec, xc, n_stop=0)
                ev = ix.evaluate(tr, S)
                key = f"{sym}|mom|{name}|{xt}"
                store[key] = tr
                grid.append({"key": key, "sym": sym, "family": "B_momentum", "signal": name, "exit": xt, **ev})
    R = pd.DataFrame(reg_rows)
    R.to_csv(os.path.join(OUT, "e06_B_momentum_regressions.csv"), index=False)
    G = pd.DataFrame(grid)
    G.to_csv(os.path.join(OUT, "e06_B_momentum_grid.csv"), index=False)
    pd.to_pickle(store, os.path.join(ix.CACHE, "e06_B_trades.pkl"))
    pd.set_option("display.width", 250)
    uni = R[R.model != "ALL"].pivot_table(index=["sym", "predictor"], columns="period", values=["slope", "t_nw", "r2"])
    print("univariate predictive regressions of r(14:00->14:30):")
    print(uni.round(4).to_string())
    multi = R[R.model == "ALL"].pivot_table(index=["sym", "predictor"], columns="period", values=["slope", "t_nw"])
    print("\nmultivariate:")
    print(multi.round(4).to_string())
    show = ["key", "is_sharpe", "oos_sharpe", "full_sharpe", "full_gross_sharpe", "oos_gross_sharpe", "full_trades_py",
            "full_avg_bps", "full_avg_gross_bps", "full_hit"]
    for sym in SYMS:
        g = G[G.sym == sym].sort_values("is_sharpe", ascending=False)
        print(f"\n{sym}: {len(g)} variants, top 12 by IS net Sharpe")
        print(g[show].head(12).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
