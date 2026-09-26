"""Order simulator on 1-minute bars.

A strategy emits *orders* (one row per setup). Each order is simulated independently on the 1-minute path:

  entry   market (open of first minute >= t_active) | stop at entry_px | limit at entry_px
          pending orders expire at t_expire; optional cancel level (e.g. target reached before a pullback fill)
  exits   stop-loss, take-profit, time exit (open of first minute >= t_exit), optional break-even and trailing stop
  fills   gaps through a level fill at the minute's open; stop fills (entries and stop-losses) pay slippage
          = base + frac * (range of the fill minute); if SL and TP are both inside one minute the SL wins;
          in the entry minute of a stop/limit order only the SL is checked (conservative)

Prices are treated as mid quotes: the round-trip spread + commission is charged once per trade (costs.py).
Results are per-order records; `one_at_a_time` removes overlapping trades of the same strategy/symbol.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numba import njit

MARKET, STOP, LIMIT = 0, 1, 2
R_NONE, R_SL, R_TP, R_TIME, R_END, R_EXPIRED, R_CANCEL = 0, 1, 2, 3, 4, 5, 6
REASONS = {R_NONE: "none", R_SL: "sl", R_TP: "tp", R_TIME: "time", R_END: "end", R_EXPIRED: "expired", R_CANCEL: "cancel"}


@njit(cache=True)
def _simulate(t, o, h, l, c,
              side, etype, t_active, t_expire, entry_px, sl_px, tp_px, t_exit, cancel_px,
              be_at_r, be_lock_r, trail_dist, trail_at_r,
              slip_base, slip_frac, can_fill):
    n = side.shape[0]
    m = t.shape[0]
    out_fill_i = np.full(n, -1, np.int64)
    out_exit_i = np.full(n, -1, np.int64)
    out_entry = np.full(n, np.nan)
    out_exit = np.full(n, np.nan)
    out_reason = np.zeros(n, np.int64)
    out_mfe = np.zeros(n)
    out_mae = np.zeros(n)
    for k in range(n):
        s = side[k]
        i = np.searchsorted(t, t_active[k])
        if i >= m:
            out_reason[k] = R_END
            continue
        # ---------------- entry ----------------
        filled = False
        e = np.nan
        while i < m and t[i] < t_expire[k]:
            if not can_fill[i]:
                i += 1
                continue
            if not np.isnan(cancel_px[k]):
                # cancel if the market reaches the cancel level before we are filled
                if (s > 0 and h[i] >= cancel_px[k]) or (s < 0 and l[i] <= cancel_px[k]):
                    # allow a fill in the same minute only if the open is already through the entry
                    if etype[k] == LIMIT and ((s > 0 and o[i] <= entry_px[k]) or (s < 0 and o[i] >= entry_px[k])):
                        pass
                    else:
                        out_reason[k] = R_CANCEL
                        break
            if etype[k] == MARKET:
                e = o[i]
                filled = True
                break
            elif etype[k] == STOP:
                x = entry_px[k]
                if s > 0 and h[i] >= x:
                    e = max(o[i], x) + slip_base + slip_frac * (h[i] - l[i])
                    filled = True
                    break
                if s < 0 and l[i] <= x:
                    e = min(o[i], x) - slip_base - slip_frac * (h[i] - l[i])
                    filled = True
                    break
            else:  # LIMIT
                x = entry_px[k]
                if s > 0 and l[i] < x:
                    e = min(o[i], x)
                    filled = True
                    break
                if s < 0 and h[i] > x:
                    e = max(o[i], x)
                    filled = True
                    break
            i += 1
        if not filled:
            if out_reason[k] == R_NONE:
                out_reason[k] = R_EXPIRED if i < m else R_END
            continue
        out_fill_i[k] = i
        out_entry[k] = e
        sl = sl_px[k]
        tp = tp_px[k]
        risk = abs(e - sl)
        if risk <= 0:
            risk = 1e-12
        best = e
        worst = e
        be_done = False
        first = True
        reason = R_NONE
        xp = np.nan
        j = i
        while j < m:
            if t[j] >= t_exit[k] and not first and can_fill[j]:
                xp = o[j]
                reason = R_TIME
                break
            # --- stop-loss (checked first; a gap through the level fills at the open) ---
            if s > 0 and l[j] <= sl:
                px = o[j] if (not first and o[j] < sl) else sl
                xp = px - slip_base - slip_frac * (h[j] - l[j])
                reason = R_SL
                break
            if s < 0 and h[j] >= sl:
                px = o[j] if (not first and o[j] > sl) else sl
                xp = px + slip_base + slip_frac * (h[j] - l[j])
                reason = R_SL
                break
            # --- take-profit ---
            if not np.isnan(tp) and (not first or etype[k] == MARKET) and can_fill[j]:
                if s > 0 and h[j] > tp:
                    xp = max(o[j], tp) if not first else tp
                    reason = R_TP
                    break
                if s < 0 and l[j] < tp:
                    xp = min(o[j], tp) if not first else tp
                    reason = R_TP
                    break
            # --- excursions, break-even, trailing (updated at the minute close -> apply from next minute) ---
            if s > 0:
                best = max(best, h[j])
                worst = min(worst, l[j])
            else:
                best = min(best, l[j])
                worst = max(worst, h[j])
            fav = (best - e) * s / risk
            if not be_done and not np.isnan(be_at_r[k]) and fav >= be_at_r[k]:
                lock = e + s * be_lock_r[k] * risk
                if (s > 0 and lock > sl) or (s < 0 and lock < sl):
                    sl = lock
                be_done = True
            if not np.isnan(trail_dist[k]) and fav >= trail_at_r[k]:
                cand = best - s * trail_dist[k]
                if (s > 0 and cand > sl) or (s < 0 and cand < sl):
                    sl = cand
            first = False
            j += 1
        if reason == R_NONE:
            j = m - 1
            xp = c[j]
            reason = R_END
        out_exit_i[k] = j
        out_exit[k] = xp
        out_reason[k] = reason
        out_mfe[k] = (best - e) * s / risk
        out_mae[k] = (worst - e) * s / risk
    return out_fill_i, out_exit_i, out_entry, out_exit, out_reason, out_mfe, out_mae


ORDER_COLS = ["side", "etype", "t_active", "t_expire", "entry_px", "sl_px", "tp_px", "t_exit"]


def rollover_mask(index: pd.DatetimeIndex, start="16:40", end="18:10") -> np.ndarray:
    """True where orders may fill. The vendor quotes are bids: around the 17:00 New York rollover spreads widen and
    the bid sags then snaps back (16:45 -> 17:30/18:00 NY), so entries, take-profits and time exits are not allowed
    to fill inside [start, end) NY. Stop-losses still trigger there (a real sell-stop would)."""
    ny = index.tz_convert("America/New_York")
    tod = ny.hour * 60 + ny.minute
    a = int(start[:2]) * 60 + int(start[3:])
    b = int(end[:2]) * 60 + int(end[3:])
    return ~((tod >= a) & (tod < b))


def simulate(minutes: pd.DataFrame, orders: pd.DataFrame, cost_rt: float, slip_base: float, slip_frac: float = 0.1,
             financing_per_night: float = 0.0, blackout: bool = True) -> pd.DataFrame:
    """minutes: UTC 1m OHLC. orders: DataFrame with ORDER_COLS (+ optional cancel_px, be_at_r, be_lock_r,
    trail_dist, trail_at_r, and any metadata columns which are passed through).
    cost_rt: round-trip spread+commission in price units. financing_per_night: price units per 17:00 NY roll held.
    """
    if len(orders) == 0:
        return pd.DataFrame()
    od = orders.reset_index(drop=True).copy()
    for col, default in [("cancel_px", np.nan), ("be_at_r", np.nan), ("be_lock_r", 0.0), ("trail_dist", np.nan), ("trail_at_r", 0.0)]:
        if col not in od:
            od[col] = default
    t = minutes.index.as_unit("ns").asi8

    def to_ns(col):
        di = pd.DatetimeIndex(col)
        di = di.tz_localize("UTC") if di.tz is None else di.tz_convert("UTC")
        return di.as_unit("ns").asi8
    res = _simulate(t, minutes["open"].values, minutes["high"].values, minutes["low"].values, minutes["close"].values,
                    od["side"].values.astype(np.int64), od["etype"].values.astype(np.int64),
                    to_ns(od["t_active"]), to_ns(od["t_expire"]), od["entry_px"].values.astype(float),
                    od["sl_px"].values.astype(float), od["tp_px"].values.astype(float), to_ns(od["t_exit"]),
                    od["cancel_px"].values.astype(float), od["be_at_r"].values.astype(float), od["be_lock_r"].values.astype(float),
                    od["trail_dist"].values.astype(float), od["trail_at_r"].values.astype(float),
                    float(slip_base), float(slip_frac),
                    rollover_mask(minutes.index) if blackout else np.ones(len(minutes), dtype=np.bool_))
    fi, xi, e, x, reason, mfe, mae = res
    od["filled"] = fi >= 0
    nat = np.iinfo(np.int64).min
    od["entry_time"] = pd.to_datetime(np.where(fi >= 0, t[np.maximum(fi, 0)], nat), utc=True)
    od["exit_time"] = pd.to_datetime(np.where(xi >= 0, t[np.maximum(xi, 0)], nat), utc=True)
    od["entry"] = e
    od["exit"] = x
    od["reason"] = [REASONS[r] for r in reason]
    od["mfe_r"] = mfe
    od["mae_r"] = mae
    tr = od[od.filled].copy()
    if len(tr) == 0:
        return tr
    # nights held: number of 17:00 New York rolls crossed
    ent = tr["entry_time"].dt.tz_convert("America/New_York")
    ext = tr["exit_time"].dt.tz_convert("America/New_York")
    d0 = (ent + pd.Timedelta(hours=7)).dt.floor("D")
    d1 = (ext + pd.Timedelta(hours=7)).dt.floor("D")
    tr["nights"] = ((d1 - d0).dt.days).clip(lower=0)
    tr["risk"] = (tr["entry"] - tr["sl_px"]).abs()
    tr["gross"] = tr["side"] * (tr["exit"] - tr["entry"])
    tr["cost"] = cost_rt + financing_per_night * tr["nights"]
    tr["pnl"] = tr["gross"] - tr["cost"]
    tr["r"] = tr["pnl"] / tr["risk"].where(tr["risk"] > 0)
    tr["ret_bp"] = tr["pnl"] / tr["entry"] * 1e4
    tr["hold_min"] = (tr["exit_time"] - tr["entry_time"]).dt.total_seconds() / 60
    return tr


def one_at_a_time(tr: pd.DataFrame, keys=("strategy", "symbol")) -> pd.DataFrame:
    """Greedy: within each key group keep a trade only if it starts after the previous kept trade exited."""
    if len(tr) == 0:
        return tr
    keep = []
    for _, g in tr.sort_values("entry_time").groupby(list(k for k in keys if k in tr.columns), sort=False):
        last_exit = None
        for i, row in zip(g.index, g[["entry_time", "exit_time"]].itertuples(index=False)):
            if last_exit is None or row.entry_time >= last_exit:
                keep.append(i)
                last_exit = row.exit_time
    return tr.loc[sorted(keep)]
