"""E12 - Candidate bot on near-month contracts (closer to what front-referenced CFDs track), 2008-2024.

near : CRUDE_ICE (~1-2 month WTI), BRENT_W, GAS-LAST (~1-2 month gas); crack built with CRUDE_ICE
main : CRUDE_W (Dec WTI), BRENT_W, GAS_US
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings("ignore")

import pandas as pd

from src import signals as sg
from src.data import futures_daily
from src.evaluate import evaluate
from experiments.e10_portfolio import trend
from experiments.e09_crack import crack_series

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
COLS = ["ret", "tri", "carry", "price"]


def dataset(codes):
    d = {}
    for s, c in codes.items():
        df = futures_daily(c)[COLS].copy()
        df["sym"] = s
        d[s] = df
    return d


def trend_crack_with(z):
    def f(d):
        t = trend(d)
        if d["sym"].iloc[0] in ("XTIUSD", "XBRUSD"):
            return (t + 2 * (z.reindex(d.index).ffill() / 2).clip(-1, 1)) / 2
        return t
    return f


if __name__ == "__main__":
    sets = {
        "near-month": (dataset({"XTIUSD": "CRUDE_ICE", "XBRUSD": "BRENT_W", "XNGUSD": "GAS-LAST"}),
                       sg.zscore(crack_series("CRUDE_ICE"), 250)),
        "main": (dataset({"XTIUSD": "CRUDE_W", "XBRUSD": "BRENT_W", "XNGUSD": "GAS_US"}),
                 sg.zscore(crack_series("CRUDE_W"), 250)),
    }
    rows = []
    for lab, (data, z) in sets.items():
        for name, fn in [("trend", trend), ("trend+crack", trend_crack_with(z))]:
            t = evaluate(fn, name, data=data, start="2008-01-01")["table"].set_index("symbol")
            rows.append({"contracts": lab, "strategy": name, "port_sharpe": t.loc["PORT", "sharpe"],
                         "wti": t.loc["XTIUSD", "sharpe"], "brent": t.loc["XBRUSD", "sharpe"],
                         "gas": t.loc["XNGUSD", "sharpe"], "max_dd": t.loc["PORT", "max_dd"],
                         "sr_2010s": t.loc["PORT", "sr_2010-2019"], "sr_2020s": t.loc["PORT", "sr_2020-2029"]})
    T = pd.DataFrame(rows).round(3)
    T.to_csv(os.path.join(OUT, "e12_near_month.csv"), index=False)
    print(T.to_string(index=False))
