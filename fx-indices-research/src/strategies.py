"""Strategy families -> order tables for engine.simulate.

Every family has a DEFAULT config (fixed before testing, from the literature / common practice) and a small grid
around it. All levels are computed from data strictly before the order's t_active.

Families
  S01 london_breakout     FX       Asian box (00-07 London) -> OCO stops at the box edges during London morning
  S02 orb                 indices  opening range (first N min of the cash session) breakout
  S03 noise_momentum      indices  Zarattini-Aziz-Barbon "noise area" intraday momentum (HH:00/HH:30 checks)
  S04 gap_fade            indices  fade the overnight gap at the cash open toward the prior cash close
  S05 sweep_reversal      both     15m bar pokes through the prior day high/low and closes back inside -> fade
  S06 trend_pullback      both     20-day breakout trend, 1h pullback >= 0.5 ATR, enter on 1h resumption bar
  S07 asian_fade          FX       fade 15m breakouts of the recent range during the quiet Asian session
  S08 tokyo_fix           JPY      long USDJPY/EURJPY into the 09:55 JST fix (gotobi days / all days)
  S09 news_momentum       both     US 08:30 ET release shock: follow (or fade) the first 15m candle
  S10 eur_seasonality     FX       Breedon-Ranaldo: EUR/GBP weak in European hours, strong in US afternoon
  S11 nr_breakout         both     NR4 inside-bar (1h/4h) OCO breakout
  S12 last_half_hour      indices  Gao-Han-Li-Zhou intraday momentum: first half-hour return -> last half-hour
  S13 overnight_drift     indices  long from the cash close to the next cash open
"""
from __future__ import annotations

import itertools
from functools import lru_cache

import numpy as np
import pandas as pd

import data as D
from engine import MARKET, STOP, LIMIT

UTC = "UTC"


# ------------------------------------------------------------------------------------------------ helpers
@lru_cache(maxsize=None)
def atr_prev(sym: str, n: int = 14) -> pd.Series:
    """Daily ATR (NY trading day, true range) known at the START of each trading day (uses days < d)."""
    d = D.daily_bars(sym)
    pc = d["close"].shift()
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=5).mean().shift(1)


@lru_cache(maxsize=None)
def local_minutes(sym: str, tz: str) -> pd.DataFrame:
    m = D.load_minutes(sym)
    loc = m.index.tz_convert(tz)
    out = m.copy()
    out["date"] = loc.tz_localize(None).normalize()
    out["tod"] = loc.hour * 60 + loc.minute
    out["dow"] = loc.dayofweek
    return out


def ts(date, minutes_of_day: float, tz: str) -> pd.Timestamp:
    """local date + minutes -> UTC timestamp"""
    t = pd.Timestamp(date) + pd.Timedelta(minutes=float(minutes_of_day))
    return t.tz_localize(tz, nonexistent="shift_forward", ambiguous=True).tz_convert(UTC)


def hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _mk(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["side", "etype", "t_active", "t_expire", "entry_px", "sl_px", "tp_px", "t_exit"])
    return pd.DataFrame(rows)


def session_stats(sym: str, tz: str, start: int, end: int) -> pd.DataFrame:
    """Per local date: open/high/low/close of minutes with start <= tod < end."""
    lm = local_minutes(sym, tz)
    s = lm[(lm.tod >= start) & (lm.tod < end) & (lm.dow < 5)]
    g = s.groupby("date")
    return pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                         "close": g["close"].last(), "n": g["close"].size(), "first_tod": g["tod"].first()})


def grid(**kw):
    keys = list(kw)
    for vals in itertools.product(*[kw[k] for k in keys]):
        yield dict(zip(keys, vals))


# ------------------------------------------------------------------------------------------------ S01
def london_breakout(sym, box_max_atr=0.6, box_min_atr=0.1, tp_mult=1.0, sl="edge", until="11:00", exit_at="16:00"):
    tz = "Europe/London"
    box = session_stats(sym, tz, 0, hm("07:00"))
    atr = atr_prev(sym)
    rows = []
    for d, b in box.iterrows():
        a = atr.get(d, np.nan)
        if np.isnan(a) or b.n < 300 or pd.Timestamp(d).dayofweek >= 5:
            continue
        hgt = b.high - b.low
        if not (box_min_atr * a <= hgt <= box_max_atr * a):
            continue
        buf = 0.03 * a
        t0, t1, tx = ts(d, hm("07:00"), tz), ts(d, hm(until), tz), ts(d, hm(exit_at), tz)
        mid = (b.high + b.low) / 2
        for side in (1, -1):
            e = b.high + buf if side > 0 else b.low - buf
            stop = (b.low - buf if side > 0 else b.high + buf) if sl == "edge" else mid
            tp = e + side * tp_mult * hgt if tp_mult else np.nan
            rows.append(dict(side=side, etype=STOP, t_active=t0, t_expire=t1, entry_px=e, sl_px=stop, tp_px=tp,
                             t_exit=tx, group=f"{d.date()}"))
    return _mk(rows)


