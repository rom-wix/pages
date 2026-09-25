"""E06 summary: collect all intraday grids, pick the IS-best configuration per (sub-)family and instrument,
compute deflated Sharpe (family-level and global trial sets), stationary-bootstrap CIs, cost sensitivity,
per-year tables, and the charts.  Run after the e06_intraday_*.py experiment scripts."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy import stats

from src import backtest as bt
from src import intraday as ix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results")
SYMS = ["XTIUSD", "XNGUSD"]

GRIDS = {"A": "e06_A_orb_grid.csv", "B": "e06_B_momentum_grid.csv", "C": "e06_C_eia_grid.csv",
         "D": "e06_D_session_grid.csv", "E": "e06_E_meanrev_grid.csv"}
TRADES = {"A": "e06_A_trades.pkl", "B": "e06_B_trades.pkl", "C": "e06_C_trades.pkl", "D": "e06_D_trades.pkl",
          "E": "e06_E_trades.pkl"}


def subfamily(key: str) -> str:
    k = key.split("|")
    t = k[1]
    if t == "orb":
        return "A1 ORB opening range"
    if t == "stretch":
        return "A2 ORB Crabel stretch"
    if t == "mom":
        return "B  intraday momentum"
    if t == "eia_cont":
        return "C1 EIA continuation"
    if t == "eia_fade":
        return "C2 EIA fade"
    if t == "eia_pre":
        return "C3 EIA pre-report drift"
    if t == "session":
        return "D1 session hold"
    if t == "dow":
        return "D2 day-of-week hold"
    if t == "sunday_gap":
        return "D3 Sunday-gap"
    if t == "session_walkforward":
        return "D4 walk-forward session pick"
    if t == "mr":
        return "E2 VWAP fade" if k[3] == "vwap" else "E1 z-score fade"
    raise ValueError(key)


def load():
    G = []
    for fam, f in GRIDS.items():
        g = pd.read_csv(os.path.join(OUT, f))
        g["fam"] = fam
        G.append(g)
    G = pd.concat(G, ignore_index=True)
    G["sub"] = G["key"].map(subfamily)
    G["degenerate"] = ~np.isfinite(G["is_sharpe"]) | (G["full_trades"].fillna(0) == 0)
    T = {}
    for fam, f in TRADES.items():
        T.update(pd.read_pickle(os.path.join(ix.CACHE, f)))
    return G, T


def daily(T, key, mult=1.0):
    sym = key.split("|")[0]
    S = ix.session_matrix(sym)
    return ix.daily_pnl(T[key], ix.valid_dates(S), mult)


def clip(x, p):
    a, b = ix.PERIODS[p]
    if a is not None:
        x = x[x.index >= a]
    if b is not None:
        x = x[x.index <= b]
    return x


def dsr(x, trial_srs):
    x = x.dropna()
    trial_srs = [s for s in trial_srs if np.isfinite(s)]
    return bt.deflated_sharpe(bt.sharpe(x), trial_srs, len(x), float(stats.skew(x)), float(stats.kurtosis(x, fisher=False)))


def sr0(trial_srs):
    """Expected maximum annualised Sharpe of N unskilled trials with the observed dispersion (the DSR hurdle)."""
    x = np.asarray([v for v in trial_srs if np.isfinite(v)])
    n = len(x)
    if n < 2:
        return 0.0
    g = 0.5772156649
    return float(np.std(x) * ((1 - g) * stats.norm.ppf(1 - 1.0 / n) + g * stats.norm.ppf(1 - 1.0 / (n * np.e))))


def main():
    G, T = load()
    live = G[~G["degenerate"]]
    n_trials = live.groupby(["sub", "sym"]).size()
    fam_trials = live.groupby(["fam", "sym"]).size()
    print("trials per family x instrument:\n", fam_trials.to_string())
    print("total trials:", len(live), " (degenerate, excluded:", int(G["degenerate"].sum()), ")")
    all_full = live["full_sharpe"].tolist()
    rows = []
    for (sub, sym), g in live.groupby(["sub", "sym"]):
        best = g.sort_values("is_sharpe", ascending=False).iloc[0]
        key = best["key"]
        dn = daily(T, key)
        fam = best["fam"]
        famg = live[(live.fam == fam) & (live.sym == sym)]
        r = {"sub": sub, "sym": sym, "best_config": key.split("|", 1)[1], "n_trials_sub": len(g),
             "n_trials_family": len(famg)}
        for c in ["is_sharpe", "oos_sharpe", "full_sharpe", "is_gross_sharpe", "oos_gross_sharpe", "full_gross_sharpe",
                  "full_trades_py", "oos_trades_py", "full_avg_bps", "oos_avg_bps", "full_avg_gross_bps", "full_hit",
                  "oos_hit", "full_max_dd", "full_t_stat", "oos_t_stat", "full_ann_ret", "full_ann_vol",
                  "is_sharpe_0x", "oos_sharpe_0x", "full_sharpe_0x", "is_sharpe_2x", "oos_sharpe_2x", "full_sharpe_2x"]:
            r[c] = best.get(c, np.nan)
        # deflated Sharpe: IS (selection period) vs IS Sharpes of the family's trials; full vs full; global
        r["oos_ex2020_sharpe"] = bt.sharpe(clip(dn, "oos")[clip(dn, "oos").index.year != 2020])
        r["full_ex2020_sharpe"] = bt.sharpe(dn[dn.index.year != 2020])
        r["sr0_is_family"] = sr0(famg["is_sharpe"].tolist())
        r["dsr_is_family"] = dsr(clip(dn, "is"), famg["is_sharpe"].tolist())
        r["dsr_full_family"] = dsr(dn, famg["full_sharpe"].tolist())
        r["dsr_full_global"] = dsr(dn, all_full)
        # null-SE flavour: hurdle = expected max of N zero-skill trials (N = family trials / all trials)
        r["dsrN_is_family"] = ix.dsr_null(clip(dn, "is"), len(famg))
        r["dsrN_full_family"] = ix.dsr_null(dn, len(famg))
        r["dsrN_full_global"] = ix.dsr_null(dn, len(all_full))
        r["share_family_trials_oos_net_pos"] = float((famg["oos_sharpe"] > 0).mean())
        rows.append(r)
    R = pd.DataFrame(rows).sort_values("oos_sharpe", ascending=False)
    # bootstrap CIs for the top rows (and every row: cheap enough)
    lo_f, hi_f, lo_o, hi_o = [], [], [], []
    for _, r in R.iterrows():
        key = f"{r['sym']}|{r['best_config']}"
        dn = daily(T, key)
        a, b = bt.bootstrap_sharpe_ci(dn, n=2000, block=20, seed=1)
        c, d = bt.bootstrap_sharpe_ci(clip(dn, "oos"), n=2000, block=20, seed=2)
        lo_f.append(a), hi_f.append(b), lo_o.append(c), hi_o.append(d)
    R["full_ci_lo"], R["full_ci_hi"], R["oos_ci_lo"], R["oos_ci_hi"] = lo_f, hi_f, lo_o, hi_o
    R.to_csv(os.path.join(OUT, "e06_ranked.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 50)
    show = ["sub", "sym", "best_config", "n_trials_sub", "is_sharpe", "oos_sharpe", "full_sharpe", "full_gross_sharpe",
            "oos_gross_sharpe", "full_trades_py", "full_avg_bps", "full_hit", "full_max_dd", "full_t_stat",
            "full_sharpe_2x", "oos_ex2020_sharpe", "sr0_is_family", "dsr_is_family", "dsr_full_global", "dsrN_is_family",
            "dsrN_full_family", "dsrN_full_global", "oos_ci_lo", "oos_ci_hi"]
    print(R[show].round(3).to_string(index=False))

    # per-year tables for the promising / marginal candidates
    cands = R[(R["oos_sharpe"] > 0.1) & (R["is_sharpe"] > 0.1)]
    yrows = []
    for _, r in cands.iterrows():
        key = f"{r['sym']}|{r['best_config']}"
        S = ix.session_matrix(r["sym"])
        y = ix.yearly_stats(T[key], S)
        y["gross_bps"] = y["gross_ret"] / y["trades"].replace(0, np.nan) * 1e4
        y.insert(0, "strategy", key)
        yrows.append(y)
    Y = pd.concat(yrows, ignore_index=True) if yrows else pd.DataFrame()
    Y.to_csv(os.path.join(OUT, "e06_yearly.csv"), index=False)
    print(Y.round(3).to_string(index=False))
    # all-trial summary per family (how many survive OOS after costs)
    fs = live.groupby(["fam", "sym"]).agg(trials=("key", "size"), oos_net_pos=("oos_sharpe", lambda x: (x > 0).mean()),
                                          oos_gross_pos=("oos_sharpe_0x", lambda x: (x > 0).mean()),
                                          median_oos_net=("oos_sharpe", "median"), median_oos_gross=("oos_sharpe_0x", "median"),
                                          best_is=("is_sharpe", "max"))
    fs.to_csv(os.path.join(OUT, "e06_family_trial_summary.csv"))
    print(fs.round(3).to_string())
    import e06_intraday_report as rep
    rep.charts(R, T, live)
    rep.write_markdown(R, Y, fs, live, G, T)


if __name__ == "__main__":
    main()
