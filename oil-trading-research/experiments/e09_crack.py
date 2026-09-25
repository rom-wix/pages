"""E09 - Crack-spread (refining margin) signal for crude direction - deep dive.

Hypothesis: when refined-product prices are strong relative to crude (high crack spread vs its own
history), refiners' demand for crude and product-led rallies push crude up over the following weeks.

Checks: execution lag 1..10 days, component cracks (gasoline vs heating oil), seasonal adjustment
(RBOB summer/winter grade seasonality), contract-mismatch robustness (near-month WTI), parameter
sensitivity, combination with trend, bootstrap CI.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from src import backtest as bt, signals as sg
from src.data import futures_daily
from src.evaluate import evaluate, get_dataset

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
FUT = get_dataset("fut")


def crack_series(crude="CRUDE_W", kind="321"):
    cl, rb, ho = futures_daily(crude), futures_daily("GASOILINE"), futures_daily("HEATOIL")
    px = pd.concat([cl["price"], rb["price"] * 42, ho["price"] * 42], axis=1, keys=["cl", "rb", "ho"]).dropna()
    if kind == "321":
        return (2 * px.rb + px.ho - 3 * px.cl) / 3
    if kind == "gasoline":
        return px.rb - px.cl
    if kind == "heating":
        return px.ho - px.cl
    if kind == "321_pct":  # margin as % of crude price
        return ((2 * px.rb + px.ho - 3 * px.cl) / 3) / px.cl
    raise ValueError(kind)


def seasonal_adjust(x: pd.Series, years=5) -> pd.Series:
    """Subtract the prior-`years` mean of the same calendar month (strictly past years)."""
    m = x.groupby([x.index.year, x.index.month]).mean().unstack()
    base = m.shift(1).rolling(years, min_periods=3).mean()
    b = pd.Series([base.at[y, mo] if y in base.index else np.nan for y, mo in zip(x.index.year, x.index.month)],
                  index=x.index)
    return x - b


def crack_fn(z: pd.Series, scale=2.0):
    return lambda d: (z.reindex(d.index).ffill() / scale).clip(-1, 1)


def run():
    rows = []

    def rec(tag, fn, **kw):
        t = evaluate(fn, tag, data=FUT, symbols=["XTIUSD", "XBRUSD"], **kw)["table"]
        for k, v in kw.items():
            t[k] = v
        rows.append(t)

    base = crack_series()
    # 1) window sensitivity
    for n in [60, 120, 250, 500]:
        rec(f"crack321_z{n}", crack_fn(sg.zscore(base, n)))
    # 2) lag robustness (execution delay)
    for lag in [2, 3, 5, 10]:
        rec("crack321_z250", crack_fn(sg.zscore(base, 250)), lag=lag)
    # 3) components and % margin
    for kind in ["gasoline", "heating", "321_pct"]:
        rec(f"crack_{kind}_z250", crack_fn(sg.zscore(crack_series(kind=kind), 250)))
    # 4) seasonal adjustment
    sa = seasonal_adjust(base)
    rec("crack321_seasadj_z250", crack_fn(sg.zscore(sa, 250)))
    # 5) near-month crude leg (2006+) - contract-mismatch robustness
    near = crack_series("CRUDE_ICE")
    rec("crack321_nearWTI_z250", crack_fn(sg.zscore(near, 250)), start="2008-01-01")
    rec("crack321_z250_2008+", crack_fn(sg.zscore(base, 250)), start="2008-01-01")
    # 6) weekly-sampled signal (rebalance weekly only) - lower turnover
    zw = sg.zscore(base, 250)
    zw = zw.where(zw.index.dayofweek == 4).ffill()
    rec("crack321_z250_weekly", crack_fn(zw))
    # 7) cost stress
    rec("crack321_z250", crack_fn(sg.zscore(base, 250)), cost_mult=2.0)
    # 8) combination with trend
    z = sg.zscore(base, 250)
    trend = lambda d: sg.multi_ewmac(d["tri"], d["ret"], (8, 16, 32, 64))
    rec("trend_only", trend)
    rec("trend+crack", lambda d: (trend(d) + 2 * crack_fn(z)(d)) / 2)
    T = pd.concat(rows, ignore_index=True)
    return T


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    T = run()
    T.to_csv(os.path.join(OUT, "e09_crack.csv"), index=False)
    cols = [c for c in ["name", "lag", "cost_mult", "start", "symbol", "sharpe", "gross_sharpe", "is_sharpe",
                        "oos_sharpe", "turnover_py", "max_dd", "sr_1990-1999", "sr_2000-2009", "sr_2010-2019",
                        "sr_2020-2029"] if c in T.columns]
    print(T[cols].round(2).to_string(index=False))
    # bootstrap CI + correlation with trend for the headline config
    z = sg.zscore(crack_series(), 250)
    res = evaluate(crack_fn(z), "crack", data=FUT, symbols=["XTIUSD", "XBRUSD"], keep_series=True)
    lo, hi = bt.bootstrap_sharpe_ci(res["port"], n=1000)
    tr = evaluate(lambda d: sg.multi_ewmac(d["tri"], d["ret"]), "trend", data=FUT, symbols=["XTIUSD", "XBRUSD"],
                  keep_series=True)
    c = pd.concat([res["port"], tr["port"]], axis=1).dropna().corr().iloc[0, 1]
    print(f"\ncrack portfolio (WTI+Brent) Sharpe 95% bootstrap CI: [{lo:.2f}, {hi:.2f}];  corr with trend P&L: {c:.2f}")
