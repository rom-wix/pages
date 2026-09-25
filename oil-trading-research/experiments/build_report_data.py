"""Collect results into results/report_data.json for the HTML report (small, pre-aggregated)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings("ignore")
import json

import numpy as np
import pandas as pd

from src import backtest as bt
from src.evaluate import positions, evaluate
from src.data import spot_daily
from experiments.e10_portfolio import trend, FUT, SPOT

R = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def monthly_equity(r: pd.Series) -> list:
    m = (1 + r.fillna(0)).groupby(r.index.to_period("M")).prod()
    eq = m.cumprod()
    return [[str(p), round(float(v), 4)] for p, v in eq.items()]


def main():
    out = {}
    S = pd.read_csv(os.path.join(R, "e10_daily_returns.csv"), index_col=0, parse_dates=True)
    start = "1991-11-01"  # all three live + warm-up done
    eqs = {}
    for k in ["trend+crack", "trend", "crack", "long_only"]:
        eqs[k] = monthly_equity(S[k][start:])
    for s in ["XTIUSD", "XBRUSD", "XNGUSD"]:
        eqs[f"trend:{s}"] = monthly_equity(S[f"trend:{s}"][start:])
    out["equity"] = eqs
    H = json.load(open(os.path.join(R, "e10_headline.json")))
    out["headline"] = {k: {kk: H[k][kk] for kk in ["sharpe", "cagr", "ann_vol", "max_dd", "t_stat", "sortino",
                                                     "calmar", "start", "end"] if kk in H[k]} for k in H}
    for k in H:
        if "ci95" in H[k]:
            out["headline"][k]["ci95"] = H[k]["ci95"]
        if "yearly" in H[k]:
            out["headline"][k]["yearly"] = H[k]["yearly"]
        if "per_symbol" in H[k]:
            out["headline"][k]["per_symbol"] = H[k]["per_symbol"]

    # trend family: per symbol x decade, and variants
    e01 = pd.read_csv(os.path.join(R, "e01_trend.csv"))
    fut = e01[e01.dataset == "fut"]
    out["trend_variants"] = fut[fut.symbol == "PORT"][["name", "sharpe", "is_sharpe", "oos_sharpe", "max_dd"]] \
        .round(3).to_dict("records")
    tc = fut[fut.name == "trend_combo"].set_index("symbol")
    out["trend_decades"] = {s: {d: float(tc.loc[s, f"sr_{d}"]) for d in
                                ["1990-1999", "2000-2009", "2010-2019", "2020-2029"]} for s in tc.index}
    sp = e01[(e01.dataset == "spot") & (e01.name == "trend_combo")].set_index("symbol")
    out["trend_spot_vs_fut"] = {s: {"fut": float(tc.loc[s, "sharpe"]), "spot": float(sp.loc[s, "sharpe"])}
                                for s in tc.index}

    # robustness grid (portfolio)
    rob = pd.read_csv(os.path.join(R, "e10_robustness.csv"))
    rob = rob[rob.symbol == "PORT"][["name", "setting", "sharpe", "cagr", "max_dd", "is_sharpe", "oos_sharpe"]]
    out["robustness"] = rob.round(3).to_dict("records")

    # crack deep dive
    e09 = pd.read_csv(os.path.join(R, "e09_crack.csv"))
    p9 = e09[e09.symbol == "PORT"].copy()
    p9["lag"] = p9["lag"].fillna(1)
    out["crack_lag"] = p9[p9.name == "crack321_z250"][p9.cost_mult.isna()][["lag", "sharpe"]].round(3) \
        .to_dict("records")
    out["crack_variants"] = p9[(p9.lag == 1) & p9.cost_mult.isna()][["name", "sharpe", "is_sharpe",
                                                                      "oos_sharpe"]].round(3).to_dict("records")

    # carry fragility
    e02 = pd.read_csv(os.path.join(R, "e02_carry.csv"))
    out["carry"] = e02[e02.symbol.isin(["PORT", "XTIUSD", "XBRUSD", "XNGUSD"])][
        ["name", "symbol", "sharpe", "is_sharpe", "oos_sharpe", "turnover_py"]].round(3).to_dict("records")

    # mean reversion (portfolio, lag1/2)
    e03 = pd.read_csv(os.path.join(R, "e03_mean_reversion.csv"))
    out["mean_reversion"] = e03[e03.symbol == "PORT"][["name", "lag", "sharpe", "is_sharpe", "oos_sharpe"]] \
        .round(3).to_dict("records")
    out["mean_reversion_symbols"] = e03[e03.symbol != "PORT"][["name", "lag", "symbol", "sharpe", "gross_sharpe"]] \
        .round(3).to_dict("records")

    # relative value
    e05 = pd.read_csv(os.path.join(R, "e05_relative_value.csv"))
    out["relative_value"] = e05[["pair", "dataset", "name", "lag", "sharpe", "gross_sharpe", "is_sharpe",
                                 "oos_sharpe"]].round(3).to_dict("records")

    # holdout on spot: monthly P&L of trend per symbol + prices
    hold = {}
    for sym in ["XTIUSD", "XBRUSD"]:
        d = SPOT[sym]
        res = bt.run(d["ret"], positions(d, trend), sym)
        x = res["2024-01":]
        m = x.groupby(x.index.to_period("M")).agg(net=("net", "sum"), pos=("held", "mean"))
        hold[sym] = [[str(k), round(float(v.net), 4), round(float(v.pos), 3)] for k, v in m.iterrows()]
    spd = spot_daily()["2023-06":]
    hold["prices"] = {s: [[str(i.date()), float(v)] for i, v in spd[s].dropna().resample("W-FRI").last().items()]
                      for s in ["XTIUSD", "XBRUSD", "XNGUSD"]}
    ht = pd.read_csv(os.path.join(R, "e10_holdout_spot.csv"))
    hold["table"] = ht[["name", "symbol", "sharpe", "cagr", "ann_vol", "max_dd"]].round(3).to_dict("records")
    out["holdout"] = hold

    ex = os.path.join(R, "e11_extras.json")
    if os.path.exists(ex):
        out["extras"] = json.load(open(ex))

    # extra agent outputs, if present
    for f in ["e04_seasonality_summary.md", "e06_intraday_summary.md", "e07_grid_summary.md", "e08_ml_summary.md"]:
        p = os.path.join(R, f)
        out.setdefault("agent_md", {})[f] = open(p).read() if os.path.exists(p) else None

    json.dump(out, open(os.path.join(R, "report_data.json"), "w"), default=float)
    print("wrote", os.path.join(R, "report_data.json"), os.path.getsize(os.path.join(R, "report_data.json")) // 1024, "KB")


if __name__ == "__main__":
    main()