# ------------------------------------------------------------------------------------------------ S02
def orb(sym, or_min=30, tp_mult=2.0, sl="edge", active_h=3.0, max_or_atr=0.5):
    tz, o, c = D.CASH_SESSION[sym]
    so, sc = hm(o), hm(c)
    orng = session_stats(sym, tz, so, so + or_min)
    atr = atr_prev(sym)
    rows = []
    for d, b in orng.iterrows():
        a = atr.get(d, np.nan)
        if np.isnan(a) or b.n < or_min * 0.8 or b.first_tod != so:
            continue
        hgt = b.high - b.low
        if hgt <= 0 or hgt > max_or_atr * a:
            continue
        t0 = ts(d, so + or_min, tz)
        t1 = ts(d, so + or_min + active_h * 60, tz)
        tx = ts(d, sc - 5, tz)
        mid = (b.high + b.low) / 2
        for side in (1, -1):
            e = b.high if side > 0 else b.low
            stop = (b.low if side > 0 else b.high) if sl == "edge" else mid
            risk = abs(e - stop)
            tp = e + side * tp_mult * risk if tp_mult else np.nan
            rows.append(dict(side=side, etype=STOP, t_active=t0, t_expire=t1, entry_px=e, sl_px=stop, tp_px=tp,
                             t_exit=tx, group=f"{d.date()}"))
    return _mk(rows)


# ------------------------------------------------------------------------------------------------ S03
def noise_momentum(sym, lookback=14, vm=1.0, hard_sl_atr=0.5, use_vwap=True, step=30):
    """Noise boundaries: open*(1 +- vm*sigma(t)), sigma(t) = mean |close(t)/open-1| over the last `lookback`
    days at the same minute-of-session. Checks every `step` minutes; first signal of the day only;
    exit at the first later check where price is back inside max(UB, VWAP) (long) / min(LB, VWAP) (short),
    or at the cash close; a hard stop at hard_sl_atr * ATR protects between checks."""
    tz, o, c = D.CASH_SESSION[sym]
    so, sc = hm(o), hm(c)
    lm = local_minutes(sym, tz)
    s = lm[(lm.tod >= so) & (lm.tod < sc) & (lm.dow < 5)].copy()
    first_tod = s.groupby("date")["tod"].transform("first")
    s = s[first_tod == so]
    opens = s.groupby("date")["open"].first()
    closes = s.groupby("date")["close"].last()
    prev_close = closes.shift()
    checks = list(range(so + step, sc - 15 + 1, step))
    # close of the minute just before each check
    s["cum_pv"] = (s["close"] * s["volume"].clip(lower=1)).groupby(s["date"]).cumsum()
    s["cum_v"] = s["volume"].clip(lower=1).groupby(s["date"]).cumsum()
    s["vwap"] = s["cum_pv"] / s["cum_v"]
    snap = s[s.tod.isin([t - 1 for t in checks])].copy()
    snap["check"] = snap.tod + 1
    px = snap.pivot_table(index="date", columns="check", values="close")
    vw = snap.pivot_table(index="date", columns="check", values="vwap")
    move = (px.div(opens, axis=0) - 1).abs()
    sigma = move.rolling(lookback, min_periods=lookback).mean().shift(1)
    atr = atr_prev(sym)
    rows = []
    for d in px.index:
        if d not in sigma.index or sigma.loc[d].isna().all() or np.isnan(prev_close.get(d, np.nan)):
            continue
        op, pc, a = opens[d], prev_close[d], atr.get(d, np.nan)
        if np.isnan(a):
            continue
        ub = max(op, pc) * (1 + vm * sigma.loc[d])
        lb = min(op, pc) * (1 - vm * sigma.loc[d])
        p = px.loc[d]
        side, t_in = 0, None
        for t in checks[:-1]:
            if np.isnan(p.get(t, np.nan)):
                continue
            if p[t] > ub[t]:
                side, t_in = 1, t
                break
            if p[t] < lb[t]:
                side, t_in = -1, t
                break
        if not side:
            continue
        t_out = sc - 5
        for t in checks:
            if t <= t_in or np.isnan(p.get(t, np.nan)):
                continue
            ref_u = max(ub[t], vw.loc[d, t]) if use_vwap else ub[t]
            ref_l = min(lb[t], vw.loc[d, t]) if use_vwap else lb[t]
            if (side > 0 and p[t] < ref_u) or (side < 0 and p[t] > ref_l):
                t_out = t
                break
        e_est = p[t_in]
        rows.append(dict(side=side, etype=MARKET, t_active=ts(d, t_in, tz), t_expire=ts(d, t_in + 5, tz),
                         entry_px=np.nan, sl_px=e_est - side * hard_sl_atr * a, tp_px=np.nan, t_exit=ts(d, t_out, tz)))
    return _mk(rows)


# ------------------------------------------------------------------------------------------------ S04
def gap_fade(sym, gmin=0.15, gmax=0.6, target=1.0, sl_gap=1.0, delay=0, exit_after_h=2.5):
    tz, o, c = D.CASH_SESSION[sym]
    so, sc = hm(o), hm(c)
    sess = session_stats(sym, tz, so, sc)
    sess = sess[sess.first_tod == so]
    prev_close = sess["close"].shift()
    lm = local_minutes(sym, tz)
    at_entry = lm[lm.tod == so + delay].groupby("date")["open"].first()
    atr = atr_prev(sym)
    rows = []
    for d in sess.index:
        pc, a = prev_close.get(d, np.nan), atr.get(d, np.nan)
        e = at_entry.get(d, np.nan)
        if np.isnan(pc) or np.isnan(a) or np.isnan(e):
            continue
        gap = e - pc
        if not (gmin * a <= abs(gap) <= gmax * a):
            continue
        side = -int(np.sign(gap))
        tp = e + side * target * abs(gap)
        stop = e - side * sl_gap * abs(gap)
        rows.append(dict(side=side, etype=MARKET, t_active=ts(d, so + delay, tz), t_expire=ts(d, so + delay + 5, tz),
                         entry_px=np.nan, sl_px=stop, tp_px=tp, t_exit=ts(d, so + delay + exit_after_h * 60, tz)))
    return _mk(rows)


