"""E06-E  Short-term intraday mean reversion during 09:00-14:30 NY.

Bars: 5- or 15-minute bars aligned to the clock (built from the session matrix).
Signals (computed at bar close t, executed at the next bar open):
  ret-z : z = r_t / sd(r_{t-n..t-1})  (bar log return vs the rolling std of the previous n bar returns)
  px-z  : z = (C_t - SMA_n) / SD_n     (Bollinger z of the close vs its rolling n-bar mean, incl. t)
  vwap  : dev = (C_t - VWAP_t) / (C_t * trailing-20-day mean 09:00-14:30 range), VWAP from 09:00 using
          tick-count volume as weights (Oanda 'volume' = number of quote updates)
  windows n = 1 hour or 4 hours of bars; rolling statistics run over the continuous bar series (they
  may include pre-09:00 bars and the previous session).
Rules: when flat and z > thr (z < -thr) at a bar close with bar start in [09:00, 14:00): short (long)
at the next bar open.  Exit: 'mean' = first bar close back at/through the rolling mean (SMA_n, or VWAP)
-> next bar open, with a 60-minute time stop; 'time' = after 30 minutes.  Forced exit 14:30.
One position at a time; re-entry allowed.  Costs: 2 x COST_PER_SIDE per round trip (market orders).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from numba import njit

from src import intraday as ix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results")
SYMS = ["XTIUSD", "XNGUSD"]


@njit(cache=True)
def mr_kernel(O, C, Z, M, thr, first_bar, last_bar, exit_bar, exit_mode, max_hold, valid):
    """Per session row: fade |Z| > thr.  O/C bar opens/closes, Z signal, M exit-target level (mean).
    exit_mode 0: exit when close crosses back to M (or after max_hold bars); 1: exit after max_hold bars.
    Decisions at closes of bars first_bar..last_bar; forced exit at the open of the first bar >= exit_bar.
    Returns (row, dir, entry_px, exit_px, entry_bar, exit_bar)."""
    n, nb = C.shape
    cap = n * 64
    rr = np.empty(cap, np.int64)
    rd = np.empty(cap, np.float64)
    re = np.empty(cap, np.float64)
    rx = np.empty(cap, np.float64)
    rbe = np.empty(cap, np.int64)
    rbx = np.empty(cap, np.int64)
    m = 0
    for d in range(n):
        if not valid[d]:
            continue
        pos = 0
        ep = 0.0
        eb = -1
        pending = 0  # +1/-1 entry to execute at next bar open, 2 = exit at next bar open
        for b in range(first_bar, nb):
            o = O[d, b]
            if not (o == o):
                continue
            # execute pending order at this bar's open
            if b >= exit_bar:
                if pos != 0:
                    rr[m] = d
                    rd[m] = pos
                    re[m] = ep
                    rx[m] = o
                    rbe[m] = eb
                    rbx[m] = b
                    m += 1
                    pos = 0
                pending = 0
                break
            if pending == 2 and pos != 0:
                rr[m] = d
                rd[m] = pos
                re[m] = ep
                rx[m] = o
                rbe[m] = eb
                rbx[m] = b
                m += 1
                pos = 0
                pending = 0
            elif pending == 1 or pending == -1:
                if pos == 0:
                    pos = pending
                    ep = o
                    eb = b
                pending = 0
            # decision at this bar's close
            c = C[d, b]
            if not (c == c):
                continue
            if pos == 0:
                if b <= last_bar:
                    z = Z[d, b]
                    if z == z:
                        if z > thr:
                            pending = -1
                        elif z < -thr:
                            pending = 1
            else:
                held = b - eb + 1
                mm = M[d, b]
                if exit_mode == 0:
                    if (pos == 1 and mm == mm and c >= mm) or (pos == -1 and mm == mm and c <= mm) or held >= max_hold:
                        pending = 2
                else:
                    if held >= max_hold:
                        pending = 2
        if pos != 0:  # no bar at/after exit_bar (early close) -> exit at the last close
            lastc = np.nan
            lb = -1
            for b in range(nb - 1, -1, -1):
                if C[d, b] == C[d, b]:
                    lastc = C[d, b]
                    lb = b
                    break
            rr[m] = d
            rd[m] = pos
            re[m] = ep
            rx[m] = lastc
            rbe[m] = eb
            rbx[m] = lb
            m += 1
    return rr[:m], rd[:m], re[:m], rx[:m], rbe[:m], rbx[:m]


def rolling_on_bars(C, n):
    """Rolling stats over the continuous (row-major) series of non-empty bars."""
    flat = C.ravel()
    ok = np.isfinite(flat)
    s = pd.Series(flat[ok])
    r = np.log(s).diff()
    sd_r_prev = r.rolling(n, min_periods=max(3, n // 2)).std().shift(1)
    sma = s.rolling(n, min_periods=max(3, n // 2)).mean()
    sdp = s.rolling(n, min_periods=max(3, n // 2)).std()
    out = {}
    for name, v in [("r", r), ("sd_r_prev", sd_r_prev), ("sma", sma), ("sdp", sdp)]:
        a = np.full(flat.shape, np.nan)
        a[ok] = v.to_numpy()
        out[name] = a.reshape(C.shape)
    return out


def vwap_levels(S, k, bO, bC):
    """VWAP from 09:00 on k-minute bars (typical price of each minute weighted by tick volume)."""
    a = ix.col("09:00")
    tp = (S.H + S.L + S.C) / 3.0
    v = np.nan_to_num(S.V)
    w = np.where(np.isfinite(tp), v, 0.0)
    tpv = np.where(np.isfinite(tp), tp * w, 0.0)
    w[:, :a] = 0.0
    tpv[:, :a] = 0.0
    cw = np.cumsum(w, axis=1)
    ctp = np.cumsum(tpv, axis=1)
    with np.errstate(all="ignore"):
        vw_min = ctp / cw  # VWAP up to and including minute j
    # value at the close of each k-bar = minute (b+1)*k - 1
    idx = np.arange(k - 1, ix.NCOL, k)
    return vw_min[:, idx]


def main():
    t0 = time.time()
    grid, store = [], {}
    for sym in SYMS:
        S = ix.session_matrix(sym)
        # trailing 20-day mean of the 09:00-14:30 range (fraction of price), known before today
        a, b = ix.col("09:00"), ix.col("14:30")
        with np.errstate(all="ignore"):
            rng = (np.nanmax(S.H[:, a:b], axis=1) - np.nanmin(S.L[:, a:b], axis=1)) / ix.px_before(S, a)
        rng20 = ix.trailing_mean(rng, S.valid & np.isfinite(rng), 20, 10)
        for k in [5, 15]:
            bO, bH, bL, bC, bV = ix.session_bars(S, k)
            fb, lb, xb = ix.col("09:00") // k, ix.col("14:00") // k - 1, ix.col("14:30") // k
            for win_h in [1, 4]:
                n = int(win_h * 60 // k)
                R = rolling_on_bars(bC, n)
                zs = {"retz": R["r"] / R["sd_r_prev"], "pxz": (bC - R["sma"]) / R["sdp"]}
                for zname, Z in zs.items():
                    for thr in [2.0, 3.0]:
                        for exit_mode, xname, hold_min in [(0, "mean", 60), (1, "time30", 30)]:
                            mh = max(1, hold_min // k)
                            res = mr_kernel(bO, bC, np.nan_to_num(Z, nan=np.nan), R["sma"], thr, fb, lb, xb,
                                            exit_mode, mh, S.valid)
                            rows, dr, ep, xp, eb, xb_ = res
                            tr = ix.make_trades(S, rows, dr, ep, xp, eb * k, xb_ * k, n_stop=0)
                            key = f"{sym}|mr|{k}m|{zname}|{win_h}h|z{thr:g}|{xname}"
                            store[key] = tr
                            grid.append({"key": key, "sym": sym, "family": "E_meanrev", "bar": k, "z": zname,
                                         "window_h": win_h, "thr": thr, "exit": xname, **ix.evaluate(tr, S)})
            if k == 5:
                VW = vwap_levels(S, k, bO, bC)
                dev = (bC - VW) / (bC * rng20[:, None])
                fb2 = ix.col("09:30") // k
                for thr in [0.25, 0.5]:
                    for exit_mode, xname, hold_min in [(0, "vwap", 60), (1, "time30", 30)]:
                        mh = max(1, hold_min // k)
                        res = mr_kernel(bO, bC, dev, VW, thr, fb2, lb, xb, exit_mode, mh, S.valid)
                        rows, dr, ep, xp, eb, xb_ = res
                        tr = ix.make_trades(S, rows, dr, ep, xp, eb * k, xb_ * k, n_stop=0)
                        key = f"{sym}|mr|5m|vwap|day|d{thr:g}|{xname}"
                        store[key] = tr
                        grid.append({"key": key, "sym": sym, "family": "E_meanrev", "bar": 5, "z": "vwap",
                                     "window_h": 0, "thr": thr, "exit": xname, **ix.evaluate(tr, S)})
        print(sym, "done", round(time.time() - t0, 1), "s", flush=True)
    G = pd.DataFrame(grid)
    G.to_csv(os.path.join(OUT, "e06_E_meanrev_grid.csv"), index=False)
    pd.to_pickle(store, os.path.join(ix.CACHE, "e06_E_trades.pkl"))
    pd.set_option("display.width", 250)
    show = ["key", "is_sharpe", "oos_sharpe", "full_sharpe", "is_gross_sharpe", "oos_gross_sharpe", "full_trades_py",
            "full_avg_bps", "is_avg_gross_bps", "oos_avg_gross_bps", "full_hit"]
    for sym in SYMS:
        g = G[G.sym == sym].sort_values("is_gross_sharpe", ascending=False)
        print(f"\n{sym}: {len(g)} variants (sorted by IS GROSS Sharpe)")
        print(g[show].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
