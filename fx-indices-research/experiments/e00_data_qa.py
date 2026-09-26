"""Data QA: coverage, gaps, snapshot agreement, cross-rate consistency, price levels."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
import data as D

rows = []
for s in D.ALL:
    m = D.load_minutes(s)
    d = D.daily_bars(s)
    idx = m.index
    gaps = idx.to_series().diff().dt.total_seconds().div(60)
    # gaps > 30 min that are not the weekend/daily break
    big = gaps[(gaps > 30) & (gaps < 60 * 40)]
    wk = pd.Series(1, index=d.index).resample("W").sum()
    rows.append(dict(sym=s, first=idx[0].date(), last=idx[-1].date(), days=len(d), weeks_lt4days=int((wk < 4).sum()),
                     gaps_30m_plus=len(big), med_bars_per_day=int(d["n"].median()),
                     px_start=round(d["close"].iloc[0], 4), px_end=round(d["close"].iloc[-1], 4),
                     px_min=round(d["low"].min(), 4), px_max=round(d["high"].max(), 4)))
print(pd.DataFrame(rows).to_string(index=False))

# Snapshot agreement on overlapping minutes
print("\nSnapshot agreement (median / max |close diff| in pips on overlapping minutes, oldest vs newest):")
for s in ["EURUSD", "USDJPY", "US500", "GER40"]:
    parts = [D._read_snapshot(p) for p in D._snapshot_order(D.GETDATA[s])]
    a, b = parts[0], parts[-1]
    j = a[["close"]].join(b[["close"]], lsuffix="_a", rsuffix="_b", how="inner")
    diff = (j.close_a - j.close_b).abs() / D.pip_size(s)
    print(f"  {s}: overlap {len(j)} min, median {diff.median():.3f}, 99% {diff.quantile(.99):.3f}, max {diff.max():.2f}")

# Cross rates
def c(s): return D.load_minutes(s)["close"]
j = pd.concat([c("EURUSD"), c("USDJPY"), c("EURJPY"), c("GBPUSD"), c("EURGBP")], axis=1, keys=["eu", "uj", "ej", "gu", "eg"]).dropna()
e1 = (j.eu * j.uj - j.ej) / 0.01
e2 = (j.eu / j.gu - j.eg) / 0.0001
print(f"\nCross-rate EURJPY vs EURUSD*USDJPY (pips): median {e1.median():.2f}, |p99| {e1.abs().quantile(.99):.2f}")
print(f"Cross-rate EURGBP vs EURUSD/GBPUSD (pips): median {e2.median():.2f}, |p99| {e2.abs().quantile(.99):.2f}")

# Hour-of-day activity (UTC) for a few symbols: mean 1m range in pips/points
for s in ["EURUSD", "US500", "GER40", "JPN225"]:
    m = D.load_minutes(s)
    r = ((m.high - m.low) / D.pip_size(s)).groupby(m.index.hour).mean().round(2)
    print(f"\n{s} mean 1m range by UTC hour:\n" + " ".join(f"{h:02d}:{v}" for h, v in r.items()))
