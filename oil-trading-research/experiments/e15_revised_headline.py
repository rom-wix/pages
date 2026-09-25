"""E15 - Headline statistics for the revised recommended configuration.

revised = 50% 1/3/12-month momentum + 50% fast-to-medium EWMA/breakout blend, extreme-vol overlay,
          crack tilt for WTI & Brent (50/50 with trend), 15% vol target per market, 10% buffer.
Also 'revised (no crack)' for windows where product prices are unavailable (spot 2024-26, last 12m).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings("ignore")
import json

import numpy as np
import pandas as pd

from src import backtest as bt
from src.evaluate import evaluate
from experiments.e11_extras import vol_filter
from experiments.e14_speed_blends import BLENDS, with_crack, FUT, SPOT

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
TREND = vol_filter(BLENDS["tsmom 1/3/12m + fast+medium"])
STRATS = {"revised": with_crack(TREND), "revised_no_crack": TREND}


def rolling(r):
    eq = (1 + r.fillna(0)).cumprod()
    rows = []
    for yrs in [1, 2, 3, 5]:
        w = (eq.shift(-252 * yrs) / eq - 1).dropna()
        rows.append({"years": yrs, "p_loss": float((w < 0).mean()), "median": float(w.median()),
                     "p10": float(w.quantile(.1)), "worst": float(w.min())})
    dd = eq / eq.cummax() - 1
    uw = (dd < 0).astype(int)
    lengths = uw.groupby((uw.diff() != 0).cumsum()).sum()
    return rows, float(dd.min()), float(lengths.max() / 252)


if __name__ == "__main__":
    out, series = {}, {}
    for name, fn in STRATS.items():
        res = evaluate(fn, name, data=FUT, keep_series=True)
        port = res["port"]["1991-11":]
        m = bt.metrics(port, None, name)
        tab = res["table"].set_index("symbol")
        m["is_sharpe"], m["oos_sharpe"] = tab.loc["PORT", "is_sharpe"], tab.loc["PORT", "oos_sharpe"]
        m["ci95"] = list(bt.bootstrap_sharpe_ci(port, n=1000))
        m["yearly"] = {int(k): float(v) for k, v in bt.yearly(port).items()}
        m["rolling"], m["max_dd_check"], m["underwater_years"] = rolling(port)
        m["per_symbol"] = tab[["sharpe", "cagr", "max_dd", "turnover_py", "cost_py", "is_sharpe", "oos_sharpe",
                               "avg_abs_pos"]].round(3).to_dict("index")
        m["cost_py_mean"] = float(tab.loc[["XTIUSD", "XBRUSD", "XNGUSD"], "cost_py"].mean())
        m["decades"] = {k: float(tab.loc["PORT", k]) for k in tab.columns if k.startswith("sr_")}
        out[name] = m
        series[name] = port
    # recent windows (spot, no crack available)
    for lab, st, en in [("spot_2024_26", "2024-04-01", None), ("last12m", "2025-09-23", "2026-09-22")]:
        t = evaluate(TREND, "revised_no_crack", data=SPOT, start=st, end=en)["table"].set_index("symbol")
        out[lab] = {s: {"sharpe": float(t.loc[s, "sharpe"]), "max_dd": float(t.loc[s, "max_dd"]),
                        "cagr": float(t.loc[s, "cagr"])} for s in t.index}
    json.dump(out, open(os.path.join(OUT, "e15_revised_headline.json"), "w"), indent=1, default=float)
    pd.DataFrame(series).to_csv(os.path.join(OUT, "e15_revised_daily_returns.csv"))
    for k in ["revised", "revised_no_crack"]:
        v = out[k]
        print(k, bt.fmt(v), "IS %.2f OOS %.2f" % (v["is_sharpe"], v["oos_sharpe"]), "CI", np.round(v["ci95"], 2),
              "underwater %.1fy" % v["underwater_years"], "cost %.2f%%" % (100 * v["cost_py_mean"]))
        print("   rolling:", [(r["years"], round(r["p_loss"], 2), round(r["worst"], 3)) for r in v["rolling"]])
    print("spot 2024-26:", {s: round(x["sharpe"], 2) for s, x in out["spot_2024_26"].items()})
    print("last 12m:", {s: round(x["sharpe"], 2) for s, x in out["last12m"].items()})
