"""E01 - Buy & hold baselines and trend following (time-series momentum) on daily data.

Families: TSMOM sign(L), SMA cross, EWMAC single/multi-speed, breakout single/multi, Donchian/Turtle.
All vol-targeted to 15%/yr per instrument, 10% position buffer, CFD costs + 2.5% financing markup.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from src import signals as sg
from src.evaluate import evaluate, get_dataset, show

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")

FUT = get_dataset("fut")
SPOT = get_dataset("spot")

variants = {
    "long_only_voltarget": lambda d: pd.Series(1.0, index=d.index),
}
for L in [21, 63, 126, 252]:
    variants[f"tsmom_{L}"] = (lambda L: lambda d: sg.tsmom(d["tri"], L))(L)
for f, s in [(10, 50), (20, 100), (50, 200)]:
    variants[f"sma_{f}_{s}"] = (lambda f, s: lambda d: sg.ma_cross(d["tri"], f, s))(f, s)
for f in [4, 8, 16, 32, 64]:
    variants[f"ewmac_{f}_{4*f}"] = (lambda f: lambda d: sg.ewmac(d["tri"], d["ret"], f))(f)
variants["ewmac_multi_8-64"] = lambda d: sg.multi_ewmac(d["tri"], d["ret"], (8, 16, 32, 64))
variants["ewmac_multi_16-64"] = lambda d: sg.multi_ewmac(d["tri"], d["ret"], (16, 32, 64))
for n in [20, 40, 80, 160, 320]:
    variants[f"breakout_{n}"] = (lambda n: lambda d: sg.breakout(d["tri"], n))(n)
variants["breakout_multi"] = lambda d: sg.multi_breakout(d["tri"])
for e, x in [(20, 10), (55, 20), (100, 50)]:
    variants[f"donchian_{e}_{x}"] = (lambda e, x: lambda d: sg.donchian(d["tri"], e, x))(e, x)
variants["trend_combo"] = lambda d: (sg.multi_ewmac(d["tri"], d["ret"], (8, 16, 32, 64)) +
                                     sg.multi_breakout(d["tri"], (40, 80, 160, 320))) / 2

if __name__ == "__main__":
    tabs = []
    for name, fn in variants.items():
        for kind, data in [("fut", FUT), ("spot", SPOT)]:
            res = evaluate(fn, name, kind=kind, data=data)
            tabs.append(res["table"])
    T = pd.concat(tabs, ignore_index=True)
    T.to_csv(os.path.join(OUT, "e01_trend.csv"), index=False)
    pd.set_option("display.width", 250)
    for kind in ["fut", "spot"]:
        print(f"\n===== dataset={kind}  (per-symbol and equal-weight portfolio) =====")
        for sym in ["PORT", "XTIUSD", "XBRUSD", "XNGUSD"]:
            sub = T[(T.dataset == kind) & (T.symbol == sym)]
            print(f"\n--- {sym}")
            print(show(sub))
