"""Glue: datasets x signal functions -> positions -> backtests -> tidy metric tables."""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from . import backtest as bt
from .data import SYMBOLS, futures_panel, spot_returns

IS_END = "2007-12-31"  # in-sample 1990-2007, out-of-sample 2008-2024 (futures)


def get_dataset(kind: str = "fut") -> dict[str, pd.DataFrame]:
    """fut : rolled futures 1990-2024-03 (P&L-accurate incl. roll yield)
       spot: EIA spot 1986/1997-2026-09 (no roll yield; used for robustness and the 2024-26 holdout)"""
    out = {}
    if kind == "fut":
        for s, f in futures_panel().items():
            out[s] = f[["ret", "tri", "carry", "price"]].copy()
    elif kind == "spot":
        for s in SYMBOLS:
            r = spot_returns(s)
            r = r.clip(-0.5, 0.5)
            out[s] = pd.DataFrame({"ret": r, "tri": (1 + r).cumprod()})
    else:
        raise ValueError(kind)
    return out


def positions(df: pd.DataFrame, signal_fn: Callable, target_vol: float = 0.15, buffer: float | None = 0.1,
              vol_target: bool = True, cap: float = 3.0) -> pd.Series:
    sig = signal_fn(df).reindex(df.index).fillna(0.0)
    if vol_target:
        pos = bt.vol_scale(sig, df["ret"], target=target_vol, cap=cap)
    else:
        pos = sig.clip(-cap, cap)
    if buffer:
        pos = bt.buffer_positions(pos, buffer)
    return pos


def evaluate(signal_fn: Callable, name: str, kind: str = "fut", symbols=SYMBOLS, target_vol: float = 0.15,
             cost_mult: float = 1.0, fin: float | None = None, lag: int = 1, buffer: float | None = 0.1,
             vol_target: bool = True, start: str | None = None, end: str | None = None,
             data: dict | None = None, keep_series: bool = False) -> dict:
    """start/end restrict the *evaluation window* only; signals always use the full history before it."""
    data = data or get_dataset(kind)
    rows, nets = [], {}
    for s in symbols:
        df = data[s]
        if end:
            df = df[df.index <= end]
        pos = positions(df, signal_fn, target_vol, buffer, vol_target)
        res = bt.run(df["ret"], pos, s, cost_mult=cost_mult, fin=fin, lag=lag)
        # skip warm-up: start metrics once a position has been possible (first 260 days)
        res = res.iloc[260:] if len(res) > 520 else res
        if start:
            res = res[res.index >= start]
        m = bt.metrics(res["net"], res, name)
        m.update({"symbol": s, "dataset": kind})
        m["is_sharpe"] = bt.sharpe(res["net"][res.index <= IS_END]) if (res.index <= IS_END).sum() > 250 else np.nan
        m["oos_sharpe"] = bt.sharpe(res["net"][res.index > IS_END]) if (res.index > IS_END).sum() > 250 else np.nan
        for k, v in bt.by_period(res["net"]).items():
            m["sr_" + k] = v
        rows.append(m)
        nets[s] = res["net"]
    port = pd.concat(nets, axis=1).fillna(0.0)
    # equal weight across instruments that are live on each date (each is already vol-targeted)
    live = pd.concat({s: (data[s]["ret"].reindex(port.index).notna()) for s in symbols}, axis=1)
    pr = (port * live).sum(axis=1) / live.sum(axis=1).replace(0, np.nan)
    pr = pr.dropna()
    m = bt.metrics(pr, None, name)
    m.update({"symbol": "PORT", "dataset": kind})
    m["is_sharpe"] = bt.sharpe(pr[pr.index <= IS_END]) if (pr.index <= IS_END).sum() > 250 else np.nan
    m["oos_sharpe"] = bt.sharpe(pr[pr.index > IS_END]) if (pr.index > IS_END).sum() > 250 else np.nan
    for k, v in bt.by_period(pr).items():
        m["sr_" + k] = v
    rows.append(m)
    out = {"table": pd.DataFrame(rows)}
    if keep_series:
        out["nets"] = nets
        out["port"] = pr
    return out


SHOW = ["name", "symbol", "dataset", "sharpe", "cagr", "ann_vol", "max_dd", "t_stat", "is_sharpe", "oos_sharpe",
        "turnover_py", "cost_py", "gross_sharpe"]


def show(tbl: pd.DataFrame, cols=None) -> str:
    cols = cols or [c for c in SHOW if c in tbl.columns] + [c for c in tbl.columns if c.startswith("sr_")]
    t = tbl[cols].copy()
    for c in t.columns:
        if t[c].dtype.kind == "f":
            t[c] = t[c].round(3)
    return t.to_string(index=False)
