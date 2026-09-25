"""E14 - Trend speed blends: long history (futures 1991-2024) vs the recent regime (spot 2024-26, last 12m).

Motivation: in the last 12 months (extreme, headline-driven volatility) fast trend rules won and slow ones
lost.  Candidate blends are judged on ALL windows, not on the last year alone (to avoid fitting one year).
'tsmom_1_3_12' is the Hurst-Ooi-Pedersen (2017) 1/3/12-month momentum blend - a literature spec.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from src import signals as sg
from src.evaluate import evaluate, get_dataset
from experiments.e09_crack import crack_series
from experiments.e11_extras import vol_filter

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
FUT, SPOT = get_dataset("fut"), get_dataset("spot")
for D in (FUT, SPOT):
    for s, df in D.items():
        df["sym"] = s
CRACK_Z = sg.zscore(crack_series(), 250)


def blend(ew=(), bo=()):
    def f(d):
        parts = []
        if ew:
            parts.append(sg.multi_ewmac(d["tri"], d["ret"], ew))
        if bo:
            parts.append(sg.multi_breakout(d["tri"], bo))
        return sum(parts) / len(parts)
    return f


def tsmom_1_3_12(d):
    return (sg.tsmom(d["tri"], 21) + sg.tsmom(d["tri"], 63) + sg.tsmom(d["tri"], 252)) / 3


def with_crack(fn):
    def f(d):
        t = fn(d)
        if d["sym"].iloc[0] in ("XTIUSD", "XBRUSD"):
            return (t + 2 * (CRACK_Z.reindex(d.index).ffill() / 2).clip(-1, 1)) / 2
        return t
    return f


BLENDS = {
    "slow+medium (ew 8-64, bo 40-320)": blend((8, 16, 32, 64), (40, 80, 160, 320)),
    "fast (ew 4-8, bo 20-40)": blend((4, 8), (20, 40)),
    "fast+medium (ew 4-32, bo 20-160)": blend((4, 8, 16, 32), (20, 40, 80, 160)),
    "all speeds (ew 4-64, bo 20-320)": blend((4, 8, 16, 32, 64), (20, 40, 80, 160, 320)),
    "tsmom 1/3/12m (HOP 2017)": tsmom_1_3_12,
    "tsmom 1/3/12m + fast+medium": lambda d: (tsmom_1_3_12(d) + blend((4, 8, 16, 32), (20, 40, 80, 160))(d)) / 2,
}


def score(fn, name):
    t = evaluate(fn, name, data=FUT)["table"].set_index("symbol")
    h = evaluate(fn, name, data=SPOT, start="2024-04-01")["table"].set_index("symbol")
    ly = evaluate(fn, name, data=SPOT, start="2025-09-23", end="2026-09-22")["table"].set_index("symbol")
    return {"name": name, "fut_port": t.loc["PORT", "sharpe"], "fut_is": t.loc["PORT", "is_sharpe"],
            "fut_oos": t.loc["PORT", "oos_sharpe"], "fut_maxdd": t.loc["PORT", "max_dd"],
            "fut_2010s": t.loc["PORT", "sr_2010-2019"], "fut_2020s": t.loc["PORT", "sr_2020-2029"],
            "cost_wti": t.loc["XTIUSD", "cost_py"], "cost_ng": t.loc["XNGUSD", "cost_py"],
            "turn_wti": t.loc["XTIUSD", "turnover_py"],
            "spot_2024_26_wti": h.loc["XTIUSD", "sharpe"], "spot_2024_26_brent": h.loc["XBRUSD", "sharpe"],
            "last12m_wti": ly.loc["XTIUSD", "sharpe"], "last12m_brent": ly.loc["XBRUSD", "sharpe"]}


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    rows = []
    for nm, fn in BLENDS.items():
        rows.append(score(fn, nm))
        rows.append(score(vol_filter(fn), nm + " +vol overlay"))
        c = score(with_crack(vol_filter(fn)), nm + " +vol overlay +crack")
        c["spot_2024_26_wti"] = c["spot_2024_26_brent"] = c["last12m_wti"] = c["last12m_brent"] = np.nan  # no product data after 2024-03
        rows.append(c)
    T = pd.DataFrame(rows)
    T.to_csv(os.path.join(OUT, "e14_speed_blends.csv"), index=False)
    print(T.round(2).to_string(index=False))
