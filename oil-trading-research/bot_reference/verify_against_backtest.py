"""Check that bot_reference.signal_engine reproduces the research positions exactly."""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import warnings; warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from bot_reference import signal_engine as se
from src.data import futures_daily
from src.evaluate import positions
from experiments.e10_portfolio import FUT, trend_crack
from experiments.e11_extras import vol_filter
from experiments.e14_speed_blends import BLENDS, with_crack

rets = {s: FUT[s]["ret"] for s in ["XTIUSD", "XBRUSD", "XNGUSD"]}
cl, rb, ho = futures_daily("CRUDE_W"), futures_daily("GASOILINE"), futures_daily("HEATOIL")
crack_px = pd.concat([cl["price"], rb["price"], ho["price"]], axis=1, keys=["cl", "rb", "ho"]).dropna()

worst = 0.0
checks = [("revised (default)", dict(trend="revised", vol_overlay=True),
           with_crack(vol_filter(BLENDS["tsmom 1/3/12m + fast+medium"]))),
          ("original", dict(trend="original", vol_overlay=False), trend_crack)]
for label, kw, research_fn in checks:
    live = se.target_positions(rets, crack_px, **kw)
    for s in rets:
        research = positions(FUT[s], research_fn)
        diff = (live[s] - research.reindex(live.index)).abs().max()
        worst = max(worst, diff)
        print(f"[{label}] {s}: max |engine - research| = {diff:.2e}; last target = {live[s].iloc[-1]:+.3f}")
assert worst < 1e-9, "engine drifted from the backtested logic"
print("OK - reference engine matches the backtest")
