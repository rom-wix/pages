"""E13 - Last 12 months (2025-09-23 .. 2026-09-22) on EIA daily spot prices.

1. Regime: returns, volatility vs history, jumps, drawdowns, Brent-WTI spread.
2. Market character: autocorrelation / variance ratios (trending vs mean-reverting) vs 1990-2024.
3. Every daily strategy family re-scored over the last 12 months (signals use all prior history).
Caveats: EIA spot has no roll yield; Dated Brent and Henry Hub cash can diverge a lot from the futures
that XBRUSD / XNGUSD CFDs follow (e.g. Henry Hub spot printed $30.72 in the Jan-2026 cold snap).
One year of daily data gives a Sharpe standard error of ~1.0, so single-year ranks are weak evidence.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings("ignore")
import json

import numpy as np
import pandas as pd

from src import backtest as bt, signals as sg
from src.data import spot_daily
from src.evaluate import evaluate, get_dataset, positions
from experiments.e01_trend import variants as TREND_VARIANTS
from experiments.e03_mean_reversion import variants as MR_VARIANTS
from experiments.e10_portfolio import trend
from experiments.e11_extras import vol_filter

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
START, END = "2025-09-23", "2026-09-22"
SPOT = get_dataset("spot")
for s, df in SPOT.items():
    df["sym"] = s


def regime():
    sp = spot_daily()
    rows = []
    for s in ["XTIUSD", "XBRUSD", "XNGUSD"]:
        p = sp[s].dropna()
        p = p[p > 0]
        r = p.pct_change().dropna()
        ly = r[START:END]
        hist = r["1990":"2024"]
        ann_vol_hist = hist.groupby(hist.index.year).std() * np.sqrt(252)
        vol_ly = ly.std() * np.sqrt(252)
        eq = (1 + ly).cumprod()
        big = ly.abs().sort_values(ascending=False).head(5)
        rows.append({
            "symbol": s, "start_px": float(p[:START].iloc[-1]), "end_px": float(p[:END].iloc[-1]),
            "return": float(p[:END].iloc[-1] / p[:START].iloc[-1] - 1),
            "high": float(p[START:END].max()), "high_date": str(p[START:END].idxmax().date()),
            "low": float(p[START:END].min()), "low_date": str(p[START:END].idxmin().date()),
            "ann_vol": float(vol_ly), "vol_pctile_vs_years_1990_2024": float((ann_vol_hist < vol_ly).mean()),
            "median_year_vol_1990_2024": float(ann_vol_hist.median()),
            "max_dd": float((eq / eq.cummax() - 1).min()),
            "days_abs_gt_3pct": int((ly.abs() > 0.03).sum()), "n_days": int(len(ly)),
            "share_of_var_top10_days": float((ly ** 2).sort_values(ascending=False).head(10).sum() / (ly ** 2).sum()),
            "biggest_moves": {str(k.date()): round(float(ly[k]), 4) for k in big.index},
        })
    spr = (sp["XBRUSD"] - sp["XTIUSD"]).dropna()
    reg = {"markets": rows, "brent_wti_spread": {
        "start": float(spr[:START].iloc[-1]), "end": float(spr[:END].iloc[-1]),
        "max": float(spr[START:END].max()), "max_date": str(spr[START:END].idxmax().date()),
        "mean_2025": float(spr["2025"].mean()), "mean_ly": float(spr[START:END].mean())}}
    return reg


def character():
    """Autocorrelation of daily returns and variance ratios VR(k) = var(k-day)/(k var(1-day)).
    VR > 1 = trending, < 1 = mean-reverting."""
    sp = spot_daily()
    out = []
    for s in ["XTIUSD", "XBRUSD", "XNGUSD"]:
        p = sp[s].dropna()
        p = p[p > 0]
        lr = np.log(p).diff().dropna()
        for lab, x in [("1990-2024", lr["1990":"2024"]), ("last 12m", lr[START:END])]:
            row = {"symbol": s, "period": lab, "ac1": float(x.autocorr(1)), "ac5": float(x.autocorr(5))}
            for k in [2, 5, 10, 20]:
                kk = x.rolling(k).sum().dropna().iloc[::k]
                row[f"vr{k}"] = float(kk.var() / (k * x.var()))
            out.append(row)
    return pd.DataFrame(out)


def strategy_scores():
    fams = {}
    for k, fn in TREND_VARIANTS.items():
        fams[("trend" if k != "long_only_voltarget" else "benchmark", k)] = fn
    fams[("trend", "trend_combo+vol_overlay")] = vol_filter(trend)
    for k, fn in MR_VARIANTS.items():
        fams[("mean_reversion", k)] = fn
    fams[("benchmark", "static_short")] = lambda d: pd.Series(-1.0, index=d.index)
    rows = []
    for (fam, name), fn in fams.items():
        for lag in [1, 2]:
            t = evaluate(fn, name, data=SPOT, start=START, end=END, lag=lag,
                         buffer=None if fam == "mean_reversion" else 0.1)["table"]
            for _, r in t.iterrows():
                rows.append({"family": fam, "name": name, "lag": lag, "symbol": r["symbol"], "sharpe": r["sharpe"],
                             "total_ret": (1 + r["ann_ret"] / 252) ** (252 * r["years"]) - 1 if r["ann_ret"] == r["ann_ret"] else np.nan,
                             "cagr": r.get("cagr"), "max_dd": r["max_dd"], "ann_vol": r["ann_vol"]})
    return pd.DataFrame(rows)


def monthly_paths():
    out = {}
    for s in ["XTIUSD", "XBRUSD"]:
        d = SPOT[s]
        for lab, fn in [("trend", trend), ("trend+vol_overlay", vol_filter(trend))]:
            res = bt.run(d["ret"], positions(d, fn), s)
            x = res[START:END]
            m = x.groupby(x.index.to_period("M")).agg(net=("net", "sum"), pos=("held", "mean"))
            out[f"{s}:{lab}"] = [[str(k), round(float(v.net), 4), round(float(v.pos), 3)] for k, v in m.iterrows()]
    return out


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    R = regime()
    print(json.dumps(R, indent=1)[:3000])
    C = character()
    print("\nMarket character (VR>1 trending, <1 mean-reverting):")
    print(C.round(3).to_string(index=False))
    S = strategy_scores()
    S.to_csv(os.path.join(OUT, "e13_last_year_strategies.csv"), index=False)
    P = S[(S.symbol == "PORT") | (S.symbol.isin(["XTIUSD", "XBRUSD"]))]
    piv = P[P.lag == 1].pivot_table(index=["family", "name"], columns="symbol", values="sharpe").round(2)
    print("\nLast-12-month Sharpe (lag 1), spot data:")
    print(piv.sort_values("PORT", ascending=False).to_string())
    M = monthly_paths()
    json.dump({"regime": R, "character": C.to_dict("records"), "monthly": M}, open(os.path.join(OUT, "e13_last_year.json"), "w"),
              indent=1, default=float)
