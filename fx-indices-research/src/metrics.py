"""Trade-list metrics. R = pnl / initial risk (entry to stop), net of costs; every trade risks 1R."""
from __future__ import annotations

import numpy as np
import pandas as pd

SPLIT = pd.Timestamp("2026-06-01", tz="UTC")     # first half Feb-May, second half Jun-Sep
WEEKS = (pd.Timestamp("2026-09-26", tz="UTC") - pd.Timestamp("2026-02-02", tz="UTC")).days / 7


def max_dd(x: np.ndarray) -> float:
    if len(x) == 0:
        return 0.0
    eq = np.cumsum(x)
    peak = np.maximum.accumulate(np.concatenate([[0], eq]))[1:]
    return float((peak - eq).max())


def summarize(tr: pd.DataFrame, r_col: str = "r", n_symbols: int | None = None) -> dict:
    tr = tr.sort_values("exit_time")
    r = tr[r_col].values
    n = len(r)
    if n == 0:
        return dict(n=0)
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    h1, h2 = tr[tr.entry_time < SPLIT][r_col], tr[tr.entry_time >= SPLIT][r_col]
    daily = tr.groupby(tr.exit_time.dt.floor("D"))[r_col].sum()
    days = pd.date_range("2026-02-02", "2026-09-25", freq="B", tz="UTC")
    daily = daily.reindex(days, fill_value=0.0)
    sd = r.std(ddof=1) if n > 1 else np.nan
    nsym = n_symbols or tr["symbol"].nunique()
    return dict(
        n=n, per_week=n / WEEKS / max(nsym, 1), win=float((r > 0).mean()), avg_r=float(r.mean()), med_r=float(np.median(r)),
        sum_r=float(r.sum()), pf=float(wins / losses) if losses > 0 else np.inf, t=float(r.mean() / sd * np.sqrt(n)) if sd and sd > 0 else np.nan,
        sharpe=float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else np.nan,
        max_dd_r=max_dd(r), avg_bp=float(tr["ret_bp"].mean()), hold_h=float(tr["hold_min"].median() / 60),
        h1_avg=float(h1.mean()) if len(h1) else np.nan, h2_avg=float(h2.mean()) if len(h2) else np.nan,
        h1_n=len(h1), h2_n=len(h2),
    )


def by_symbol(tr: pd.DataFrame, r_col="r") -> pd.DataFrame:
    return pd.DataFrame({s: summarize(g, r_col, 1) for s, g in tr.groupby("symbol")}).T


def stress_r(tr: pd.DataFrame, extra_cost_mult: float = 0.5) -> pd.Series:
    """R after adding extra_cost_mult * round-trip cost (spread/commission/slippage stress)."""
    return (tr["pnl"] - extra_cost_mult * tr["cost_rt"]) / tr["risk"]


def block_bootstrap_p(tr: pd.DataFrame, r_col="r", n_boot=5000, seed=0) -> float:
    """P(mean daily R <= 0) by resampling whole days (keeps same-day correlation across symbols)."""
    daily = tr.groupby(tr.exit_time.dt.floor("D"))[r_col].sum().values
    if len(daily) < 5:
        return np.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(daily), size=(n_boot, len(daily)))
    means = daily[idx].mean(axis=1)
    return float((means <= 0).mean())