# ------------------------------------------------------------------------------------------------ S05
def _prior_levels(sym):
    """prior-day high/low: NY trading day for FX, prior cash session for indices. index = local date, tz."""
    if sym in D.INDICES:
        tz, o, c = D.CASH_SESSION[sym]
        sess = session_stats(sym, tz, hm(o), hm(c))
        sess = sess[sess.n > 60]
        return sess[["high", "low"]].shift(1), tz, (hm(o) + 30, hm(c) - 30)
    d = D.daily_bars(sym)
    return d[["high", "low"]].shift(1), "Europe/London", (hm("07:00"), hm("16:00"))


def sweep_reversal(sym, tf=15, tp_r=2.0, min_poke_atr=0.0, close_back="inside", buf_atr=0.05, max_hold_h=8):
    lv, tz, (w0, w1) = _prior_levels(sym)
    atr = atr_prev(sym)
    bars = D.load_bars(sym, f"{tf}min")
    loc = bars.index.tz_convert(tz)
    # map each bar to the "day" key used for levels
    if sym in D.INDICES:
        key = loc.tz_localize(None).normalize()
    else:
        key = D.trading_day_ny(bars.index)
    tod = loc.hour * 60 + loc.minute
    rows = []
    used = set()
    H, L, C, O = bars.high.values, bars.low.values, bars.close.values, bars.open.values
    for i in range(len(bars)):
        if not (w0 <= tod[i] < w1) or loc[i].dayofweek >= 5:
            continue
        k = key[i]
        if k not in lv.index:
            continue
        pdh, pdl = lv.at[k, "high"], lv.at[k, "low"]
        a = atr.get(k, np.nan)
        if np.isnan(pdh) or np.isnan(a):
            continue
        rng = H[i] - L[i]
        t_next = bars.index[i] + pd.Timedelta(minutes=tf)
        for side, cond in ((-1, H[i] > pdh + min_poke_atr * a and C[i] < pdh), (1, L[i] < pdl - min_poke_atr * a and C[i] > pdl)):
            if not cond or (k, side) in used:
                continue
            if close_back == "strong" and ((side < 0 and C[i] > L[i] + 0.5 * rng) or (side > 0 and C[i] < H[i] - 0.5 * rng)):
                continue
            stop = H[i] + buf_atr * a if side < 0 else L[i] - buf_atr * a
            e_est = C[i]
            risk = abs(stop - e_est)
            if risk <= 0 or risk > 0.6 * a:
                continue
            used.add((k, side))
            rows.append(dict(side=side, etype=MARKET, t_active=t_next, t_expire=t_next + pd.Timedelta(minutes=5),
                             entry_px=np.nan, sl_px=stop, tp_px=e_est + side * tp_r * risk,
                             t_exit=t_next + pd.Timedelta(hours=max_hold_h)))
    return _mk(rows)


# ------------------------------------------------------------------------------------------------ S06
def trend_pullback(sym, don=20, recent=5, pb_atr=0.5, tp_r=2.0, max_hold_h=72, sl_buf_atr=0.1):
    d = D.daily_bars(sym)
    atr = atr_prev(sym)
    hh = d["high"].rolling(don, min_periods=10).max()
    ll = d["low"].rolling(don, min_periods=10).min()
    new_high = (d["high"] >= hh)          # day made a new N-day high
    new_low = (d["low"] <= ll)
    # trend state known at the start of day k (uses days < k)
    up = new_high.rolling(recent).max().shift(1).fillna(0).astype(bool)
    dn = new_low.rolling(recent).max().shift(1).fillna(0).astype(bool)
    mid = ((hh + ll) / 2).shift(1)
    top = d["high"].rolling(recent).max().shift(1)
    bot = d["low"].rolling(recent).min().shift(1)
    h1 = D.load_bars(sym, "1h")
    key = D.trading_day_ny(h1.index)
    rows = []
    H, L, C = h1.high.values, h1.low.values, h1.close.values
    run_hi = run_lo = None
    busy_until = None
    for i in range(2, len(h1)):
        k = key[i]
        if k not in d.index:
            continue
        a = atr.get(k, np.nan)
        if np.isnan(a):
            continue
        t_next = h1.index[i] + pd.Timedelta(hours=1)
        if busy_until is not None and t_next < busy_until:
            continue
        if t_next.tz_convert("America/New_York").dayofweek == 4 and t_next.tz_convert("America/New_York").hour >= 12:
            continue  # no new trades into the weekend
        # running extreme since the recent-high window (use prior-days top + today's bars so far)
        day_hi = H[max(0, i - 24):i].max()
        day_lo = L[max(0, i - 24):i].min()
        if up.get(k, False) and not dn.get(k, False):
            hi = max(top[k], day_hi)
            pb_low = L[max(0, i - 24):i + 1].min()
            if hi - C[i] >= pb_atr * a and C[i] > mid[k] and C[i] > H[i - 1] and C[i - 1] <= H[i - 2]:
                stop = pb_low - sl_buf_atr * a
                risk = C[i] - stop
                if 0 < risk <= 1.0 * a:
                    rows.append(dict(side=1, etype=MARKET, t_active=t_next, t_expire=t_next + pd.Timedelta(minutes=10),
                                     entry_px=np.nan, sl_px=stop, tp_px=C[i] + tp_r * risk,
                                     t_exit=t_next + pd.Timedelta(hours=max_hold_h)))
                    busy_until = t_next + pd.Timedelta(hours=6)
        elif dn.get(k, False) and not up.get(k, False):
            lo = min(bot[k], day_lo)
            pb_high = H[max(0, i - 24):i + 1].max()
            if C[i] - lo >= pb_atr * a and C[i] < mid[k] and C[i] < L[i - 1] and C[i - 1] >= L[i - 2]:
                stop = pb_high + sl_buf_atr * a
                risk = stop - C[i]
                if 0 < risk <= 1.0 * a:
                    rows.append(dict(side=-1, etype=MARKET, t_active=t_next, t_expire=t_next + pd.Timedelta(minutes=10),
                                     entry_px=np.nan, sl_px=stop, tp_px=C[i] - tp_r * risk,
                                     t_exit=t_next + pd.Timedelta(hours=max_hold_h)))
                    busy_until = t_next + pd.Timedelta(hours=6)
    return _mk(rows)


