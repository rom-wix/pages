"""Run strategy families over their universes and collect trades."""
from __future__ import annotations

import json
import os
import traceback
from multiprocessing import Pool

import numpy as np
import pandas as pd

import costs as K
import data as D
import strategies as S
from engine import simulate, one_at_a_time

START = pd.Timestamp("2026-02-01", tz="UTC")   # first minute of the public sample


def configs(family: str) -> list[tuple[str, dict, bool]]:
    f = S.FAMILIES[family]
    out = [("default", dict(f["default"]), True)]
    seen = {json.dumps(f["default"], sort_keys=True)}
    for i, g in enumerate(S.grid(**f["grid"])):
        cfg = dict(f["default"])
        cfg.update(g)
        key = json.dumps(cfg, sort_keys=True)
        if key in seen:
            if key == json.dumps(f["default"], sort_keys=True):
                continue
            continue
        seen.add(key)
        out.append((f"g{i:03d}", cfg, False))
    return out


def run_one(family: str, cfg_id: str, cfg: dict, sym: str, cost_mult: float = 1.0) -> pd.DataFrame:
    f = S.FAMILIES[family]
    orders = f["fn"](sym, **cfg)
    if len(orders) == 0:
        return pd.DataFrame()
    m = D.load_minutes(sym)
    px = float(m["close"].iloc[-1])
    tr = simulate(m, orders, K.cost_rt(sym, cost_mult), K.slip_base(sym, cost_mult), 0.1, K.financing(sym, px))
    if len(tr) == 0:
        return tr
    if "group" in tr.columns and tr["group"].notna().any():
        # OCO: first leg to fill wins; ties -> keep the worse outcome
        tr = tr.sort_values(["entry_time", "r"]).groupby("group", as_index=False, sort=False).head(1)
    tr["family"], tr["cfg_id"], tr["symbol"] = family, cfg_id, sym
    tr["strategy"] = family + ":" + cfg_id
    tr = one_at_a_time(tr)
    tr["cost_rt"] = K.cost_rt(sym, cost_mult)
    tr["cfg"] = json.dumps(cfg, sort_keys=True)
    keep = ["family", "cfg_id", "cfg", "symbol", "side", "entry_time", "exit_time", "entry", "exit", "sl_px", "tp_px",
            "reason", "risk", "gross", "cost", "cost_rt", "pnl", "r", "ret_bp", "hold_min", "nights", "mfe_r", "mae_r"]
    return tr[keep]


def _task(args):
    family, cfg_id, cfg, sym = args
    try:
        return run_one(family, cfg_id, cfg, sym)
    except Exception:
        return RuntimeError(f"{family} {cfg_id} {sym}\n{traceback.format_exc()}")


def run_families(families: list[str], procs: int = 4, defaults_only: bool = False) -> pd.DataFrame:
    tasks = []
    for fam in families:
        for cfg_id, cfg, is_def in configs(fam):
            if defaults_only and not is_def:
                continue
            for sym in S.FAMILIES[fam]["universe"]:
                tasks.append((fam, cfg_id, cfg, sym))
    out, errors = [], []
    with Pool(procs) as p:
        for res in p.imap_unordered(_task, tasks, chunksize=1):
            if isinstance(res, Exception):
                errors.append(str(res))
            elif len(res):
                out.append(res)
    for e in errors[:5]:
        print(e)
    if errors:
        print(f"{len(errors)} task errors")
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()
