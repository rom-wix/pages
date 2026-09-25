"""Intraday research helpers (E06): session matrices, execution prices, trade -> daily P&L, stats.

Session matrix
  One row per CME-style trading session, one column per minute.  The session dated D runs from
  18:00 New York on the previous calendar day to 17:59 NY on D, so column j is "minutes since 18:00
  of the previous day" (09:00 NY = col 900, 14:30 = col 1230, 17:00 = col 1380).  NY local time is
  used throughout (DST handled by tz conversion).  Missing minutes (no ticks) are NaN.

Price conventions (no look-ahead)
  * px_before(S, c)   : last close strictly before column c  -> the price KNOWN at time c.
                        Used for signals / predictors.
  * px_exec(S, c)     : open of the first bar at or after column c (within `max_wait` minutes)
                        -> the fill of a market order sent at time c.  Used for entries/exits.
  * resting stop orders are simulated bar by bar on the minute OHLC path (see orb_kernel).

Trades
  A trade table has one row per round trip: date, dir (+1/-1), entry_px, exit_px, n_stop (number of
  stop-type sides, which pay STOP_SLIPPAGE), nights (financing nights, 0 for intraday), gross.
  net(m) = gross - m * (2*COST_PER_SIDE + n_stop*STOP_SLIPPAGE + nights*FIN_MARKUP/365)
  Daily P&L = sum of the day's trade returns, zeros on no-trade days, over all valid sessions.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd
from numba import njit
from scipy import stats

from . import backtest as bt
from . import costs
from .data import CACHE, oanda_minutes, to_ny

IS_END = pd.Timestamp("2012-12-31")
OOS_START = pd.Timestamp("2013-01-01")
PERIODS = {"is": (None, IS_END), "oos": (OOS_START, None), "full": (None, None)}
NCOL = 1440
S0 = 18 * 60  # session start: 18:00 NY on the previous calendar day
TD = 252


# ----------------------------------------------------------------------------------------------
# Time <-> column
# ----------------------------------------------------------------------------------------------
def col(t) -> int:
    """'HH:MM' New York time (or minutes-of-day int) -> session-matrix column."""
    if isinstance(t, str):
        h, m = t.split(":")
        t = int(h) * 60 + int(m)
    return int((t - S0) % NCOL)


def hhmm(c: int) -> str:
    t = (int(c) + S0) % NCOL
    return f"{t // 60:02d}:{t % 60:02d}"


# ----------------------------------------------------------------------------------------------
# Session matrix
# ----------------------------------------------------------------------------------------------
@dataclass
class Sess:
    sym: str
    dates: pd.DatetimeIndex  # session dates (tz-naive, weekdays)
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    V: np.ndarray
    prv: np.ndarray  # int16: column of the last bar at/before j (-1 if none)
    nxt: np.ndarray  # int16: column of the first bar at/after j (NCOL if none)
    valid: np.ndarray  # bool: full trading session (see calendar()) with >= 30 bars 09:00-14:30

    @property
    def n(self) -> int:
        return len(self.dates)

    def row_of(self, dates) -> np.ndarray:
        return self.dates.get_indexer(pd.DatetimeIndex(dates))


def _ffill_idx(mask: np.ndarray) -> np.ndarray:
    k = mask.shape[1]
    idx = np.where(mask, np.arange(k, dtype=np.int16)[None, :], np.int16(-1)).astype(np.int16)
    np.maximum.accumulate(idx, axis=1, out=idx)
    return idx


def _bfill_idx(mask: np.ndarray) -> np.ndarray:
    k = mask.shape[1]
    idx = np.where(mask, np.arange(k, dtype=np.int16)[None, :], np.int16(k)).astype(np.int16)
    idx = np.minimum.accumulate(idx[:, ::-1], axis=1)[:, ::-1]
    return np.ascontiguousarray(idx)


def _load_raw(sym: str):
    cache = os.path.join(CACHE, f"e06_sess_{sym}.npz")
    if os.path.exists(cache):
        z = np.load(cache)
        dates = pd.DatetimeIndex(z["dates"].astype("datetime64[ns]"))
        return dates, z["O"], z["H"], z["L"], z["C"], z["V"]
    m = oanda_minutes(sym)
    ny = to_ny(m.index)
    mod = (ny.hour * 60 + ny.minute).to_numpy()
    day = ny.normalize().tz_localize(None)
    sdate = day + pd.to_timedelta((mod >= S0).astype(int), unit="D")
    c = (mod - S0) % NCOL
    keep = sdate.dayofweek < 5
    sdate, c = sdate[keep], c[keep]
    mm = m[keep]
    dates = pd.DatetimeIndex(np.unique(sdate.to_numpy()).astype("datetime64[ns]"))
    r = dates.get_indexer(sdate)
    shape = (len(dates), NCOL)
    O, H, L, C, V = (np.full(shape, np.nan) for _ in range(5))
    for arr, name in [(O, "open"), (H, "high"), (L, "low"), (C, "close"), (V, "volume")]:
        arr[r, c] = mm[name].to_numpy()
    np.savez(cache, dates=dates.to_numpy().astype("datetime64[ns]").astype("int64"), O=O, H=H, L=L, C=C, V=V)
    return dates, O, H, L, C, V


@lru_cache(maxsize=None)
def calendar() -> pd.DatetimeIndex:
    """Full NYMEX trading sessions, derived from the liquid WTI feed: >= 60 one-minute bars between
    09:00 and 14:30 NY and at least one bar in [14:15, 14:30).  This drops exchange holidays and
    early-close days (MLK, Presidents, Memorial, July 4, Labor Day, Thanksgiving + Friday, Christmas /
    New Year eves), which a bot knows in advance from the exchange calendar."""
    dates, O, H, L, C, V = _load_raw("XTIUSD")
    mask = ~np.isnan(C)
    ok = (mask[:, col("09:00"):col("14:30")].sum(axis=1) >= 60) & mask[:, col("14:15"):col("14:30")].any(axis=1)
    return dates[ok]


@lru_cache(maxsize=None)
def session_matrix(sym: str) -> Sess:
    dates, O, H, L, C, V = _load_raw(sym)
    mask = ~np.isnan(C)
    prv = _ffill_idx(mask)
    nxt = _bfill_idx(mask)
    nbars_main = mask[:, col("09:00"):col("14:30")].sum(axis=1)
    valid = (nbars_main >= 30) & dates.isin(calendar())
    return Sess(sym, dates, O, H, L, C, V, prv, nxt, valid)


def valid_dates(S: Sess) -> pd.DatetimeIndex:
    return S.dates[S.valid]


# ----------------------------------------------------------------------------------------------
# Prices at times
# ----------------------------------------------------------------------------------------------
def px_before(S: Sess, c: int, max_age: int | None = None) -> np.ndarray:
    """Close of the last bar strictly before column c (the price known at time c). NaN if none
    (or older than max_age minutes)."""
    if c <= 0:
        return np.full(S.n, np.nan)
    j = S.prv[:, c - 1].astype(np.int64)
    out = np.where(j >= 0, S.C[np.arange(S.n), np.clip(j, 0, NCOL - 1)], np.nan)
    if max_age is not None:
        out = np.where((c - j) <= max_age, out, np.nan)
    return out


def px_exec(S: Sess, c: int, max_wait: int = 30, fallback_before: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Fill of a market order sent at column c: open of the first bar at/after c within max_wait
    minutes.  Returns (price, fill column).  With fallback_before=True, if no bar arrives in time the
    order is filled at the last close before c (used only to force-close positions at session end)."""
    j = S.nxt[:, c].astype(np.int64) if c < NCOL else np.full(S.n, NCOL)
    ok = (j < NCOL) & ((j - c) <= max_wait)
    px = np.where(ok, S.O[np.arange(S.n), np.clip(j, 0, NCOL - 1)], np.nan)
    jc = np.where(ok, j, -1)
    if fallback_before:
        pb = px_before(S, c)
        px = np.where(ok, px, pb)
        jc = np.where(ok, jc, c - 1)
    return px, jc