# ------------------------------------------------------------------------------------------------ S07
def asian_fade(sym, lookback=8, sl_mult=1.0, start="19:30", end="00:30", exit_at="02:00"):
    """15m bars, New York clock. Session start..end (crosses midnight). Short when a bar closes above the prior
    `lookback` bars' high (long mirror). TP: midpoint of that range, SL: sl_mult * range beyond entry."""
    tz = "America/New_York"
    b = D.load_bars(sym, "15min")
    loc = b.index.tz_convert(tz)
    tod = loc.hour * 60 + loc.minute
    s0, s1, sx = hm(start), hm(end), hm(exit_at)
    in_sess = (tod >= s0) | (tod < s1)
    hh = b.high.rolling(lookback).max().shift(1)
    ll = b.low.rolling(lookback).min().shift(1)
    atr = atr_prev(sym)
    key = D.trading_day_ny(b.index)
    rows, used = [], set()
    for i in np.where(in_sess)[0]:
        if np.isnan(hh.iloc[i]):
            continue
        k = key[i]
        a = atr.get(k, np.nan)
        if np.isnan(a) or pd.Timestamp(k).dayofweek >= 5:
            continue
        rng = hh.iloc[i] - ll.iloc[i]
        if rng <= 0 or rng > 0.5 * a:
            continue
        c = b.close.iloc[i]
        side = -1 if c > hh.iloc[i] else (1 if c < ll.iloc[i] else 0)
        if not side or (k, side) in used:
            continue
        used.add((k, side))
        t_next = b.index[i] + pd.Timedelta(minutes=15)
        # exit time: next occurrence of exit_at NY
        lt = t_next.tz_convert(tz)
        ex = lt.normalize() + pd.Timedelta(minutes=sx)
        if ex <= lt:
            ex += pd.Timedelta(days=1)
        mid = (hh.iloc[i] + ll.iloc[i]) / 2
        rows.append(dict(side=side, etype=MARKET, t_active=t_next, t_expire=t_next + pd.Timedelta(minutes=5),
                         entry_px=np.nan, sl_px=c - side * sl_mult * rng, tp_px=mid, t_exit=ex.tz_convert(UTC)))
    return _mk(rows)


# ------------------------------------------------------------------------------------------------ S08
JP_HOLIDAYS = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-12", "2026-02-11", "2026-02-23", "2026-03-20",
                              "2026-04-29", "2026-05-04", "2026-05-05", "2026-05-06", "2026-07-20", "2026-08-11",
                              "2026-09-21", "2026-09-22", "2026-09-23", "2026-10-12", "2026-11-03", "2026-11-23"])


def gotobi_days(start="2026-01-01", end="2026-12-31") -> set:
    bdays = pd.bdate_range(start, end)
    bdays = bdays[~bdays.isin(JP_HOLIDAYS)]
    out = set()
    for y, mth in sorted({(d.year, d.month) for d in bdays}):
        mdays = bdays[(bdays.year == y) & (bdays.month == mth)]
        for dom in (5, 10, 15, 20, 25):
            cand = mdays[mdays.day <= dom]
            if len(cand):
                out.add(cand[-1].normalize())
        out.add(mdays[-1].normalize())  # month end
    return out


def tokyo_fix(sym, entry="08:00", exit_at="09:55", days="gotobi", side=1, sl_atr=0.3):
    tz = "Asia/Tokyo"
    lm = local_minutes(sym, tz)
    atr = atr_prev(sym)
    g = gotobi_days()
    dates = sorted(set(lm["date"][lm.dow < 5]))
    rows = []
    for d in dates:
        if d in JP_HOLIDAYS:
            continue
        if days == "gotobi" and d not in g:
            continue
        if days == "other" and d in g:
            continue
        a = atr.get(d, np.nan)
        if np.isnan(a):
            continue
        t0 = ts(d, hm(entry), tz)
        # entry px estimate for the stop: last close before t0
        prev = lm.loc[:t0 - pd.Timedelta(minutes=1)]
        if not len(prev):
            continue
        e_est = prev["close"].iloc[-1]
        rows.append(dict(side=side, etype=MARKET, t_active=t0, t_expire=t0 + pd.Timedelta(minutes=5), entry_px=np.nan,
                         sl_px=e_est - side * sl_atr * a, tp_px=np.nan, t_exit=ts(d, hm(exit_at), tz)))
    return _mk(rows)


