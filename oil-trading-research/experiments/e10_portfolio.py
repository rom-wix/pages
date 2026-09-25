"""E10 - Candidate daily bot: trend (all 3) + crack-spread tilt (crude only). Robustness & holdout.

Outputs: results/e10_*.csv and series used by the report (equity curves, yearly returns, drawdowns).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings("ignore")
import json

import numpy as np
import pandas as pd

from src import backtest as bt, signals as sg
from src.data import futures_daily
from src.evaluate import evaluate, get_dataset
from experiments.e09_crack import crack_series

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
FUT = get_dataset("fut")
SPOT = get_dataset("spot")
CRACK_Z = sg.zscore(crack_series(), 250)


def trend(d):
    return (sg.multi_ewmac(d["tri"], d["ret"], (8, 16, 32, 64)) + sg.multi_breakout(d["tri"], (40, 80, 160, 320))) / 2


def crack(d):
    return (CRACK_Z.reindex(d.index).ffill() / 2).clip(-1, 1)


def trend_crack(d):
    """Crude: 50/50 trend + crack; gas: trend only."""
    t = trend(d)
    if d["sym"].iloc[0] in ("XTIUSD", "XBRUSD"):
        return (t + 2 * crack(d)) / 2  # crack(d) is in [-1,1]; x2 puts it on the trend forecast scale
    return t


def tag(data):
    for s, df in data.items():
        df["sym"] = s
    return data


FUT = tag(FUT)
SPOT = tag(SPOT)

STRATS = {"trend": trend, "crack": crack, "trend+crack": trend_crack}


def robustness():
    rows = []
    for name, fn in STRATS.items():
        syms = ["XTIUSD", "XBRUSD"] if name == "crack" else ["XTIUSD", "XBRUSD", "XNGUSD"]
        grid = [dict()] + [dict(cost_mult=2.0), dict(cost_mult=3.0), dict(fin=0.05), dict(fin=0.0), dict(lag=2),
                           dict(lag=3), dict(buffer=None), dict(buffer=0.25), dict(target_vol=0.25)]
        for kw in grid:
            t = evaluate(fn, name, data=FUT, symbols=syms, **kw)["table"]
            t["setting"] = ",".join(f"{k}={v}" for k, v in kw.items()) or "base"
            rows.append(t)
    return pd.concat(rows, ignore_index=True)


def headline():
    """Series + stats for the report."""
    out = {}
    series = {}
    for name, fn in STRATS.items():
        syms = ["XTIUSD", "XBRUSD"] if name == "crack" else ["XTIUSD", "XBRUSD", "XNGUSD"]
        res = evaluate(fn, name, data=FUT, symbols=syms, keep_series=True)
        port = res["port"]
        lo, hi = bt.bootstrap_sharpe_ci(port, n=1000)
        m = bt.metrics(port, None, name)
        m["ci95"] = [lo, hi]
        m["yearly"] = {int(k): float(v) for k, v in bt.yearly(port).items()}
        m["per_symbol"] = res["table"].set_index("symbol")[["sharpe", "cagr", "max_dd", "turnover_py", "cost_py",
                                                             "is_sharpe", "oos_sharpe"]].round(3).to_dict("index")
        out[name] = m
        series[name] = port
        for s, r in res["nets"].items():
            series[f"{name}:{s}"] = r
    # buy & hold (vol-targeted long) for reference
    bh = evaluate(lambda d: pd.Series(1.0, index=d.index), "long_only", data=FUT, keep_series=True)
    series["long_only"] = bh["port"]
    out["long_only"] = bt.metrics(bh["port"], None, "long_only")
    S = pd.DataFrame(series)
    S.to_csv(os.path.join(OUT, "e10_daily_returns.csv"))
    return out, S


def holdout_spot():
    """2024-04 -> 2026-09 on EIA spot (no roll yield; signals computed on spot history since 1986/1997).
    Only trend can be evaluated (no product prices after 2024-03). NG spot (Henry Hub cash) is not the
    CFD underlying - shown for completeness only."""
    res = evaluate(trend, "trend_spot", data=SPOT, start="2024-04-01", keep_series=True)
    t = res["table"]
    long = evaluate(lambda d: pd.Series(1.0, index=d.index), "long_spot", data=SPOT, start="2024-04-01",
                    keep_series=True)
    return pd.concat([t, long["table"]]), res


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    R = robustness()
    R.to_csv(os.path.join(OUT, "e10_robustness.csv"), index=False)
    cols = ["name", "setting", "symbol", "sharpe", "cagr", "ann_vol", "max_dd", "is_sharpe", "oos_sharpe",
            "turnover_py", "cost_py", "sr_1990-1999", "sr_2000-2009", "sr_2010-2019", "sr_2020-2029"]
    print(R[R.symbol == "PORT"][cols].round(2).to_string(index=False))
    H, S = headline()
    json.dump(H, open(os.path.join(OUT, "e10_headline.json"), "w"), indent=1, default=float)
    for k, v in H.items():
        print(k, bt.fmt(v), "CI95", v.get("ci95"))
    print("\nCorrelation of daily P&L:")
    print(S[["trend", "crack", "trend+crack", "long_only"]].corr().round(2))
    HT, _ = holdout_spot()
    HT.to_csv(os.path.join(OUT, "e10_holdout_spot.csv"), index=False)
    print("\nHoldout 2024-04..2026-09 on EIA spot:")
    print(HT[["name", "symbol", "sharpe", "cagr", "ann_vol", "max_dd"]].round(2).to_string(index=False))
