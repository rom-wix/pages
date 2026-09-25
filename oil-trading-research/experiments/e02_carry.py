"""E02 - Carry / term-structure strategies.

carry[t] = annualised roll yield between the held contract and the adjacent nearer contract
           (>0 backwardation: nearer contract dearer -> long earns roll yield; <0 contango).
Variants: sign(carry), scaled carry, smoothed carry, seasonally-adjusted carry (for gas), static short gas,
and carry used as a filter on the trend signal.  Also a predictive regression carry -> next 21d return.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import statsmodels.api as sm

from src import signals as sg
from src.evaluate import evaluate, get_dataset, show

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
FUT = get_dataset("fut")


def carry_raw(d):
    return d["carry"].ffill()


def seasonal_adj_carry(d, years=5):
    """carry minus the trailing `years` average carry of the same calendar month (only past data)."""
    c = d["carry"].ffill()
    m = c.groupby([c.index.year, c.index.month]).mean()
    m.index = pd.MultiIndex.from_tuples(m.index, names=["y", "m"])
    mm = m.unstack("m")  # rows: year, cols: month
    base = mm.shift(1).rolling(years, min_periods=3).mean()  # prior years only
    b = pd.Series([base.loc[y, mo] if y in base.index else np.nan for y, mo in zip(c.index.year, c.index.month)],
                  index=c.index)
    return c - b


def scaled(x, cap=2.0):
    return sg._normalise(x, 1.0, cap)


variants = {
    "carry_sign": lambda d: np.sign(carry_raw(d)),
    "carry_scaled": lambda d: scaled(carry_raw(d)),
    "carry_ema60_sign": lambda d: np.sign(carry_raw(d).ewm(span=60).mean()),
    "carry_ema60_scaled": lambda d: scaled(carry_raw(d).ewm(span=60).mean()),
    "carry_seasadj_sign": lambda d: np.sign(seasonal_adj_carry(d).ewm(span=20).mean()),
    "carry_seasadj_scaled": lambda d: scaled(seasonal_adj_carry(d).ewm(span=20).mean()),
    "static_short": lambda d: pd.Series(-1.0, index=d.index),
    "trend": lambda d: sg.multi_ewmac(d["tri"], d["ret"], (8, 16, 32, 64)),
    # trend only when carry agrees with its sign, else half size
    "trend_carry_filter": lambda d: (lambda t, c: t.where(np.sign(t) == np.sign(c), t * 0.5))(
        sg.multi_ewmac(d["tri"], d["ret"], (8, 16, 32, 64)), carry_raw(d).ewm(span=20).mean()),
    "trend_plus_carry": lambda d: scaled(sg.multi_ewmac(d["tri"], d["ret"], (8, 16, 32, 64)) +
                                         0.5 * scaled(carry_raw(d).ewm(span=60).mean())),
}


def predictive_regression():
    rows = []
    for s, d in FUT.items():
        c = d["carry"].ffill()
        fwd = np.log(d["tri"]).shift(-21) - np.log(d["tri"])  # next 21d log return
        x = pd.concat([c, fwd], axis=1, keys=["c", "f"]).dropna()
        x = x.iloc[::21]  # non-overlapping monthly samples
        for lab, sub in [("full", x), ("1990-2007", x[:"2007"]), ("2008-2024", x["2008":])]:
            X = sm.add_constant(sub["c"])
            r = sm.OLS(sub["f"], X).fit(cov_type="HC1")
            rows.append({"symbol": s, "period": lab, "beta": r.params["c"], "t": r.tvalues["c"],
                         "r2": r.rsquared, "n": len(sub),
                         "corr_carry_trend": np.corrcoef(
                             np.sign(c.reindex(sub.index)),
                             np.sign(sg.multi_ewmac(d["tri"], d["ret"]).reindex(sub.index).fillna(0)))[0, 1]})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    reg = predictive_regression()
    reg.to_csv(os.path.join(OUT, "e02_carry_regression.csv"), index=False)
    print("Predictive regression: next-21d log return on annualised carry (monthly non-overlapping, HC1 t)")
    print(reg.round(3).to_string(index=False))

    tabs = []
    for name, fn in variants.items():
        tabs.append(evaluate(fn, name, data=FUT)["table"])
    T = pd.concat(tabs, ignore_index=True)
    T.to_csv(os.path.join(OUT, "e02_carry.csv"), index=False)
    for sym in ["PORT", "XTIUSD", "XBRUSD", "XNGUSD"]:
        print(f"\n--- {sym}")
        print(show(T[T.symbol == sym]))
