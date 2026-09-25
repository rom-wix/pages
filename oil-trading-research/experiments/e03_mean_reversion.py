"""E03 - Daily mean-reversion / short-term reversal strategies.

On rolled futures (close-only signals) and on Oanda daily OHLC (IBS-type signals, 2005-2020).
Each variant is run with lag=1 (trade at the signal close) and lag=2 (trade next close) - short-horizon
effects that disappear with a one-day delay are usually close-to-close microstructure artefacts.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from src import signals as sg
from src.data import oanda_daily
from src.evaluate import evaluate, get_dataset, show

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
FUT = get_dataset("fut")


def hold_after(trigger: pd.Series, direction: pd.Series, days: int) -> pd.Series:
    """Position = direction for `days` days after each trigger (non-cumulative)."""
    out = pd.Series(0.0, index=trigger.index)
    t = trigger.fillna(False).to_numpy()
    d = direction.fillna(0).to_numpy()
    o = np.zeros(len(t))
    left, cur = 0, 0.0
    for i in range(len(t)):
        if t[i]:
            left, cur = days, d[i]
        o[i] = cur if left > 0 else 0.0
        left = max(left - 1, 0)
    out[:] = o
    return out


def rsi2_connors(d, lo=10, hi=90, trend_filter=True):
    x = np.log(d["tri"])
    r = sg.rsi(d["ret"], 2)
    up = x > x.rolling(200).mean()
    pos = np.zeros(len(x))
    cur = 0.0
    for i, (rv, u) in enumerate(zip(r.to_numpy(), up.to_numpy())):
        if np.isnan(rv):
            pos[i] = 0
            continue
        if cur == 0:
            if rv < lo and (u or not trend_filter):
                cur = 1.0
            elif rv > hi and ((not u) or not trend_filter):
                cur = -1.0
        elif cur > 0 and rv > 70:
            cur = 0.0
        elif cur < 0 and rv < 30:
            cur = 0.0
        pos[i] = cur
    return pd.Series(pos, index=x.index)


def zfade(d, n=20, entry=2.0, exit=0.5):
    z = sg.zscore(np.log(d["tri"]), n).to_numpy()
    pos = np.zeros(len(z))
    cur = 0.0
    for i, zv in enumerate(z):
        if np.isnan(zv):
            continue
        if cur == 0:
            if zv > entry:
                cur = -1.0
            elif zv < -entry:
                cur = 1.0
        elif cur > 0 and zv > -exit:
            cur = 0.0
        elif cur < 0 and zv < exit:
            cur = 0.0
        pos[i] = cur
    return pd.Series(pos, index=d.index)


def shock_reversal(d, k=2.5, days=3):
    vol = d["ret"].ewm(span=36, min_periods=20).std().shift(1)
    z = d["ret"] / vol
    trig = z.abs() > k
    return hold_after(trig, -np.sign(z), days)


def shock_continuation(d, k=2.5, days=3):
    return -shock_reversal(d, k, days)


variants = {}
for k in [1, 2, 3, 5, 10]:
    variants[f"reversal_{k}d"] = (lambda k: lambda d: -np.sign(np.log(d["tri"]).diff(k)))(k)
variants["rsi2_connors_trendfilter"] = lambda d: rsi2_connors(d, 10, 90, True)
variants["rsi2_connors_nofilter"] = lambda d: rsi2_connors(d, 10, 90, False)
for n in [10, 20, 50]:
    variants[f"zfade_{n}_2.0"] = (lambda n: lambda d: zfade(d, n, 2.0, 0.5))(n)
    variants[f"zcontinuous_{n}"] = (lambda n: lambda d: (-sg.zscore(np.log(d["tri"]), n) / 2).clip(-1, 1))(n)
for k, days in [(2.0, 1), (2.5, 3), (3.0, 5)]:
    variants[f"shock_reversal_{k}_{days}d"] = (lambda k, days: lambda d: shock_reversal(d, k, days))(k, days)
    variants[f"shock_continuation_{k}_{days}d"] = (lambda k, days: lambda d: shock_continuation(d, k, days))(k, days)


def oanda_ibs():
    """Internal bar strength on Oanda daily OHLC (cut 17:00 NY). IBS=(C-L)/(H-L).
    Long if IBS<0.2, short if IBS>0.8, hold 1 day. P&L on the Oanda close-to-close return (intraday
    CFD prices; roll yield not included, fine for 1-day holds)."""
    rows = []
    for sym in ["XTIUSD", "XNGUSD"]:
        od = oanda_daily(sym)
        r = od["close"].pct_change()
        ibs = (od["close"] - od["low"]) / (od["high"] - od["low"]).replace(0, np.nan)
        df = pd.DataFrame({"ret": r, "tri": (1 + r.fillna(0)).cumprod()})
        for lo, hi in [(0.2, 0.8), (0.1, 0.9)]:
            sig = pd.Series(np.where(ibs < lo, 1.0, np.where(ibs > hi, -1.0, 0.0)), index=od.index)
            for lag in [1, 2]:
                t = evaluate(lambda d, s=sig: s, f"ibs_{lo}_{hi}", data={sym: df}, symbols=[sym], lag=lag,
                             buffer=None)["table"]
                t = t[t.symbol == sym]
                t["lag"] = lag
                rows.append(t)
    return pd.concat(rows, ignore_index=True)


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    tabs = []
    for name, fn in variants.items():
        for lag in [1, 2]:
            t = evaluate(fn, name, data=FUT, lag=lag, buffer=None)["table"]
            t["lag"] = lag
            tabs.append(t)
    T = pd.concat(tabs, ignore_index=True)
    ibs = oanda_ibs()
    ibs["dataset"] = "oanda"
    T = pd.concat([T, ibs], ignore_index=True)
    T.to_csv(os.path.join(OUT, "e03_mean_reversion.csv"), index=False)
    cols = ["name", "lag", "symbol", "sharpe", "gross_sharpe", "is_sharpe", "oos_sharpe", "turnover_py", "cost_py",
            "max_dd", "sr_1990-1999", "sr_2000-2009", "sr_2010-2019", "sr_2020-2029"]
    for sym in ["PORT", "XTIUSD", "XBRUSD", "XNGUSD"]:
        print(f"\n--- {sym}")
        sub = T[(T.symbol == sym)][cols]
        print(sub.round(2).to_string(index=False))