# ------------------------------------------------------------------------------------------------ S09
def news_momentum(sym, slot="08:30", k=2.5, body=0.5, sl="mid", tp_r=2.0, exit_at="12:00", mode="follow", lookback=20):
    """US release slot (New York time). Signal = the 15m candle starting at `slot` has range >= k * median range of
    the same candle over the previous `lookback` weekdays and a body >= `body` * range. follow: trade in the candle's
    direction at the next candle open; fade: the opposite way. SL: candle midpoint ('mid') or far extreme ('ext')."""
    tz = "America/New_York"
    lm = local_minutes(sym, tz)
    s0 = hm(slot)
    w = lm[(lm.tod >= s0) & (lm.tod < s0 + 15) & (lm.dow < 5)]
    g = w.groupby("date")
    c = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last(), "n": g.size()})
    c = c[c.n >= 12]
    c["rng"] = c.high - c.low
    c["med"] = c["rng"].rolling(lookback, min_periods=10).median().shift(1)
    rows = []
    for d, r in c.iterrows():
        if np.isnan(r.med) or r.rng < k * r.med or abs(r.close - r.open) < body * r.rng:
            continue
        direction = int(np.sign(r.close - r.open))
        side = direction if mode == "follow" else -direction
        if sl == "mid":
            stop = (r.high + r.low) / 2
        else:
            stop = r.low if side > 0 else r.high
        if mode == "fade":
            stop = r.high if side < 0 else r.low   # beyond the candle's extreme
            stop = stop + (-side) * 0.25 * r.rng
        t0 = ts(d, s0 + 15, tz)
        risk = abs(r.close - stop)
        if risk <= 0:
            continue
        rows.append(dict(side=side, etype=MARKET, t_active=t0, t_expire=t0 + pd.Timedelta(minutes=5), entry_px=np.nan,
                         sl_px=stop, tp_px=r.close + side * tp_r * risk if tp_r else np.nan, t_exit=ts(d, hm(exit_at), tz)))
    return _mk(rows)


# ------------------------------------------------------------------------------------------------ S10
def eur_seasonality(sym, leg="europe", sl_atr=0.4):
    """Breedon & Ranaldo (2013): a currency tends to depreciate in its own trading hours.
    europe leg: short EUR/GBP vs USD 03:00 -> 11:00 NY. us leg: long 11:00 -> 16:00 NY."""
    tz = "America/New_York"
    lm = local_minutes(sym, tz)
    atr = atr_prev(sym)
    t_in, t_out, side = (hm("03:00"), hm("11:00"), -1) if leg == "europe" else (hm("11:00"), hm("16:00"), 1)
    if sym.startswith("USD"):
        side = -side  # USDxxx: foreign currency is the quote
    rows = []
    for d in sorted(set(lm["date"][lm.dow < 5])):
        a = atr.get(d, np.nan)
        if np.isnan(a):
            continue
        t0 = ts(d, t_in, tz)
        prev = lm["close"].loc[:t0 - pd.Timedelta(minutes=1)]
        if not len(prev):
            continue
        e_est = prev.iloc[-1]
        rows.append(dict(side=side, etype=MARKET, t_active=t0, t_expire=t0 + pd.Timedelta(minutes=5), entry_px=np.nan,
                         sl_px=e_est - side * sl_atr * a, tp_px=np.nan, t_exit=ts(d, t_out, tz)))
    return _mk(rows)


# ------------------------------------------------------------------------------------------------ S11
def nr_breakout(sym, tf="4h", nr=4, tp_mult=2.0, valid_bars=2, hold_bars=6, inside=True):
    b = D.load_bars(sym, tf)
    step = pd.Timedelta(tf)
    rng = b.high - b.low
    is_nr = rng <= rng.rolling(nr).min()
    is_ib = (b.high <= b.high.shift()) & (b.low >= b.low.shift())
    sig = is_nr & (is_ib if inside else True)
    atr = atr_prev(sym)
    key = D.trading_day_ny(b.index)
    rows = []
    for i in np.where(sig.values)[0]:
        a = atr.get(key[i], np.nan)
        r = rng.iloc[i]
        if np.isnan(a) or r <= 0.05 * a:
            continue
        t0 = b.index[i] + step
        ny = t0.tz_convert("America/New_York")
        if ny.dayofweek == 4 and ny.hour >= 9:
            continue
        hi, lo = b.high.iloc[i], b.low.iloc[i]
        for side in (1, -1):
            e = hi if side > 0 else lo
            stop = lo if side > 0 else hi
            rows.append(dict(side=side, etype=STOP, t_active=t0, t_expire=t0 + valid_bars * step, entry_px=e, sl_px=stop,
                             tp_px=e + side * tp_mult * r, t_exit=t0 + hold_bars * step, group=str(b.index[i])))
    return _mk(rows)


