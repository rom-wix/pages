"""E11 - Extra diagnostics for the candidate daily bot (saved to results/e11_extras.json).

  * trend Sharpe by volatility regime (vol percentile vs trailing 5y, known at t)
  * extreme-vol de-risking overlay (halve exposure above the 90th percentile)
  * long vs short leg decomposition
  * weekly vs daily rebalancing
  * rolling 1/2/3/5-year outcome distribution and drawdown statistics
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings("ignore")
import json

import numpy as np
import pandas as pd

from src import backtest as bt
from src.evaluate import evaluate, positions
from experiments.e10_portfolio import trend, trend_crack, FUT, SPOT

R = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def volpct(d, span=36, win=1260):
    v = d["ret"].ewm(span=span).std()
    return v.rolling(win, min_periods=500).apply(lambda x: (x[-1] >= x).mean(), raw=True)


def vol_filter(base, thr=0.9, mult=0.5):
    def f(d):
        s = base(d)
        p = volpct(d).reindex(s.index)
        return s.where(~(p > thr), s * mult)
    return f


def weekly(base, dow=2):
    def f(d):
        s = base(d)
        return s.where(s.index.dayofweek == dow).ffill()
    return f


def main():
    out = {}
    # 1) vol regimes
    rows = []
    for sym in ["XTIUSD", "XBRUSD", "XNGUSD"]:
        d = FUT[sym]
        res = bt.run(d["ret"], positions(d, trend), sym).iloc[260:]
        q = pd.cut(volpct(d).reindex(res.index), [0, .25, .5, .75, .9, 1.0],
                   labels=["<25", "25-50", "50-75", "75-90", ">90"])
        for k, v in res["net"].groupby(q):
            rows.append({"symbol": sym, "bucket": str(k), "sharpe": round(bt.sharpe(v), 3), "days": int(len(v))})
    out["vol_regime"] = rows
    # 2) overlay
    ov = []
    for name, base in [("trend", trend), ("trend+crack", trend_crack)]:
        for lab, fn in [("none", base), ("halve>p90", vol_filter(base))]:
            t = evaluate(fn, name, data=FUT)["table"]
            p = t[t.symbol == "PORT"].iloc[0]
            h = evaluate(fn, name, data=SPOT, start="2024-04-01")["table"]
            hp = h[h.symbol == "PORT"].iloc[0]
            ov.append({"strategy": name, "overlay": lab, "sharpe": round(p.sharpe, 3), "is": round(p.is_sharpe, 3),
                       "oos": round(p.oos_sharpe, 3), "max_dd": round(p.max_dd, 3),
                       "spot_holdout_trend_only": round(hp.sharpe, 3) if name == "trend" else None})
    out["vol_overlay"] = ov
    # 3) long/short legs
    legs = []
    for sym in ["XTIUSD", "XBRUSD", "XNGUSD"]:
        d = FUT[sym]
        pos = positions(d, trend)
        for leg, p in [("both", pos), ("long leg", pos.clip(lower=0)), ("short leg", pos.clip(upper=0))]:
            res = bt.run(d["ret"], p, sym).iloc[260:]
            legs.append({"symbol": sym, "leg": leg, "sharpe": round(bt.sharpe(res.net), 3),
                         "is": round(bt.sharpe(res.net[:"2007"]), 3), "oos": round(bt.sharpe(res.net["2008":]), 3)})
    out["legs"] = legs
    # 4) weekly rebalance
    wk = []
    for name, base in [("trend", trend), ("trend+crack", trend_crack)]:
        for lab, fn in [("daily", base), ("weekly (Wed)", weekly(base, 2))]:
            t = evaluate(fn, name, data=FUT)["table"].set_index("symbol")
            wk.append({"strategy": name, "rebalance": lab, "sharpe": round(t.loc["PORT", "sharpe"], 3),
                       "max_dd": round(t.loc["PORT", "max_dd"], 3),
                       "turnover_wti": round(t.loc["XTIUSD", "turnover_py"], 2),
                       "cost_wti": round(t.loc["XTIUSD", "cost_py"], 4),
                       "cost_ng": round(t.loc["XNGUSD", "cost_py"], 4)})
    out["weekly"] = wk
    # 5) rolling outcomes
    S = pd.read_csv(os.path.join(R, "e10_daily_returns.csv"), index_col=0, parse_dates=True)
    roll = []
    for k in ["trend", "trend+crack"]:
        r = S[k]["1991-11":].fillna(0)
        eq = (1 + r).cumprod()
        for yrs in [1, 2, 3, 5]:
            n = 252 * yrs
            w = (eq.shift(-n) / eq - 1).dropna()
            roll.append({"strategy": k, "years": yrs, "p_loss": round(float((w < 0).mean()), 3),
                         "median": round(float(w.median()), 3), "p10": round(float(w.quantile(.1)), 3),
                         "p90": round(float(w.quantile(.9)), 3), "worst": round(float(w.min()), 3)})
        dd = eq / eq.cummax() - 1
        uw = (dd < 0).astype(int)
        lengths = uw.groupby((uw.diff() != 0).cumsum()).sum()
        roll.append({"strategy": k, "years": "dd", "max_dd": round(float(dd.min()), 3),
                     "longest_underwater_years": round(float(lengths.max() / 252), 1)})
    out["rolling"] = roll
    json.dump(out, open(os.path.join(R, "e11_extras.json"), "w"), indent=1, default=float)
    print(json.dumps(out, indent=1, default=float)[:4000])


if __name__ == "__main__":
    main()
