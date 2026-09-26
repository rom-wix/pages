"""Reconcile the four watch-list strategies with an external FBS/MT5 replication.

Each strategy runs on our Feb-Sep 2026 data twice: as originally specified (ATR = daily ATR(14) on the
17:00-New-York trading day, known at the start of the day) and with the replication's choices
(ATR(14) on M15 bars for the two intraday trades, on H4 bars for the two 4h trades; Tokyo exit at the close of
the 09:45 M15 bar; 7 indices without US2000). Same engine, same costs, same 1-minute fills throughout."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
import data as D, strategies as S, costs as K, metrics as M
from engine import simulate, one_at_a_time, MARKET, STOP
pd.set_option("display.width", 250)
IDX7 = [s for s in D.INDICES if s != "US2000"]


def atr_intraday(sym, tf, n=14):
    """ATR(n) on tf bars, indexed by the time it becomes known (bar close)."""
    b = D.load_bars(sym, tf)
    pc = b.close.shift()
    tr = pd.concat([b.high - b.low, (b.high - pc).abs(), (b.low - pc).abs()], axis=1).max(axis=1)
    a = tr.rolling(n).mean()
    a.index = a.index + pd.Timedelta(tf)
    return a.dropna()


def atr_at(series, t):
    i = series.index.searchsorted(t, side="right") - 1
    return series.iloc[i] if i >= 0 else np.nan


def run(sym, od):
    if not len(od):
        return pd.DataFrame()
    tr = simulate(D.load_minutes(sym), pd.DataFrame(od), K.cost_rt(sym), K.slip_base(sym), 0.1,
                  K.financing(sym, float(D.load_minutes(sym).close.iloc[-1])))
    tr["symbol"], tr["strategy"] = sym, "x"
    return one_at_a_time(tr)


def stats(tr):
    if not len(tr):
        return dict(n=0)
    r = tr.sort_values("exit_time").r.values
    w, l = r[r > 0].sum(), -r[r < 0].sum()
    return dict(n=len(r), pf=round(w / l, 2) if l else np.inf, avg_r=round(r.mean(), 3), win=round((r > 0).mean(), 2),
                max_dd_r=round(M.max_dd(r), 1), net_r=round(r.sum(), 1), t=round(r.mean() / r.std() * np.sqrt(len(r)), 2),
                stop_share=round((tr.reason == "sl").mean(), 2), med_risk_bp=round((tr.risk / tr.entry * 1e4).median(), 1))


# ---------------------------------------------------------------------------------------------- 1 Tokyo pre-fix
def tokyo(sym, atr_tf, exit_hm):
    tz = "Asia/Tokyo"
    lm = S.local_minutes(sym, tz)
    daily = S.atr_prev(sym)
    intr = atr_intraday(sym, atr_tf) if atr_tf else None
    g = S.gotobi_days()
    od = []
    for d in sorted(set(lm["date"][lm.dow < 5])):
        if d in S.JP_HOLIDAYS or d not in g:
            continue
        t0 = S.ts(d, S.hm("08:00"), tz)
        a = atr_at(intr, t0) if atr_tf else daily.get(d, np.nan)
        prev = lm["close"].loc[:t0 - pd.Timedelta(minutes=1)]
        if np.isnan(a) or not len(prev):
            continue
        e = prev.iloc[-1]
        od.append(dict(side=1, etype=MARKET, t_active=t0, t_expire=t0 + pd.Timedelta(minutes=5), entry_px=np.nan,
                       sl_px=e - 0.3 * a, tp_px=np.nan, t_exit=S.ts(d, S.hm(exit_hm), tz)))
    return run(sym, od)


# ---------------------------------------------------------------------------------------------- 2 end-of-day momentum
def eod(sym, atr_tf, sl_atr, fmin=0.2):
    tz, o, c = D.CASH_SESSION[sym]
    so, sc = S.hm(o), S.hm(c)
    lm = S.local_minutes(sym, tz)
    daily = S.atr_prev(sym)
    intr = atr_intraday(sym, atr_tf) if atr_tf else None
    sess = S.session_stats(sym, tz, so, sc)
    sess = sess[sess.first_tod == so]
    at = lambda t: lm[lm.tod == t].groupby("date")["close"].last()
    p30, p60 = at(sc - 31), at(sc - 61)
    od = []
    for d in sess.index:
        t0 = S.ts(d, sc - 30, tz)
        a = atr_at(intr, t0) if atr_tf else daily.get(d, np.nan)
        e, r0 = p30.get(d, np.nan), p60.get(d, np.nan)
        if np.isnan(a) or np.isnan(e) or np.isnan(r0) or abs(e - r0) < fmin * a or e == r0:
            continue
        side = int(np.sign(e - r0))
        od.append(dict(side=side, etype=MARKET, t_active=t0, t_expire=t0 + pd.Timedelta(minutes=3), entry_px=np.nan,
                       sl_px=e - side * sl_atr * a, tp_px=np.nan, t_exit=S.ts(d, sc - 1, tz)))
    return run(sym, od)


# ---------------------------------------------------------------------------------------------- 3 JPY 4h channel
def channel(sym, atr_tf, trail, n=20, sl_atr=1.5, max_days=10):
    b = D.load_bars(sym, "4h")
    step = pd.Timedelta("4h")
    hh, ll = b.high.rolling(n).max(), b.low.rolling(n).min()
    daily = S.atr_prev(sym)
    intr = atr_intraday(sym, atr_tf) if atr_tf else None
    key = D.trading_day_ny(b.index)
    od = []
    for i in range(n, len(b) - 1):
        t0 = b.index[i] + step
        a = atr_at(intr, t0) if atr_tf else daily.get(key[i], np.nan)
        if np.isnan(a):
            continue
        for side, lvl in ((1, hh.iloc[i]), (-1, ll.iloc[i])):
            od.append(dict(side=side, etype=STOP, t_active=t0, t_expire=t0 + step, entry_px=lvl, sl_px=lvl - side * sl_atr * a,
                           tp_px=np.nan, t_exit=t0 + pd.Timedelta(days=max_days), trail_dist=trail * a, trail_at_r=0.0))
    return run(sym, od)


# ---------------------------------------------------------------------------------------------- 4 index dip-buy
def dip(sym, atr_tf, drop=1.5, tp=0.75, sl=1.0, max_days=5):
    b = D.load_bars(sym, "4h")
    step = pd.Timedelta("4h")
    d = D.daily_bars(sym)
    mid = (d.high.rolling(20, min_periods=10).max() + d.low.rolling(20, min_periods=10).min()) / 2
    up = (d.close > mid).shift(1)
    daily = S.atr_prev(sym)
    intr = atr_intraday(sym, atr_tf) if atr_tf else None
    key = D.trading_day_ny(b.index)
    ext = b.high.rolling(30).max()
    lowc = b.close.rolling(6).min().shift(1)
    od = []
    for i in range(30, len(b) - 1):
        t0 = b.index[i] + step
        a = atr_at(intr, t0) if atr_tf else daily.get(key[i], np.nan)
        if np.isnan(a) or not up.get(key[i], False):
            continue
        c = b.close.iloc[i]
        if c <= lowc.iloc[i] and ext.iloc[i] - c >= drop * a:
            od.append(dict(side=1, etype=MARKET, t_active=t0, t_expire=t0 + pd.Timedelta(hours=1), entry_px=np.nan,
                           sl_px=c - sl * a, tp_px=c + tp * a, t_exit=t0 + pd.Timedelta(days=max_days)))
    return run(sym, od)


rows = []
def add(strategy, variant, tr, **extra):
    s = stats(tr)
    s.update(strategy=strategy, variant=variant, **extra)
    rows.append(s)
    if len(tr) and "side" in tr and tr.side.nunique() > 1:
        for sd, nm in ((1, "long"), (-1, "short")):
            ss = stats(tr[tr.side == sd]); ss.update(strategy=strategy, variant=f"{variant} [{nm}]", **extra); rows.append(ss)

cat = lambda fs: pd.concat([f for f in fs if len(f)], ignore_index=True) if any(len(f) for f in fs) else pd.DataFrame()

for v, tf, ex in (("ours: daily ATR, exit 09:55", None, "09:55"), ("daily ATR, exit 10:00 (09:45 M15 close)", None, "10:00"),
                  ("theirs: M15 ATR, exit 10:00", "15min", "10:00"), ("M15 ATR, exit 09:55", "15min", "09:55")):
    add("1 Tokyo pre-fix", v, cat([tokyo(s, tf, ex) for s in S.JPY]))
for v, tf, uni in (("ours: daily ATR, 8 idx", None, D.INDICES), ("daily ATR, 7 idx", None, IDX7), ("theirs: M15 ATR, 7 idx", "15min", IDX7)):
    for slm in (0.15, 0.25):
        add("2 EOD momentum", f"{v}, SL {slm}", cat([eod(s, tf, slm) for s in uni]))
for v, tf in (("ours: daily ATR", None), ("H4 ATR", "4h"), ("H1 ATR", "1h")):
    for trail in (2.0, 2.5, 3.0):
        add("3 JPY channel", f"{v}, trail {trail}", cat([channel(s, tf, trail) for s in S.JPY]))
for v, tf, uni in (("ours: daily ATR, 8 idx", None, D.INDICES), ("daily ATR, 7 idx", None, IDX7), ("theirs?: H4 ATR, 7 idx", "4h", IDX7)):
    add("4 Dip-buy", v, cat([dip(s, tf) for s in uni]))

out = pd.DataFrame(rows)[["strategy", "variant", "n", "pf", "avg_r", "win", "max_dd_r", "net_r", "t", "stop_share", "med_risk_bp"]]
out.to_csv(os.path.join(os.path.dirname(__file__), "..", "results", "fbs_reconcile.csv"), index=False)
print(out.to_string(index=False))
