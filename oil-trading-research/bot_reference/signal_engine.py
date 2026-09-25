"""Reference signal engine for the recommended daily bot (multi-speed trend + crack tilt, vol-targeted).

Self-contained (pandas/numpy only) and identical in logic to the research backtests, so live targets can
be checked against research numbers (see verify_against_backtest.py):
  trend="revised"  (default)  1/3/12-month momentum (Hurst-Ooi-Pedersen 2017) averaged with fast-to-medium
                              EWMA crossovers (4-32d) and breakouts (20-160d)      -> experiments/e14_speed_blends.py
  trend="original"            EWMA crossovers 8-64d + breakouts 40-320d            -> experiments/e10_portfolio.py

Inputs (daily, one row per trading day, aligned on the settlement/close time you trade at):
  closes[sym]  : roll-ADJUSTED daily closes for XTIUSD / XBRUSD / XNGUSD (no roll gaps!)
  crack_px     : DataFrame with columns cl, rb, ho = WTI ($/bbl), RBOB ($/gal), ULSD/heating oil ($/gal)
Output:
  target position per market as a fraction of account equity (e.g. 0.42 = long notional 42% of equity).

Turn a target into lots with:  lots = target * equity / (price * contract_size)
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TARGET_VOL = 0.15       # per market, annualised
CAP = 3.0               # max |position| as multiple of equity
BUFFER = 0.10           # trade only when target moves >10% of the typical position
EWMAC_SPEEDS = (8, 16, 32, 64)            # original blend
BREAKOUT_WINDOWS = (40, 80, 160, 320)
FAST_EWMAC_SPEEDS = (4, 8, 16, 32)         # revised blend
FAST_BREAKOUT_WINDOWS = (20, 40, 80, 160)
TSMOM_LOOKBACKS = (21, 63, 252)            # 1, 3, 12 months
CRACK_WINDOW = 250
VOL_PCTILE_CUT = 0.90   # halve exposure above this percentile of trailing-5y vol (optional overlay)
CRUDE = ("XTIUSD", "XBRUSD")


def _normalise(raw: pd.Series, cap: float = 2.0, min_periods: int = 250) -> pd.Series:
    scale = raw.abs().expanding(min_periods=min_periods).mean()
    return (raw / scale).clip(-cap, cap)


def returns_from_adjusted(closes: pd.Series, unadjusted: pd.Series | None = None) -> pd.Series:
    """Daily % returns. With additive (Panama) back-adjusted prices pass the unadjusted price too."""
    if unadjusted is None:
        return closes.pct_change().fillna(0.0)
    return (closes.diff() / unadjusted.shift(1)).fillna(0.0)


def trend_forecast(r: pd.Series, ewmac_speeds=EWMAC_SPEEDS, breakout_windows=BREAKOUT_WINDOWS) -> pd.Series:
    x = np.log((1 + r).cumprod())
    vol = r.ewm(span=36, min_periods=20).std()
    ew = []
    for f in ewmac_speeds:
        raw = (x.ewm(span=f, min_periods=f).mean() - x.ewm(span=4 * f, min_periods=4 * f).mean()) / vol
        ew.append(_normalise(raw))
    ewmac = _normalise(pd.concat(ew, axis=1).mean(axis=1))
    bo = []
    for n in breakout_windows:
        hi, lo = x.rolling(n, min_periods=n).max(), x.rolling(n, min_periods=n).min()
        raw = ((x - (hi + lo) / 2) / (hi - lo)).ewm(span=max(n // 4, 2)).mean() * 2
        bo.append(_normalise(raw))
    brk = _normalise(pd.concat(bo, axis=1).mean(axis=1))
    return (ewmac + brk) / 2


def tsmom_forecast(r: pd.Series) -> pd.Series:
    x = np.log((1 + r).cumprod())
    return sum(np.sign(x - x.shift(n)) for n in TSMOM_LOOKBACKS) / len(TSMOM_LOOKBACKS)


def revised_trend_forecast(r: pd.Series) -> pd.Series:
    return (tsmom_forecast(r) + trend_forecast(r, FAST_EWMAC_SPEEDS, FAST_BREAKOUT_WINDOWS)) / 2


def crack_forecast(crack_px: pd.DataFrame) -> pd.Series:
    crack = (2 * crack_px["rb"] * 42 + crack_px["ho"] * 42 - 3 * crack_px["cl"]) / 3
    z = (crack - crack.rolling(CRACK_WINDOW).mean()) / crack.rolling(CRACK_WINDOW).std()
    return (z / 2).clip(-1, 1)


def forecast_vol(r: pd.Series) -> pd.Series:
    v = r.ewm(span=36, min_periods=20).std() * math.sqrt(252)
    lr = v.rolling(252 * 10, min_periods=252).mean()
    return (0.7 * v + 0.3 * lr).fillna(v)


def vol_percentile(r: pd.Series) -> pd.Series:
    v = r.ewm(span=36).std()
    return v.rolling(1260, min_periods=500).apply(lambda a: (a[-1] >= a).mean(), raw=True)


def buffer_positions(pos: pd.Series, buffer: float = BUFFER) -> pd.Series:
    p = pos.fillna(0.0).to_numpy()
    scale = pd.Series(np.abs(p)).rolling(250, min_periods=1).mean().to_numpy()
    out, cur = np.zeros_like(p), 0.0
    for i, tgt in enumerate(p):
        band = buffer * max(scale[i], 1e-9)
        if tgt > cur + band:
            cur = tgt - band
        elif tgt < cur - band:
            cur = tgt + band
        if tgt == 0.0:
            cur = 0.0
        out[i] = cur
    return pd.Series(out, index=pos.index)


def target_positions(rets: dict[str, pd.Series], crack_px: pd.DataFrame | None = None,
                     vol_overlay: bool = True, buffered: bool = True, trend: str = "revised") -> pd.DataFrame:
    """rets: {sym: daily % return series of the roll-adjusted CFD/futures}. Returns targets per day.
    The volatility overlay halves the TREND part when the market's vol is above its 90th percentile of the
    trailing five years; the crack tilt (crude only) is added after the overlay."""
    ck = crack_forecast(crack_px) if crack_px is not None else None
    out = {}
    for sym, r in rets.items():
        fc = revised_trend_forecast(r) if trend == "revised" else trend_forecast(r)
        if vol_overlay:
            p = vol_percentile(r).reindex(fc.index)
            fc = fc.where(~(p > VOL_PCTILE_CUT), fc * 0.5)
        if ck is not None and sym in CRUDE:
            fc = (fc + 2 * ck.reindex(fc.index).ffill()) / 2
        pos = (fc.fillna(0.0) * TARGET_VOL / forecast_vol(r)).clip(-CAP, CAP).fillna(0.0)
        out[sym] = buffer_positions(pos) if buffered else pos
    return pd.DataFrame(out)


def orders_for_today(targets_today: pd.Series, current_lots: dict, equity: float, prices: dict,
                     contract_size: dict, lot_step: float = 0.01) -> dict:
    """Convert today's targets into lot deltas (rounded to the broker's lot step)."""
    orders = {}
    for sym, tgt in targets_today.items():
        want = tgt * equity / (prices[sym] * contract_size[sym])
        want = round(want / lot_step) * lot_step
        delta = round(want - current_lots.get(sym, 0.0), 8)
        if abs(delta) >= lot_step:
            orders[sym] = delta
    return orders
