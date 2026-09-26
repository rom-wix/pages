"""Sanity tests for engine.simulate on hand-built minute paths."""
import numpy as np, pandas as pd
from engine import simulate, MARKET, STOP, LIMIT

def mk(prices):
    """prices: list of (o,h,l,c) per minute starting 2026-03-02 10:00 UTC"""
    idx = pd.date_range("2026-03-02 10:00", periods=len(prices), freq="1min", tz="UTC")
    return pd.DataFrame(prices, index=idx, columns=["open", "high", "low", "close"])

def order(**kw):
    base = dict(side=1, etype=MARKET, t_active=pd.Timestamp("2026-03-02 10:00", tz="UTC"),
                t_expire=pd.Timestamp("2026-03-03", tz="UTC"), entry_px=np.nan, sl_px=99.0, tp_px=102.0,
                t_exit=pd.Timestamp("2026-03-03", tz="UTC"))
    base.update(kw); return pd.DataFrame([base])

m = mk([(100, 100.5, 99.8, 100.2), (100.2, 101, 100.1, 100.9), (100.9, 102.5, 100.8, 102.2), (102.2, 102.3, 101, 101.2)])
# 1 market long, TP hit in minute 3
r = simulate(m, order(), 0.0, 0.0, 0.0).iloc[0]
assert r.reason == "tp" and r.entry == 100 and r.exit == 102 and abs(r.r - 2.0) < 1e-9, r
# 2 SL and TP in same minute -> SL wins
m2 = mk([(100, 100.2, 99.9, 100), (100, 102.5, 98.5, 101)])
r = simulate(m2, order(), 0.0, 0.0, 0.0).iloc[0]
assert r.reason == "sl" and r.exit == 99.0, r
# 3 gap through the stop fills at the open
m3 = mk([(100, 100.2, 99.9, 100), (98.0, 98.2, 97.5, 98.1)])
r = simulate(m3, order(), 0.0, 0.0, 0.0).iloc[0]
assert r.reason == "sl" and r.exit == 98.0, r
# 4 buy stop with slippage; entry minute also touches SL -> stopped (conservative)
m4 = mk([(100, 100.4, 99.9, 100.3), (100.3, 100.8, 98.9, 100.5), (100.5, 103, 100.4, 102.9)])
r = simulate(m4, order(etype=STOP, entry_px=100.5), 0.0, 0.01, 0.0).iloc[0]
assert r.reason == "sl" and abs(r.entry - 100.51) < 1e-9, r
# 5 buy stop filled, TP later; costs applied
m5 = mk([(100, 100.4, 99.9, 100.3), (100.3, 100.8, 100.2, 100.7), (100.7, 103, 100.6, 102.9)])
r = simulate(m5, order(etype=STOP, entry_px=100.5), 0.1, 0.0, 0.0).iloc[0]
assert r.reason == "tp" and r.entry == 100.5 and abs(r.pnl - (1.5 - 0.1)) < 1e-9, r
# 6 limit short at 100.8 not filled before expiry
r = simulate(m5, order(side=-1, etype=LIMIT, entry_px=103.5, sl_px=104, tp_px=99), 0.0, 0.0, 0.0)
assert len(r) == 0
# 7 time exit at the open of the exit minute
r = simulate(m5, order(tp_px=110, t_exit=pd.Timestamp("2026-03-02 10:02", tz="UTC")), 0.0, 0.0, 0.0).iloc[0]
assert r.reason == "time" and r.exit == 100.7, r
# 8 break-even: +1R reached then back to entry -> exit at entry
m8 = mk([(100, 100.2, 99.9, 100), (100, 101.2, 99.95, 101), (101, 101, 99.9, 99.95)])
r = simulate(m8, order(be_at_r=1.0, be_lock_r=0.0), 0.0, 0.0, 0.0).iloc[0]
assert r.reason == "sl" and r.exit == 100.0, r
# 9 short side mirror, TP
m9 = mk([(100, 100.2, 99.9, 100), (100, 100.1, 97.5, 97.8)])
r = simulate(m9, order(side=-1, sl_px=101, tp_px=98), 0.0, 0.0, 0.0).iloc[0]
assert r.reason == "tp" and r.exit == 98 and abs(r.r - 2) < 1e-9, r
# 10 cancel level: limit buy at 99.5 cancelled because price hits 101 first
m10 = mk([(100, 100.2, 99.9, 100), (100, 101.1, 99.9, 101), (101, 101, 99.0, 99.2)])
r = simulate(m10, order(etype=LIMIT, entry_px=99.5, sl_px=98.5, tp_px=101, cancel_px=101.0), 0.0, 0.0, 0.0)
assert len(r) == 0
print("engine tests passed")
