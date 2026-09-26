"""Market-behaviour diagnostics, first half (Feb-May) vs second half (Jun-Sep).
1) variance ratios of 15m returns (trend > 1 > mean reversion) at 1h / 4h / 1d horizons
2) what follows a large 1h move (continuation vs reversal over the next 1h / 4h / 12h)
3) session hand-offs: does the Asia / London-morning / US-first-hour direction persist?
Rollover minutes (16:40-18:10 NY) are excluded."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
import data as D
from engine import rollover_mask
pd.set_option("display.width", 250)
SPLIT = pd.Timestamp("2026-06-01", tz="UTC")

def clean_bars(sym, rule):
    m = D.load_minutes(sym)
    m = m[rollover_mask(m.index)]
    return D.resample(m, rule)

def vr(r, q):
    r = r.dropna()
    x = r.rolling(q).sum().dropna()[::1]
    return x.var() / (q * r.var())

rows = []
for sym in D.ALL:
    b = clean_bars(sym, "15min")
    r = np.log(b.close).diff()
    # drop returns spanning gaps > 15 min (weekend / breaks)
    gap = b.index.to_series().diff() > pd.Timedelta("15min")
    r[gap.values] = np.nan
    for half, rr in (("H1", r[r.index < SPLIT]), ("H2", r[r.index >= SPLIT])):
        rows.append(dict(sym=sym, half=half, vr_1h=vr(rr, 4), vr_4h=vr(rr, 16), vr_1d=vr(rr, 64), ac1_15m=rr.autocorr(1)))
v = pd.DataFrame(rows).pivot(index="sym", columns="half")
print("Variance ratios (15m base; <1 = mean-reverting, >1 = trending):")
print(v.round(3).to_string())

# 2) large 1h moves
print("\nAfter a large 1h move (|r| > 2.0 x trailing 20-day 1h sigma): mean signed follow-through in bp (continuation > 0) and t-stat")
out = []
for sym in D.ALL:
    b = clean_bars(sym, "1h")
    r = np.log(b.close).diff() * 1e4
    sig = r.rolling(24 * 20, min_periods=100).std().shift(1)
    ev = r.abs() > 2.0 * sig
    for hz in (1, 4, 12):
        fwd = np.log(b.close).shift(-hz).sub(np.log(b.close)) * 1e4
        s = (np.sign(r) * fwd)[ev]
        for half, ss in (("H1", s[s.index < SPLIT]), ("H2", s[s.index >= SPLIT])):
            ss = ss.dropna()
            out.append(dict(sym=sym, hz=hz, half=half, n=len(ss), mean=ss.mean(), t=ss.mean() / ss.std() * np.sqrt(len(ss)) if len(ss) > 2 else np.nan))
o = pd.DataFrame(out)
print(o.pivot_table(index="sym", columns=["hz", "half"], values=["mean", "t"]).round(1).to_string())

# 3) session hand-offs (FX, New York clock)
def seg(sym, a, b, tz="America/New_York"):
    m = D.load_minutes(sym)
    loc = m.index.tz_convert(tz)
    tod = loc.hour * 60 + loc.minute
    d = D.trading_day_ny(m.index)
    s = m[(tod >= a) & (tod < b)]
    g = s.groupby(np.asarray(d)[(tod >= a) & (tod < b)])
    return np.log(g.close.last() / g.open.first()) * 1e4

print("\nSession hand-off correlations (corr of segment returns across days), H1 | H2:")
hm = lambda s: int(s[:2]) * 60 + int(s[3:])
pairs = [("asia 18:10-02:00 -> london 02:00-06:00", ("18:10", "24:00"), ("02:00", "06:00")),
         ("london 02:00-08:00 -> ny 08:00-12:00", ("02:00", "08:00"), ("08:00", "12:00")),
         ("ny 08:00-12:00 -> pm 12:00-16:00", ("08:00", "12:00"), ("12:00", "16:00")),
         ("day 18:10-12:00 -> pm 12:00-16:30", ("18:10", "24:00"), ("12:00", "16:30"))]
res = []
for sym in D.FX + ["US500", "NAS100", "GER40", "JPN225"]:
    row = {"sym": sym}
    for name, A, B in pairs:
        a = seg(sym, hm(A[0]), hm(A[1]) if A[1] != "24:00" else 1440)
        if name.startswith("asia") or name.startswith("day"):
            # asia segment runs across midnight: add 00:00-02:00 part (or 00:00-12:00 for 'day')
            end2 = hm("02:00") if name.startswith("asia") else hm("12:00")
            a = a.add(seg(sym, 0, end2), fill_value=0)
        bb = seg(sym, hm(B[0]), hm(B[1]))
        j = pd.concat([a, bb], axis=1, keys=["a", "b"]).dropna()
        j.index = pd.to_datetime(j.index).tz_localize("UTC")
        h1, h2 = j[j.index < SPLIT], j[j.index >= SPLIT]
        row[name] = f"{h1.a.corr(h1.b):+.2f} | {h2.a.corr(h2.b):+.2f}"
    res.append(row)
print(pd.DataFrame(res).to_string(index=False))
