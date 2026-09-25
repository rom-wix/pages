"""Small, explicit, vectorised daily backtester + metrics.

Timing convention (no look-ahead):
  * `pos[t]` is the target position decided with information available at the close of day t.
  * With lag=1 it is traded at that close and earns ret[t+1]  (held[t+1] = pos[t]).
    lag=2 means "trade one day later" (a robustness check that kills close-to-close illusions).
  * Positions are fractions of equity notional (0.5 = long 50% of account equity).

Costs:
  * spread/slippage: |held[t] - held[t-1]| * cost_per_side
  * financing markup: |held[t]| * FIN_MARKUP * calendar_days/365
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from . import costs

TD = 252


# ----------------------------------------------------------------------------------------------
# Risk helpers
# ----------------------------------------------------------------------------------------------
def ewma_vol(r: pd.Series, span: int = 36, min_periods: int = 20) -> pd.Series:
    """Annualised EWMA volatility using returns up to and including t."""
    return r.ewm(span=span, min_periods=min_periods).std() * math.sqrt(TD)


def blended_vol(r: pd.Series, span: int = 36, long_years: int = 10) -> pd.Series:
    """Carver-style blend: 70% recent EWMA vol + 30% long-run average (reduces vol-timing noise)."""
    v = ewma_vol(r, span)
    lr = v.rolling(TD * long_years, min_periods=TD).mean()
    return (0.7 * v + 0.3 * lr).fillna(v)


def vol_scale(signal: pd.Series, r: pd.Series, target: float = 0.15, cap: float = 3.0,
              span: int = 36, blend: bool = True) -> pd.Series:
    """Position = signal * target_vol / forecast_vol.  `signal` should be ~[-1, 1] (or forecast/10)."""
    vol = blended_vol(r, span) if blend else ewma_vol(r, span)
    pos = signal * target / vol
    return pos.clip(-cap, cap).fillna(0.0)


def buffer_positions(pos: pd.Series, buffer: float = 0.1) -> pd.Series:
    """Only trade when the target moves more than `buffer` * |typical position| away from the current
    position; then trade to the edge of the band (Carver's position inertia). Cuts turnover a lot."""
    p = pos.fillna(0.0).to_numpy()
    scale = pd.Series(np.abs(p)).rolling(250, min_periods=1).mean().to_numpy()
    out = np.zeros_like(p)
    cur = 0.0
    for i, tgt in enumerate(p):
        band = buffer * max(scale[i], 1e-9)
        if tgt > cur + band:
            cur = tgt - band
        elif tgt < cur - band:
            cur = tgt + band
        if tgt == 0.0:  # explicit flat target -> go flat
            cur = 0.0
        out[i] = cur
    return pd.Series(out, index=pos.index)


# ----------------------------------------------------------------------------------------------
# Engine
# ----------------------------------------------------------------------------------------------
def run(ret: pd.Series, pos: pd.Series, sym: str, cost_mult: float = 1.0,
        fin: float | None = None, lag: int = 1, cost_per_side: float | None = None) -> pd.DataFrame:
    fin = costs.FIN_MARKUP if fin is None else fin
    cps = costs.per_side(sym, cost_mult) if cost_per_side is None else cost_per_side * cost_mult
    ret = ret.astype(float)
    p = pos.reindex(ret.index).ffill().fillna(0.0)
    held = p.shift(lag).fillna(0.0)
    trade = held.diff().abs()
    trade.iloc[0] = abs(held.iloc[0])
    days = pd.Series(ret.index, index=ret.index).diff().dt.days.fillna(1).clip(lower=1)
    gross = held * ret
    tcost = trade * cps
    fcost = held.abs() * fin * days / 365.0
    net = gross - tcost - fcost
    return pd.DataFrame({"gross": gross, "net": net, "tcost": tcost, "fcost": fcost,
                         "held": held, "trade": trade})


def run_portfolio(rets: pd.DataFrame, pos: pd.DataFrame, weights: dict | None = None, **kw) -> dict:
    """Run each symbol and sum net returns (positions already expressed in equity fractions).
    `weights` multiplies each symbol's positions (e.g. 1/3 each for an equal-risk book)."""
    res = {}
    for s in pos.columns:
        w = 1.0 if weights is None else weights.get(s, 0.0)
        res[s] = run(rets[s].dropna(), pos[s] * w, s, **kw)
    idx = sorted(set().union(*[r.index for r in res.values()]))
    net = pd.concat({s: r["net"] for s, r in res.items()}, axis=1).reindex(idx).fillna(0.0).sum(axis=1)
    gross = pd.concat({s: r["gross"] for s, r in res.items()}, axis=1).reindex(idx).fillna(0.0).sum(axis=1)
    return {"per_symbol": res, "net": net, "gross": gross}


# ----------------------------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------------------------
def max_drawdown(r: pd.Series) -> float:
    eq = (1 + r.fillna(0)).cumprod()
    return float((eq / eq.cummax() - 1).min())


def sharpe(r: pd.Series) -> float:
    r = r.dropna()
    sd = r.std()
    return float(r.mean() / sd * math.sqrt(TD)) if sd > 0 else float("nan")


def metrics(r: pd.Series, bt: pd.DataFrame | None = None, name: str = "") -> dict:
    r = r.dropna()
    if len(r) < 20:
        return {"name": name, "n": len(r)}
    years = len(r) / TD
    mu, sd = r.mean() * TD, r.std() * math.sqrt(TD)
    eq = (1 + r).cumprod()
    cagr = eq.iloc[-1] ** (1 / years) - 1 if eq.iloc[-1] > 0 else -1.0
    mdd = max_drawdown(r)
    dn = r[r < 0].std() * math.sqrt(TD)
    out = {
        "name": name, "start": str(r.index[0].date()), "end": str(r.index[-1].date()),
        "years": round(years, 1), "ann_ret": mu, "cagr": cagr, "ann_vol": sd,
        "sharpe": mu / sd if sd > 0 else np.nan, "sortino": mu / dn if dn > 0 else np.nan,
        "max_dd": mdd, "calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
        "skew": float(r.skew()), "t_stat": (mu / sd) * math.sqrt(years) if sd > 0 else np.nan,
        "hit_rate": float((r[r != 0] > 0).mean()) if (r != 0).any() else np.nan,
    }
    if bt is not None:
        out["turnover_py"] = float(bt["trade"].sum() / years)
        out["cost_py"] = float((bt["tcost"] + bt["fcost"]).sum() / years)
        out["gross_sharpe"] = sharpe(bt["gross"])
        out["avg_abs_pos"] = float(bt["held"].abs().mean())
        out["time_in_mkt"] = float((bt["held"].abs() > 1e-9).mean())
    return out


def fmt(m: dict) -> str:
    keys = [("sharpe", "{:.2f}"), ("cagr", "{:.1%}"), ("ann_vol", "{:.1%}"), ("max_dd", "{:.1%}"),
            ("t_stat", "{:.1f}"), ("turnover_py", "{:.1f}"), ("cost_py", "{:.2%}"), ("gross_sharpe", "{:.2f}")]
    return " ".join(f"{k}={f.format(m[k])}" for k, f in keys if k in m and m[k] == m[k])


def by_period(r: pd.Series, edges=("1990", "2000", "2010", "2020", "2030")) -> dict:
    out = {}
    for a, b in zip(edges[:-1], edges[1:]):
        x = r[(r.index >= a) & (r.index < b)]
        if len(x) > 60:
            out[f"{a}-{int(b) - 1}"] = round(sharpe(x), 2)
    return out


def yearly(r: pd.Series) -> pd.Series:
    return (1 + r).groupby(r.index.year).prod() - 1


def _stationary_bootstrap_sr(x: np.ndarray, n: int, block: int, seed: int) -> np.ndarray:
    from numba import njit

    @njit(cache=False)
    def _run(x, n, p, seed):
        np.random.seed(seed)
        T = x.shape[0]
        out = np.empty(n)
        for k in range(n):
            i = np.random.randint(T)
            s1 = 0.0
            s2 = 0.0
            for t in range(T):
                if t > 0 and np.random.random() < p:
                    i = np.random.randint(T)
                v = x[i]
                s1 += v
                s2 += v * v
                i = (i + 1) % T
            m = s1 / T
            sd = math.sqrt(max(s2 / T - m * m, 1e-18))
            out[k] = m / sd * math.sqrt(252.0)
        return out

    return _run(x, n, 1.0 / block, seed)


def bootstrap_sharpe_ci(r: pd.Series, n: int = 2000, block: int = 20, seed: int = 0, alpha: float = 0.05):
    """Stationary (Politis-Romano) bootstrap CI for the annualised Sharpe ratio."""
    x = r.dropna().to_numpy().astype(np.float64)
    srs = _stationary_bootstrap_sr(x, n, block, seed)
    return float(np.quantile(srs, alpha / 2)), float(np.quantile(srs, 1 - alpha / 2))


def deflated_sharpe(sr_ann: float, sr_trials_ann: list, T: int, skew: float, kurt: float) -> float:
    """Bailey & Lopez de Prado (2014) deflated Sharpe ratio: P(true SR > 0) after N trials.
    kurt = non-excess kurtosis."""
    N = max(len(sr_trials_ann), 1)
    sr = sr_ann / math.sqrt(TD)
    v = np.var(np.asarray(sr_trials_ann) / math.sqrt(TD)) if N > 1 else 0.0
    g = 0.5772156649
    sr0 = math.sqrt(v) * ((1 - g) * stats.norm.ppf(1 - 1.0 / N) + g * stats.norm.ppf(1 - 1.0 / (N * math.e))) if N > 1 else 0.0
    den = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4.0 * sr ** 2, 1e-12))
    return float(stats.norm.cdf((sr - sr0) * math.sqrt(T - 1) / den))
