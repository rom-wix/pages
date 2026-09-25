"""Signal library. Every function uses data up to and including t only (causal)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def logp(tri: pd.Series) -> pd.Series:
    return np.log(tri)


def daily_vol(r: pd.Series, span: int = 36) -> pd.Series:
    return r.ewm(span=span, min_periods=20).std()


def _normalise(raw: pd.Series, target_abs: float = 1.0, cap: float = 2.0, min_periods: int = 250) -> pd.Series:
    """Scale a raw forecast so its *expanding* mean absolute value is `target_abs`; clip at +/-cap.
    Expanding window => no look-ahead in the scaling."""
    scale = raw.abs().expanding(min_periods=min_periods).mean()
    return (raw / scale * target_abs).clip(-cap, cap)


def ewmac(tri: pd.Series, r: pd.Series, fast: int, slow: int | None = None, cap: float = 2.0) -> pd.Series:
    """Carver EWMAC trend forecast on log total-return index, normalised by daily vol."""
    slow = slow or 4 * fast
    x = logp(tri)
    raw = (x.ewm(span=fast, min_periods=fast).mean() - x.ewm(span=slow, min_periods=slow).mean()) / daily_vol(r)
    return _normalise(raw, 1.0, cap)


def breakout(tri: pd.Series, n: int, cap: float = 2.0) -> pd.Series:
    """Carver breakout: position of price in its n-day range, smoothed. ~[-1, 1]."""
    x = logp(tri)
    hi, lo = x.rolling(n, min_periods=n).max(), x.rolling(n, min_periods=n).min()
    mid = (hi + lo) / 2
    raw = ((x - mid) / (hi - lo)).ewm(span=max(n // 4, 2)).mean() * 2
    return _normalise(raw, 1.0, cap)


def tsmom(tri: pd.Series, lookback: int) -> pd.Series:
    """Sign of trailing `lookback`-day total return (Moskowitz-Ooi-Pedersen)."""
    x = logp(tri)
    return np.sign(x - x.shift(lookback))


def ma_cross(tri: pd.Series, fast: int, slow: int) -> pd.Series:
    x = logp(tri)
    return np.sign(x.rolling(fast).mean() - x.rolling(slow).mean())


def donchian(tri: pd.Series, entry: int = 55, exit: int = 20) -> pd.Series:
    """Turtle-style stateful breakout: +1 on new `entry`-day high, -1 on new low; exit on `exit`-day
    opposite extreme. Uses highs/lows up to t-1 so a breakout is decided on the close of t."""
    x = logp(tri).to_numpy()
    n = len(x)
    pos = np.zeros(n)
    hi_e = pd.Series(x).rolling(entry).max().shift(1).to_numpy()
    lo_e = pd.Series(x).rolling(entry).min().shift(1).to_numpy()
    hi_x = pd.Series(x).rolling(exit).max().shift(1).to_numpy()
    lo_x = pd.Series(x).rolling(exit).min().shift(1).to_numpy()
    cur = 0.0
    for i in range(n):
        if np.isnan(hi_e[i]):
            pos[i] = 0.0
            continue
        if cur > 0 and x[i] < lo_x[i]:
            cur = 0.0
        elif cur < 0 and x[i] > hi_x[i]:
            cur = 0.0
        if x[i] > hi_e[i]:
            cur = 1.0
        elif x[i] < lo_e[i]:
            cur = -1.0
        pos[i] = cur
    return pd.Series(pos, index=tri.index)


def zscore(x: pd.Series, n: int) -> pd.Series:
    m, s = x.rolling(n, min_periods=n).mean(), x.rolling(n, min_periods=n).std()
    return (x - m) / s


def rsi(r: pd.Series, n: int = 2) -> pd.Series:
    up = r.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-r.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def multi_ewmac(tri: pd.Series, r: pd.Series, speeds=(8, 16, 32, 64), cap: float = 2.0) -> pd.Series:
    """Equal-weight blend of EWMAC(f, 4f) forecasts (with a diversification multiplier re-normalisation)."""
    fc = pd.concat([ewmac(tri, r, f) for f in speeds], axis=1).mean(axis=1)
    return _normalise(fc, 1.0, cap)


def multi_breakout(tri: pd.Series, windows=(20, 40, 80, 160, 320), cap: float = 2.0) -> pd.Series:
    fc = pd.concat([breakout(tri, n) for n in windows], axis=1).mean(axis=1)
    return _normalise(fc, 1.0, cap)
