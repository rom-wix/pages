"""Design (first half only unless argv[1]=H2): what follows a large move on the 15m/1h/4h grid.
Trigger: |bar return| >= k * trailing sigma of that bar size (20 days). Signed forward return over h bars
(continuation > 0), measured from the trigger bar close; rollover minutes excluded; bp and t-stat."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
import data as D
from engine import rollover_mask
pd.set_option("display.width", 250)
SPLIT = pd.Timestamp("2026-06-01", tz="UTC")
HALF = sys.argv[1] if len(sys.argv) > 1 else "H1"
groups = {"JPY": ["USDJPY", "EURJPY"], "FXmaj": ["EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "EURGBP"],
          "USidx": ["US500", "NAS100", "US30", "US2000"], "ROWidx": ["GER40", "EUSTX50", "JPN225", "AUS200"]}
rows = []
for gname, syms in groups.items():
    for tf, per_day in (("15min", 96), ("1h", 24), ("4h", 6)):
        for sym in syms:
            m = D.load_minutes(sym)
            m = m[rollover_mask(m.index)]
            b = D.resample(m, tf)
            lc = np.log(b.close)
            r = lc.diff() * 1e4
            gap = b.index.to_series().diff() > pd.Timedelta(tf) * 1.5
            r[gap.values] = np.nan
            sig = r.rolling(per_day * 20, min_periods=per_day * 5).std().shift(1)
            for k in (1.5, 2.0, 3.0):
                ev = (r.abs() >= k * sig)
                for h in (1, 4, 16):
                    fwd = (lc.shift(-h) - lc) * 1e4
                    s = (np.sign(r) * fwd)[ev].dropna()
                    s = s[s.index < SPLIT] if HALF == "H1" else s[s.index >= SPLIT]
                    # normalise by sigma of the trigger bar so symbols are comparable
                    rows.append(dict(group=gname, tf=tf, k=k, h=h, sym=sym, n=len(s), mean_bp=s.mean(),
                                     mean_sig=(s / sig.reindex(s.index)).mean()))
r = pd.DataFrame(rows)
agg = r.groupby(["group", "tf", "k", "h"]).agg(n=("n", "sum"), mean_sig=("mean_sig", "mean"),
                                               pos_syms=("mean_sig", lambda x: f"{(x > 0).sum()}/{len(x)}"), mean_bp=("mean_bp", "mean"))
print(f"{HALF}: follow-through after large moves, in units of trigger-bar sigma (continuation > 0)")
print(agg.round(3).unstack("h").to_string())