# ------------------------------------------------------------------------------------------------ S12
def last_half_hour(sym, sig="first", sl_atr=0.25, min_move_atr=0.0):
    """Gao, Han, Li & Zhou (2018): the first half-hour return (prior close -> open+30) predicts the last half-hour.
    sig='first' uses prior cash close -> 10:00; sig='penult' uses the 12th half hour (15:00 -> 15:30)."""
    tz, o, c = D.CASH_SESSION[sym]
    so, sc = hm(o), hm(c)
    lm = local_minutes(sym, tz)
    atr = atr_prev(sym)
    sess = session_stats(sym, tz, so, sc)
    sess = sess[sess.first_tod == so]
    pc = sess["close"].shift()
    at = lambda t: lm[lm.tod == t].groupby("date")["close"].last()
    p30, p_pen0, p_pen1 = at(so + 29), at(sc - 61), at(sc - 31)
    rows = []
    for d in sess.index:
        a = atr.get(d, np.nan)
        if np.isnan(a) or np.isnan(pc.get(d, np.nan)):
            continue
        if sig == "first":
            mv = p30.get(d, np.nan) - pc[d]
        else:
            mv = p_pen1.get(d, np.nan) - p_pen0.get(d, np.nan)
        if np.isnan(mv) or abs(mv) < min_move_atr * a or mv == 0:
            continue
        side = int(np.sign(mv))
        t0 = ts(d, sc - 30, tz)
        e_est = p_pen1.get(d, np.nan)
        if np.isnan(e_est):
            continue
        rows.append(dict(side=side, etype=MARKET, t_active=t0, t_expire=t0 + pd.Timedelta(minutes=3), entry_px=np.nan,
                         sl_px=e_est - side * sl_atr * a, tp_px=np.nan, t_exit=ts(d, sc - 1, tz)))
    return _mk(rows)


# ------------------------------------------------------------------------------------------------ S13
def overnight_drift(sym, sl_atr=0.6, entry_before_close=5, exit_after_open=5, skip_friday=True):
    tz, o, c = D.CASH_SESSION[sym]
    so, sc = hm(o), hm(c)
    lm = local_minutes(sym, tz)
    atr = atr_prev(sym)
    dates = sorted(set(lm["date"][lm.dow < 5]))
    rows = []
    for i, d in enumerate(dates[:-1]):
        if skip_friday and pd.Timestamp(d).dayofweek == 4:
            continue
        a = atr.get(d, np.nan)
        if np.isnan(a):
            continue
        t0 = ts(d, sc - entry_before_close, tz)
        prev = lm["close"].loc[:t0 - pd.Timedelta(minutes=1)]
        e_est = prev.iloc[-1]
        nxt = dates[i + 1]
        rows.append(dict(side=1, etype=MARKET, t_active=t0, t_expire=t0 + pd.Timedelta(minutes=3), entry_px=np.nan,
                         sl_px=e_est - sl_atr * a, tp_px=np.nan, t_exit=ts(nxt, so + exit_after_open, tz)))
    return _mk(rows)


# ------------------------------------------------------------------------------------------------ registry
USD_FX = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF"]
US_IDX = ["US500", "NAS100", "US30", "US2000"]

FAMILIES = {
    "S01_london_breakout": dict(fn=london_breakout, universe=D.FX,
                                default=dict(box_max_atr=0.6, tp_mult=1.0, sl="edge", until="11:00", exit_at="16:00"),
                                grid=dict(box_max_atr=[0.4, 0.6, 1.0], tp_mult=[1.0, 2.0, 0], sl=["edge", "mid"], until=["10:00", "12:00"])),
    "S02_orb": dict(fn=orb, universe=D.INDICES,
                    default=dict(or_min=30, tp_mult=2.0, sl="edge", active_h=3.0),
                    grid=dict(or_min=[15, 30, 60], tp_mult=[1.0, 2.0, 0], sl=["edge", "mid"])),
    "S03_noise_momentum": dict(fn=noise_momentum, universe=D.INDICES,
                               default=dict(lookback=14, vm=1.0, hard_sl_atr=0.5, use_vwap=True),
                               grid=dict(vm=[0.8, 1.0, 1.25, 1.5], use_vwap=[True, False], hard_sl_atr=[0.35, 0.5, 0.75])),
    "S04_gap_fade": dict(fn=gap_fade, universe=D.INDICES,
                         default=dict(gmin=0.15, gmax=0.6, target=1.0, sl_gap=1.0, delay=0),
                         grid=dict(gmin=[0.1, 0.2], gmax=[0.5, 1.0], target=[0.5, 1.0], sl_gap=[0.75, 1.5], delay=[0, 15])),
    "S05_sweep_reversal": dict(fn=sweep_reversal, universe=D.ALL,
                               default=dict(tf=15, tp_r=2.0, close_back="inside"),
                               grid=dict(tf=[15, 60], tp_r=[1.0, 2.0, 3.0], close_back=["inside", "strong"])),
    "S06_trend_pullback": dict(fn=trend_pullback, universe=D.ALL,
                               default=dict(don=20, pb_atr=0.5, tp_r=2.0, max_hold_h=72),
                               grid=dict(pb_atr=[0.35, 0.5, 0.75], tp_r=[1.5, 2.0, 3.0], max_hold_h=[24, 72])),
    "S07_asian_fade": dict(fn=asian_fade, universe=D.FX,
                           default=dict(lookback=8, sl_mult=1.0),
                           grid=dict(lookback=[8, 16], sl_mult=[0.5, 1.0, 1.5], start=["19:30", "18:30"])),
    "S08_tokyo_fix": dict(fn=tokyo_fix, universe=["USDJPY", "EURJPY"],
                          default=dict(entry="08:00", exit_at="09:55", days="gotobi"),
                          grid=dict(entry=["07:00", "08:00", "09:00"], days=["gotobi", "all", "other"])),
    "S09_news_momentum": dict(fn=news_momentum, universe=USD_FX + US_IDX,
                              default=dict(slot="08:30", k=2.5, sl="mid", tp_r=2.0, exit_at="12:00", mode="follow"),
                              grid=dict(k=[2.0, 3.0], sl=["mid", "ext"], tp_r=[1.0, 2.0, 0], mode=["follow", "fade"])),
    "S10_eur_seasonality": dict(fn=eur_seasonality, universe=["EURUSD", "GBPUSD", "USDCHF"],
                                default=dict(leg="europe", sl_atr=0.4),
                                grid=dict(leg=["europe", "us"], sl_atr=[0.3, 0.6])),
    "S11_nr_breakout": dict(fn=nr_breakout, universe=D.ALL,
                            default=dict(tf="4h", nr=4, tp_mult=2.0, inside=True),
                            grid=dict(tf=["1h", "4h"], tp_mult=[1.0, 2.0, 3.0], inside=[True, False])),
    "S12_last_half_hour": dict(fn=last_half_hour, universe=D.INDICES,
                               default=dict(sig="first", sl_atr=0.25),
                               grid=dict(sig=["first", "penult"], sl_atr=[0.15, 0.25, 0.4], min_move_atr=[0.0, 0.2])),
    "S13_overnight_drift": dict(fn=overnight_drift, universe=D.INDICES,
                                default=dict(sl_atr=0.6, skip_friday=True),
                                grid=dict(sl_atr=[0.4, 0.6, 1.0], skip_friday=[True, False])),
}