def daily_close(S: Sess) -> pd.Series:
    """Session close = last price before 17:00 NY (the CME daily settlement/rollover time)."""
    return pd.Series(px_before(S, col("17:00")), index=S.dates)


def prev_valid(x: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Value on the previous valid session (NaN-safe forward fill over invalid rows), shifted by 1."""
    s = pd.Series(np.where(valid, x, np.nan))
    return s.ffill().shift(1).to_numpy()


def trailing_mean(x: np.ndarray, valid: np.ndarray, n: int, min_periods: int | None = None,
                  fn: str = "mean") -> np.ndarray:
    """Trailing statistic of x over the previous n valid sessions (excluding today)."""
    s = pd.Series(np.where(valid, x, np.nan))
    r = s.rolling(n, min_periods=min_periods or max(n // 2, 1))
    v = getattr(r, fn)()
    # rolling over rows counts invalid rows too; good enough since invalid rows are rare holidays.
    return v.shift(1).to_numpy()


# ----------------------------------------------------------------------------------------------
# Trades -> daily P&L -> stats
# ----------------------------------------------------------------------------------------------
TRADE_COLS = ["date", "dir", "entry_px", "exit_px", "entry_col", "exit_col", "n_stop", "nights"]


def make_trades(S: Sess, rows, direction, entry_px, exit_px, entry_col=None, exit_col=None, n_stop=0,
                nights=0, **extra) -> pd.DataFrame:
    rows = np.asarray(rows)
    n = len(rows)
    bc = lambda v: np.broadcast_to(np.asarray(v), (n,)) if np.ndim(v) == 0 else np.asarray(v)
    df = pd.DataFrame({
        "date": S.dates[rows] if n else pd.DatetimeIndex([]),
        "dir": bc(direction).astype(float),
        "entry_px": bc(entry_px).astype(float),
        "exit_px": bc(exit_px).astype(float),
        "entry_col": bc(-1 if entry_col is None else entry_col).astype(int),
        "exit_col": bc(-1 if exit_col is None else exit_col).astype(int),
        "n_stop": bc(n_stop).astype(float),
        "nights": bc(nights).astype(float),
    })
    for k, v in extra.items():
        df[k] = bc(v)
    ok = np.isfinite(df["entry_px"]) & np.isfinite(df["exit_px"]) & (df["dir"] != 0) & (df["entry_px"] > 0)
    df = df[ok.to_numpy()].copy()
    df["gross"] = df["dir"] * (df["exit_px"] / df["entry_px"] - 1.0)
    df["sym"] = S.sym
    return df.reset_index(drop=True)


def cost_per_trade(sym: str, n_stop, nights, mult: float = 1.0):
    return mult * (2 * costs.COST_PER_SIDE[sym] + np.asarray(n_stop) * costs.STOP_SLIPPAGE[sym]
                   + np.asarray(nights) * costs.FIN_MARKUP / 365.0)


def net_returns(tr: pd.DataFrame, mult: float = 1.0) -> pd.Series:
    """Per-trade net return for 1x notional (ignores any sizing column)."""
    if len(tr) == 0:
        return pd.Series(dtype=float)
    sym = tr["sym"].iloc[0]
    return tr["gross"] - cost_per_trade(sym, tr["n_stop"], tr["nights"], mult)


def daily_pnl(tr: pd.DataFrame, dates: pd.DatetimeIndex, mult: float = 1.0) -> pd.Series:
    if len(tr) == 0:
        return pd.Series(0.0, index=dates)
    size = tr["size"] if "size" in tr else 1.0
    r = tr["gross"] * size - cost_per_trade(tr["sym"].iloc[0], tr["n_stop"], tr["nights"], mult) * np.abs(size)
    d = r.groupby(tr["date"]).sum()
    return d.reindex(dates, fill_value=0.0)


def _clip(x: pd.Series | pd.DataFrame, start, end):
    idx = x.index if isinstance(x, pd.Series) else pd.DatetimeIndex(x["date"])
    m = np.ones(len(x), bool)
    if start is not None:
        m &= idx >= start
    if end is not None:
        m &= idx <= end
    return x[m]


def period_stats(tr: pd.DataFrame, dates: pd.DatetimeIndex, start=None, end=None, mult: float = 1.0) -> dict:
    dn = _clip(daily_pnl(tr, dates, mult), start, end)
    dg = _clip(daily_pnl(tr, dates, 0.0), start, end)
    t = _clip(tr, start, end) if len(tr) else tr
    years = len(dn) / TD
    out = {"days": len(dn)}
    if len(dn) < 60:
        return out
    net_t = net_returns(t, mult) if len(t) else pd.Series(dtype=float)
    sd = dn.std()
    out.update({
        "sharpe": bt.sharpe(dn), "gross_sharpe": bt.sharpe(dg),
        "ann_ret": dn.mean() * TD, "ann_vol": sd * math.sqrt(TD),
        "max_dd": bt.max_drawdown(dn),
        "t_stat": (dn.mean() / sd * math.sqrt(len(dn))) if sd > 0 else np.nan,
        "trades": len(t), "trades_py": len(t) / years if years > 0 else np.nan,
        "avg_bps": net_t.mean() * 1e4 if len(t) else np.nan,
        "avg_gross_bps": t["gross"].mean() * 1e4 if len(t) else np.nan,
        "hit": float((net_t > 0).mean()) if len(t) else np.nan,
    })
    return out


def evaluate(tr: pd.DataFrame, S: Sess, extra_mults=(0.0, 2.0)) -> dict:
    """Flat dict of IS / OOS / full stats at 1x costs, plus full-period Sharpe at other cost multiples."""
    dates = valid_dates(S)
    out = {}
    for p, (a, b) in PERIODS.items():
        for k, v in period_stats(tr, dates, a, b).items():
            out[f"{p}_{k}"] = v
    for m in extra_mults:
        for p, (a, b) in PERIODS.items():
            dn = _clip(daily_pnl(tr, dates, m), a, b)
            out[f"{p}_sharpe_{m:g}x"] = bt.sharpe(dn) if len(dn) > 60 else np.nan
    return out


def yearly_stats(tr: pd.DataFrame, S: Sess, mult: float = 1.0) -> pd.DataFrame:
    dates = valid_dates(S)
    dn = daily_pnl(tr, dates, mult)
    dg = daily_pnl(tr, dates, 0.0)
    rows = []
    for y in sorted(set(dn.index.year)):
        x, g = dn[dn.index.year == y], dg[dg.index.year == y]
        t = tr[pd.DatetimeIndex(tr["date"]).year == y] if len(tr) else tr
        nt = net_returns(t, mult) if len(t) else pd.Series(dtype=float)
        rows.append({"year": y, "net_ret": x.sum(), "gross_ret": g.sum(), "sharpe": bt.sharpe(x),
                     "trades": len(t), "avg_bps": nt.mean() * 1e4 if len(t) else np.nan,
                     "hit": float((nt > 0).mean()) if len(t) else np.nan})
    return pd.DataFrame(rows)


def dsr_for(daily: pd.Series, trial_sharpes) -> float:
    x = daily.dropna()
    return bt.deflated_sharpe(bt.sharpe(x), list(trial_sharpes), len(x), float(stats.skew(x)),
                              float(stats.kurtosis(x, fisher=False)))


def dsr_null(daily: pd.Series, n_trials: int) -> float:
    """Deflated Sharpe with the hurdle set by N *unskilled* trials: the variance of the trial Sharpes is the
    sampling variance of a zero-Sharpe estimator, 1/(T-1) per day, instead of the observed cross-trial
    dispersion (which, with many cost-heavy variants, mostly reflects known cost differences, not noise).
    Same formula as backtest.deflated_sharpe otherwise."""
    x = daily.dropna()
    T = len(x)
    if T < 3 or x.std() == 0:
        return float("nan")
    sr = x.mean() / x.std()
    N = max(int(n_trials), 1)
    g = 0.5772156649
    emax = ((1 - g) * stats.norm.ppf(1 - 1.0 / N) + g * stats.norm.ppf(1 - 1.0 / (N * math.e))) if N > 1 else 0.0
    sr0 = emax / math.sqrt(T - 1)
    sk, ku = float(stats.skew(x)), float(stats.kurtosis(x, fisher=False))
    den = math.sqrt(max(1 - sk * sr + (ku - 1) / 4.0 * sr ** 2, 1e-12))
    return float(stats.norm.cdf((sr - sr0) * math.sqrt(T - 1) / den))


def nw_ols(y, X, lags: int = 5):
    """OLS with Newey-West (HAC) standard errors. X without constant; returns statsmodels result."""
    import statsmodels.api as sm
    X = sm.add_constant(np.asarray(X, float))
    return sm.OLS(np.asarray(y, float), X).fit(cov_type="HAC", cov_kwds={"maxlags": lags})


# ----------------------------------------------------------------------------------------------
# Resting stop-order simulator on minute OHLC paths (used by ORB / breakout rules)
# ----------------------------------------------------------------------------------------------
@njit(cache=True)
def orb_kernel(O, H, L, C, hi, lo, start_col, last_entry_col, exit_col, stop_mode, allow_rev, dir_allowed):
    """Simulate a two-sided stop-entry breakout per session row.

    Orders become active at column start_col[d] (range end).  Buy stop at hi[d], sell stop at lo[d].
    At most one trade, plus one reversal if allow_rev (opposite-direction stop entry at the opposite
    range edge once the first trade has been stopped out).  No new entries after last_entry_col.
    Protective stop: stop_mode 0 = none, 1 = opposite range edge, 2 = range midpoint.
    Positions still open are closed at the open of the first bar at/after exit_col (market order),
    or at the last seen price if the session has no later bar.
    Intrabar path: O -> L -> H -> C if C >= O else O -> H -> L -> C.  A gap between bars fills at the
    new bar's open (never at the level).  dir_allowed[d]: 0 both, +1 long only, -1 short only.

    Returns arrays (row, dir, entry_px, exit_px, entry_col, exit_col, n_stop) of length n_trades.
    """
    n = O.shape[0]
    cap = 2 * n
    r_row = np.empty(cap, np.int64)
    r_dir = np.empty(cap, np.float64)
    r_ep = np.empty(cap, np.float64)
    r_xp = np.empty(cap, np.float64)
    r_ec = np.empty(cap, np.int64)
    r_xc = np.empty(cap, np.int64)
    r_ns = np.empty(cap, np.float64)
    m = 0
    for d in range(n):
        h0 = hi[d]
        l0 = lo[d]
        if not (h0 == h0) or not (l0 == l0) or h0 <= l0:
            continue
        mid = 0.5 * (h0 + l0)
        allowL = dir_allowed[d] >= 0
        allowS = dir_allowed[d] <= 0
        pendL = allowL
        pendS = allowS
        pos = 0
        ntr = 0
        ep = 0.0
        ec = -1
        stop = np.nan
        lastp = np.nan
        for j in range(start_col[d], exit_col):
            o = O[d, j]
            if not (o == o):
                continue
            hh = H[d, j]
            ll = L[d, j]
            cc = C[d, j]
            if cc >= o:
                p1 = ll
                p2 = hh
            else:
                p1 = hh
                p2 = ll
            for k in range(4):
                if k == 0:
                    a = o if not (lastp == lastp) else lastp
                    b = o
                    gap = True
                elif k == 1:
                    a = o
                    b = p1
                    gap = False
                elif k == 2:
                    a = p1
                    b = p2
                    gap = False
                else:
                    a = p2
                    b = cc
                    gap = False
                cur = a
                for it in range(4):
                    if pos == 0:
                        entry_ok = (j <= last_entry_col) and (ntr == 0 or (allow_rev and ntr == 1))
                        if not entry_ok:
                            break
                        fill = np.nan
                        newdir = 0
                        if pendL and cur >= h0:
                            fill = cur
                            newdir = 1
                        elif pendS and cur <= l0:
                            fill = cur
                            newdir = -1
                        elif pendL and b >= h0:
                            fill = b if gap else h0
                            newdir = 1
                        elif pendS and b <= l0:
                            fill = b if gap else l0
                            newdir = -1
                        if newdir == 0:
                            break
                        pos = newdir
                        ep = fill
                        ec = j
                        cur = fill
                        ntr += 1
                        if stop_mode == 1:
                            stop = l0 if pos == 1 else h0
                        elif stop_mode == 2:
                            stop = mid
                        else:
                            stop = np.nan
                        # only a reversal may follow
                        pendL = allow_rev and (pos == -1) and allowL
                        pendS = allow_rev and (pos == 1) and allowS
                    else:
                        if not (stop == stop):
                            break
                        fill = np.nan
                        if pos == 1:
                            if cur <= stop:
                                fill = cur
                            elif b <= stop:
                                fill = b if gap else stop
                        else:
                            if cur >= stop:
                                fill = cur
                            elif b >= stop:
                                fill = b if gap else stop
                        if not (fill == fill):
                            break
                        r_row[m] = d
                        r_dir[m] = pos
                        r_ep[m] = ep
                        r_xp[m] = fill
                        r_ec[m] = ec
                        r_xc[m] = j
                        r_ns[m] = 2.0
                        m += 1
                        pos = 0
                        cur = fill
                lastp = b
        if pos != 0:
            xp = lastp
            xc = exit_col - 1
            for j in range(exit_col, O.shape[1]):
                if O[d, j] == O[d, j]:
                    xp = O[d, j]
                    xc = j
                    break
            if xp == xp:
                r_row[m] = d
                r_dir[m] = pos
                r_ep[m] = ep
                r_xp[m] = xp
                r_ec[m] = ec
                r_xc[m] = xc
                r_ns[m] = 1.0
                m += 1
    return r_row[:m], r_dir[:m], r_ep[:m], r_xp[:m], r_ec[:m], r_xc[:m], r_ns[:m]


# ----------------------------------------------------------------------------------------------
# Bars within the session matrix (5 / 15 minute) for bar-based rules
# ----------------------------------------------------------------------------------------------
def session_bars(S: Sess, k: int):
    """Aggregate the minute matrix into k-minute bars aligned to 18:00 (so to the clock).
    Returns O,H,L,C,V arrays of shape (n, NCOL//k); empty bars are NaN (V=0)."""
    n = S.n
    nb = NCOL // k
    shp = (n, nb, k)
    Hs = S.H.reshape(shp)
    Ls = S.L.reshape(shp)
    Vs = np.nan_to_num(S.V).reshape(shp)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            H = np.nanmax(Hs, axis=2)
            L = np.nanmin(Ls, axis=2)
    Cs = S.C.reshape(shp)
    Os = S.O.reshape(shp)
    mask = ~np.isnan(Cs)
    any_ = mask.any(axis=2)
    first = np.argmax(mask, axis=2)
    last = k - 1 - np.argmax(mask[:, :, ::-1], axis=2)
    ii, jj = np.meshgrid(np.arange(n), np.arange(nb), indexing="ij")
    O = np.where(any_, Os[ii, jj, first], np.nan)
    C = np.where(any_, Cs[ii, jj, last], np.nan)
    V = Vs.sum(axis=2)
    return O, H, L, C, V


# ----------------------------------------------------------------------------------------------
# EIA schedule
# ----------------------------------------------------------------------------------------------
def federal_holidays(start="2004-12-01", end="2020-12-31") -> pd.DatetimeIndex:
    from pandas.tseries.holiday import USFederalHolidayCalendar
    return USFederalHolidayCalendar().holidays(start, end)


def eia_schedule(S: Sess, kind: str) -> pd.DataFrame:
    """Scheduled release per week (known in advance from the EIA calendar; approximated here by the
    federal-holiday rule).  kind='crude' (Weekly Petroleum Status Report) or 'gas' (storage report).

    crude: Wednesday 10:30 ET; if a federal holiday falls Mon-Wed of that week -> Thursday (10:30 ET
           until Sep 2008, 11:00 ET from Oct 2008 - both verified against the 1-minute spikes).
    gas  : Thursday 10:30 ET; weeks with a federal holiday Tue-Fri are dropped (release moved to an
           irregular day/time).
    Data quirk: Jun-Dec 2008 the release registers at 10:35 in this feed (both reports, both CFDs,
    while the 09:00 open and 14:28 settlement spikes are on time) -> event minute 10:35 then.
    Returns DataFrame(date, row, col, shifted)."""
    hol = set(federal_holidays().normalize())
    d = S.dates[S.valid]
    wk = d - pd.to_timedelta(d.dayofweek, unit="D")  # Monday of each week
    out = []
    for monday in sorted(set(wk)):
        days = [monday + pd.Timedelta(days=i) for i in range(5)]
        hol_dow = [i for i, x in enumerate(days) if x in hol]
        if kind == "crude":
            if any(i <= 2 for i in hol_dow):
                # holiday weeks: Thursday 10:30 until Sep 2008, Thursday 11:00 from Oct 2008 (per the data)
                ev, sh = days[3], True
                t = "10:30" if days[3] < pd.Timestamp("2008-10-01") else "11:00"
            else:
                ev, t, sh = days[2], "10:30", False
        else:
            if any(1 <= i <= 4 for i in hol_dow):
                continue
            ev, t, sh = days[3], "10:30", False
        if ev not in S.dates or ev in hol:
            continue
        if pd.Timestamp("2008-06-01") <= ev <= pd.Timestamp("2008-12-31") and t == "10:30":
            t = "10:35"
        out.append({"date": ev, "col": col(t), "time": t, "shifted": sh})
    df = pd.DataFrame(out)
    df["row"] = S.row_of(df["date"])
    df = df[df["row"] >= 0]
    df = df[S.valid[df["row"].to_numpy()]]
    return df.reset_index(drop=True)
