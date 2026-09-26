"""USD 'clock': mean USD return (basket of 6 USD pairs, sign-adjusted so + = USD up) per 30-min bucket (London time),
first vs second half. Tests Krohn-Mueller-Whelan (JF 2024): USD up into the fixes (Tokyo 09:55 JST, London 16:00), down after."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
import data as D
from engine import rollover_mask
pd.set_option("display.width", 250)
SPLIT = pd.Timestamp("2026-06-01", tz="UTC")
pairs = {"EURUSD": -1, "GBPUSD": -1, "AUDUSD": -1, "USDJPY": 1, "USDCAD": 1, "USDCHF": 1}
rets = []
for s, sg in pairs.items():
    m = D.load_minutes(s)
    m = m[rollover_mask(m.index) & (m.index.dayofweek < 5)]
    b = D.resample(m, "30min")
    r = np.log(b.close / b.open) * 1e4 * sg      # within-bucket return (open->close) avoids gap contamination
    rets.append(r.rename(s))
R = pd.concat(rets, axis=1, sort=True)
usd = R.mean(axis=1, skipna=False).dropna()
loc = usd.index.tz_convert("Europe/London")
lab = pd.Series(loc.strftime("%H:%M"), index=usd.index)
res = {}
for half, mask in (("H1", usd.index < SPLIT), ("H2", usd.index >= SPLIT)):
    g = usd[mask].groupby(lab[mask])
    res[(half, "bp")] = g.mean()
    res[(half, "t")] = g.mean() / g.std() * np.sqrt(g.count())
out = pd.DataFrame(res).round(2)
out["both_same_sign"] = np.sign(out[("H1", "bp")]) == np.sign(out[("H2", "bp")])
print("USD basket mean return per 30-min bucket (London time; + = USD up)")
print(out.to_string())