# ------------------------------------------------------------------------------------------------ round 2
def shock(sym, tf="15min", k=2.5, mode="follow", hold_bars=16, sl_mult=1.0, tp_frac=0.0, sigma_days=20, session=None):
    """Large-bar reaction. Trigger: |bar log-return| >= k * trailing sigma (sigma_days of same-size bars, rollover
    minutes excluded). follow: trade the bar's direction; fade: trade against it. Entry at the next bar open.
    SL = sl_mult * trigger-bar range from the trigger close; TP (optional) = tp_frac * range; time exit hold_bars.
    session: None (any time outside the rollover) or 'cash' (index cash hours)."""
    from engine import rollover_mask
    m = D.load_minutes(sym)
    m = m[rollover_mask(m.index)]
    b = D.resample(m, tf)
    step = pd.Timedelta(tf)
    per_day = int(pd.Timedelta("1D") / step)
    lc = np.log(b.close)
    r = lc.diff()
    gap = b.index.to_series().diff() > step * 1.5
    r[gap.values] = np.nan
    sig = r.rolling(per_day * sigma_days, min_periods=per_day * 5).std().shift(1)
    ev = (r.abs() >= k * sig).values
    if session == "cash" and sym in D.CASH_SESSION:
        tz, o, c = D.CASH_SESSION[sym]
        loc = b.index.tz_convert(tz)
        tod = loc.hour * 60 + loc.minute
        ev &= (tod >= hm(o)) & (tod < hm(c) - int(step / pd.Timedelta("1min")))
    rows = []
    H, L, C = b.high.values, b.low.values, b.close.values
    rv = r.values
    for i in np.where(ev)[0]:
        t_next = b.index[i] + step
        ny = t_next.tz_convert("America/New_York")
        if ny.dayofweek == 4 and ny.hour >= 15 or ny.dayofweek >= 5:
            continue
        rng = H[i] - L[i]
        if rng <= 0:
            continue
        d = int(np.sign(rv[i]))
        side = d if mode == "follow" else -d
        stop = C[i] - side * sl_mult * rng
        tp = C[i] + side * tp_frac * rng if tp_frac else np.nan
        rows.append(dict(side=side, etype=MARKET, t_active=t_next, t_expire=t_next + pd.Timedelta(minutes=5), entry_px=np.nan,
                         sl_px=stop, tp_px=tp, t_exit=t_next + hold_bars * step))
    return _mk(rows)


