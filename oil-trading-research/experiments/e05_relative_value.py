"""E05 - Relative value: Brent-WTI spread, oil/gas ratio, crack-spread signal.

Spread trade = long leg A / short leg B, equal notional; P&L = w * (rA - rB) - costs on both legs.
Datasets:
  near : BRENT_W (~2nd month) vs CRUDE_ICE (~2nd month WTI), settlement-synchronous, 2006-2024
  deferred: BRENT_W vs CRUDE_W (Dec WTI), 1990-2024 (mismatched maturities -> noisier)
  spot : EIA Brent FOB vs WTI Cushing (1987-2026). Brent is assessed hours before WTI -> non-synchronous;
         lag>=2 is mandatory to avoid fake mean-reversion profits.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from src import backtest as bt, costs
from src import signals as sg
from src.data import futures_daily, spot_daily

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def pair_backtest(rA, rB, level_spread, signal_fn, symA, symB, target_vol=0.10, lag=1, cost_mult=1.0,
                  fin=costs.FIN_MARKUP):
    idx = rA.index.intersection(rB.index).intersection(level_spread.index)
    rA, rB, s = rA.reindex(idx).fillna(0), rB.reindex(idx).fillna(0), level_spread.reindex(idx).ffill()
    spr_ret = rA - rB
    sig = signal_fn(s, spr_ret).reindex(idx).fillna(0.0)
    vol = bt.ewma_vol(spr_ret, 60).clip(lower=0.03)
    w = (sig * target_vol / vol).clip(-3, 3).fillna(0.0)
    held = w.shift(lag).fillna(0.0)
    trade = held.diff().abs().fillna(held.abs())
    days = pd.Series(idx, index=idx).diff().dt.days.fillna(1)
    tcost = trade * (costs.per_side(symA, cost_mult) + costs.per_side(symB, cost_mult))
    fcost = 2 * held.abs() * fin * days / 365
    gross = held * spr_ret
    net = gross - tcost - fcost
    res = pd.DataFrame({"gross": gross, "net": net, "tcost": tcost, "fcost": fcost, "held": held,
                        "trade": trade}).iloc[260:]
    return res


def z_revert(n, entry=None):
    def f(s, r):
        z = sg.zscore(s, n)
        if entry is None:
            return (-z / 2).clip(-1, 1)
        pos = np.zeros(len(z)); cur = 0.0
        for i, zv in enumerate(z.to_numpy()):
            if np.isnan(zv):
                continue
            if cur == 0:
                if zv > entry:
                    cur = -1.0
                elif zv < -entry:
                    cur = 1.0
            elif cur < 0 and zv < 0.25:   # short spread exits once z has reverted
                cur = 0.0
            elif cur > 0 and zv > -0.25:
                cur = 0.0
            pos[i] = cur
        return pd.Series(pos, index=z.index)
    return f


def spread_trend(fast):
    def f(s, r):
        tri = np.exp(r.cumsum())
        return sg.ewmac(tri, r, fast)
    return f


def run_all():
    rows = []
    bw, ci, cw = futures_daily("BRENT_W"), futures_daily("CRUDE_ICE"), futures_daily("CRUDE_W")
    sp = spot_daily()
    sets = {
        "near(BRENT_W-CRUDE_ICE)": (bw["ret"], ci["ret"], np.log(bw["price"]) - np.log(ci["price"])),
        "deferred(BRENT_W-CRUDE_W)": (bw["ret"], cw["ret"], np.log(bw["price"]) - np.log(cw["price"])),
    }
    b = sp["XBRUSD"].where(sp["XBRUSD"] > 0); w = sp["XTIUSD"].where(sp["XTIUSD"] > 0)
    both = pd.concat([b, w], axis=1).dropna()
    sets["spot(EIA)"] = (both.iloc[:, 0].pct_change().clip(-.5, .5), both.iloc[:, 1].pct_change().clip(-.5, .5),
                         np.log(both.iloc[:, 0]) - np.log(both.iloc[:, 1]))
    sigs = {}
    for n in [20, 60, 120, 250]:
        sigs[f"z_revert_{n}"] = z_revert(n)
    for n in [20, 60]:
        sigs[f"z_entry2_{n}"] = z_revert(n, 2.0)
    for f in [8, 32]:
        sigs[f"spread_trend_{f}"] = spread_trend(f)
    for dname, (rA, rB, lev) in sets.items():
        for sname, fn in sigs.items():
            for lag in [1, 2]:
                res = pair_backtest(rA, rB, lev, fn, "XBRUSD", "XTIUSD", lag=lag)
                m = bt.metrics(res["net"], res, sname)
                m.update({"dataset": dname, "lag": lag, "pair": "Brent-WTI",
                          "is_sharpe": bt.sharpe(res["net"][:"2012"]), "oos_sharpe": bt.sharpe(res["net"]["2013":])})
                m.update({"sr_" + k: v for k, v in bt.by_period(res["net"]).items()})
                rows.append(m)
    # oil / gas ratio (WTI vs NG)
    g = futures_daily("GAS_US")
    lev = np.log(cw["price"]) - np.log(g["price"] * 10)  # $/bbl vs $/MMBtu*10 - level only for z-scores
    for sname in ["z_revert_60", "z_revert_250", "spread_trend_32"]:
        for lag in [1, 2]:
            res = pair_backtest(cw["ret"], g["ret"], lev, sigs[sname], "XTIUSD", "XNGUSD", lag=lag)
            m = bt.metrics(res["net"], res, sname)
            m.update({"dataset": "fut(CRUDE_W-GAS_US)", "lag": lag, "pair": "WTI-NG",
                      "is_sharpe": bt.sharpe(res["net"][:"2012"]), "oos_sharpe": bt.sharpe(res["net"]["2013":])})
            m.update({"sr_" + k: v for k, v in bt.by_period(res["net"]).items()})
            rows.append(m)
    return pd.DataFrame(rows)


def crack_signal_test():
    """Does the 3-2-1 crack spread (refining margin) predict crude returns?  Next 21d return on crack z-score."""
    import statsmodels.api as sm
    cl, rb, ho = futures_daily("CRUDE_W"), futures_daily("GASOILINE"), futures_daily("HEATOIL")
    px = pd.concat([cl["price"], rb["price"] * 42, ho["price"] * 42], axis=1, keys=["cl", "rb", "ho"]).dropna()
    crack = (2 * px.rb + px.ho - 3 * px.cl) / 3
    z = sg.zscore(crack, 250)
    fwd = np.log(cl["tri"]).shift(-21) - np.log(cl["tri"])
    x = pd.concat([z, fwd], axis=1, keys=["z", "f"]).dropna().iloc[::21]
    out = []
    for lab, sub in [("full", x), ("<=2007", x[:"2007"]), ("2008+", x["2008":])]:
        r = sm.OLS(sub.f, sm.add_constant(sub.z)).fit(cov_type="HC1")
        out.append({"period": lab, "beta": r.params["z"], "t": r.tvalues["z"], "n": len(sub)})
    return pd.DataFrame(out)


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    T = run_all()
    T.to_csv(os.path.join(OUT, "e05_relative_value.csv"), index=False)
    cols = ["pair", "dataset", "name", "lag", "sharpe", "gross_sharpe", "is_sharpe", "oos_sharpe", "turnover_py",
            "cost_py", "max_dd", "sr_1990-1999", "sr_2000-2009", "sr_2010-2019", "sr_2020-2029"]
    print(T[[c for c in cols if c in T.columns]].round(2).to_string(index=False))
    print("\nCrack spread (3-2-1) z-score -> next 21d WTI return:")
    print(crack_signal_test().round(3).to_string(index=False))