JPY = ["USDJPY", "EURJPY"]
FX_MAJ = ["EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "EURGBP"]
ROW_IDX = ["GER40", "EUSTX50", "JPN225", "AUS200"]

# Round-2 candidates: ONE config each, fixed from the first-half (Feb-May) event study before looking at Jun-Sep.
ROUND2 = {
    "R2a_jpy_shock_follow": dict(fn=shock, universe=JPY, default=dict(tf="15min", k=2.5, mode="follow", hold_bars=16, sl_mult=1.0)),
    "R2b_usidx_shock_fade": dict(fn=shock, universe=US_IDX, default=dict(tf="15min", k=2.5, mode="fade", hold_bars=16, sl_mult=1.0, tp_frac=0.5)),
    "R2c_fxmaj_shock_fade": dict(fn=shock, universe=FX_MAJ, default=dict(tf="15min", k=2.5, mode="fade", hold_bars=16, sl_mult=1.0, tp_frac=0.5)),
    "R2d_rowidx_1h_follow": dict(fn=shock, universe=ROW_IDX, default=dict(tf="1h", k=2.0, mode="follow", hold_bars=4, sl_mult=1.0)),
}


# ------------------------------------------------------------------------------------------------ round 3 (multi-day, 4h chart)
def donchian_4h(sym, n=20, trail_atr=2.0, sl_atr=1.5, max_days=10):
    """Price-channel breakout on 4h bars (both sides): stop order at the highest high / lowest low of the last n bars,
    re-issued every bar while flat; initial SL sl_atr*ATR, trailing trail_atr*ATR from the best price; time stop."""
    b = D.load_bars(sym, "4h")
    step = pd.Timedelta("4h")
    hh = b.high.rolling(n).max()
    ll = b.low.rolling(n).min()
    atr = atr_prev(sym)
    key = D.trading_day_ny(b.index)
    rows = []
    for i in range(n, len(b) - 1):
        a = atr.get(key[i], np.nan)
        if np.isnan(a):
            continue
        t0 = b.index[i] + step
        for side, lvl in ((1, hh.iloc[i]), (-1, ll.iloc[i])):
            rows.append(dict(side=side, etype=STOP, t_active=t0, t_expire=t0 + step, entry_px=lvl,
                             sl_px=lvl - side * sl_atr * a, tp_px=np.nan, t_exit=t0 + pd.Timedelta(days=max_days),
                             trail_dist=trail_atr * a, trail_at_r=0.0))
    return _mk(rows)


def dip_buy(sym, drop_atr=1.0, lookback_days=5, tp_atr=1.0, sl_atr=1.5, max_days=5, trend=True, side=1):
    """Buy the dip in an up-trend (side=-1: sell the rip in a down-trend), 4h chart.
    Setup at a 4h close: close <= lowest close of the prior 6 bars (1-day low) and >= drop_atr*ATR below the
    lookback_days high; trend filter: prior daily close above the 20-day channel midpoint.
    Entry next bar open; TP tp_atr*ATR, SL sl_atr*ATR, time stop max_days."""
    b = D.load_bars(sym, "4h")
    step = pd.Timedelta("4h")
    d = D.daily_bars(sym)
    mid = ((d.high.rolling(20, min_periods=10).max() + d.low.rolling(20, min_periods=10).min()) / 2)
    up = (d.close > mid).shift(1)
    dn = (d.close < mid).shift(1)
    atr = atr_prev(sym)
    key = D.trading_day_ny(b.index)
    look = int(lookback_days * 6)
    ext = b.high.rolling(look).max() if side > 0 else b.low.rolling(look).min()
    lowc = b.close.rolling(6).min().shift(1) if side > 0 else b.close.rolling(6).max().shift(1)
    rows = []
    for i in range(look, len(b) - 1):
        k = key[i]
        a = atr.get(k, np.nan)
        if np.isnan(a):
            continue
        if trend and not (up.get(k, False) if side > 0 else dn.get(k, False)):
            continue
        c = b.close.iloc[i]
        if side > 0 and not (c <= lowc.iloc[i] and ext.iloc[i] - c >= drop_atr * a):
            continue
        if side < 0 and not (c >= lowc.iloc[i] and c - ext.iloc[i] >= drop_atr * a):
            continue
        t0 = b.index[i] + step
        rows.append(dict(side=side, etype=MARKET, t_active=t0, t_expire=t0 + pd.Timedelta(hours=1), entry_px=np.nan,
                         sl_px=c - side * sl_atr * a, tp_px=c + side * tp_atr * a, t_exit=t0 + pd.Timedelta(days=max_days)))
    return _mk(rows)


def random_long(sym, every_h=24, tp_atr=1.0, sl_atr=1.5, max_days=5, seed=0):
    """Drift benchmark: long at random 4h bar opens (about one per every_h hours) with dip_buy's exits."""
    b = D.load_bars(sym, "4h")
    atr = atr_prev(sym)
    key = D.trading_day_ny(b.index)
    rng = np.random.default_rng(seed)
    rows = []
    for i in np.where(rng.random(len(b)) < 4 / every_h)[0]:
        a = atr.get(key[i], np.nan)
        if np.isnan(a) or i + 1 >= len(b):
            continue
        c = b.close.iloc[i]
        t0 = b.index[i] + pd.Timedelta("4h")
        rows.append(dict(side=1, etype=MARKET, t_active=t0, t_expire=t0 + pd.Timedelta(hours=1), entry_px=np.nan,
                         sl_px=c - sl_atr * a, tp_px=c + tp_atr * a, t_exit=t0 + pd.Timedelta(days=max_days)))
    return _mk(rows)


ROUND3 = {
    "R3a_donchian_4h": dict(fn=donchian_4h, universe=D.ALL, default=dict(n=20, trail_atr=2.0, sl_atr=1.5, max_days=10),
                            grid=dict(n=[10, 20, 40], trail_atr=[1.5, 2.0, 3.0])),
    "R3b_dip_buy_idx": dict(fn=dip_buy, universe=D.INDICES, default=dict(drop_atr=1.0, tp_atr=1.0, sl_atr=1.5, max_days=5),
                            grid=dict(drop_atr=[0.75, 1.0, 1.5], tp_atr=[0.75, 1.0, 1.5], sl_atr=[1.0, 1.5])),
    "R3c_random_long_idx": dict(fn=random_long, universe=D.INDICES, default=dict(every_h=24, tp_atr=1.0, sl_atr=1.5, max_days=5),
                                grid=dict(seed=[1, 2, 3, 4])),
}
