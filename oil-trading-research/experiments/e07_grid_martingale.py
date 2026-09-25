"""E07 - Grid / martingale / averaging-down (DCA) bots on oil & gas CFDs: a risk demonstration.

Simulator: src/retail_bots.py (1:10 margin, stop-out at 50% margin level, negative-balance protection,
spread per fill, 2.5%/yr financing markup, roll yield via the futures total-return index).

  1. Headline configurations, monthly start dates, 2-year horizon: P(stop-out), P(>= 50% loss),
     median / 5th percentile / worst outcome, win rates, "smooth first year" conditioning
  2. Parameter sweeps (step, lot size, number of lots / doublings / safety orders, ladder size)
  3. Intraday stop-out robustness using Oanda CFD high/low (2005-2020) and front-month futures
  4. Episodes: 2008 H2, 2014-16, 2020 (incl. a CFD on the expiring May-2020 WTI contract),
     NG 2008-12 decline, NG 2021-22 spike and 2022-23 collapse
  5. Charts
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import warnings  # noqa: E402

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import plotstyle as ps  # noqa: E402
from src import retail_bots as rb  # noqa: E402
from src import signals as sg  # noqa: E402
from src.costs import COST_PER_SIDE, FIN_MARKUP  # noqa: E402
from src.data import futures_daily, oanda_daily, spot_daily  # noqa: E402
from src.evaluate import evaluate, get_dataset  # noqa: E402

OUT = os.path.join(ROOT, "results")
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

# P&L series: (label, futures code, CFD symbol for costs / Oanda ranges)
SERIES = {
    "WTI (Dec, CRUDE_W)": ("CRUDE_W", "XTIUSD"),
    "WTI front (CRUDE_ICE)": ("CRUDE_ICE", "XTIUSD"),
    "Brent (BRENT_W)": ("BRENT_W", "XBRUSD"),
    "NatGas (GAS_US)": ("GAS_US", "XNGUSD"),
    "NatGas front (GAS-LAST)": ("GAS-LAST", "XNGUSD"),
}
MAIN = ["WTI (Dec, CRUDE_W)", "Brent (BRENT_W)", "NatGas (GAS_US)"]
COLOR = {"WTI (Dec, CRUDE_W)": ps.SERIES[0], "Brent (BRENT_W)": ps.SERIES[1], "NatGas (GAS_US)": ps.SERIES[2],
         "WTI front (CRUDE_ICE)": ps.SERIES[0], "NatGas front (GAS-LAST)": ps.SERIES[2]}
BOT_COLOR = {"grid": ps.SERIES[0], "martingale": ps.SERIES[1], "dca": ps.SERIES[2], "grid_hedged": ps.SERIES[3]}
BOT_LABEL = {"grid": "Grid (buy every X% down, TP +X% per lot)", "martingale": "Martingale (double after a loss)",
             "dca": "DCA averaging down (TP on average price)", "grid_hedged": "Two-sided hedged grid"}
BOTS3 = ["grid", "martingale", "dca"]
HORIZON_YEARS = 2


def step_for(series_label, crude_step, ng_step):
    return ng_step if series_label.startswith("NatGas") else crude_step


# headline configurations (typical retail settings); step: crude 3%, gas 5% (~1.5 daily sigma)
HEADLINE = {
    "grid": dict(step=(0.03, 0.05), lot=0.5, nmax=8),                       # 8 lots x 0.5 = 4x when full
    "grid_hedged": dict(step=(0.03, 0.05), lot=0.5, nmax=8),                # same, both directions
    "martingale": dict(step=(0.03, 0.05), base=0.5, kmax=6),                # 0.5x doubling up to 32x (capped)
    "dca": dict(step=(0.03, 0.05), tp=0.02, vmult=1.5, mmax=6, gross=5.0),  # 7-order ladder = 5x at full
}


# ------------------------------------------------------------------------------------------------
# data
# ------------------------------------------------------------------------------------------------
def load_series(label):
    code, sym = SERIES[label]
    f = futures_daily(code)
    tri = f["tri"].copy()
    idx = tri.index
    C = tri.to_numpy(float)
    days = np.r_[1.0, np.diff(idx.values).astype("timedelta64[D]").astype(float)]
    # intraday ranges from Oanda CFD candles (2005-2020): apply session low/high/open relative to close
    L, H, O = C.copy(), C.copy(), C.copy()
    has_hl = np.zeros(len(C), dtype=bool)
    if sym in ("XTIUSD", "XNGUSD"):
        od = oanda_daily(sym)
        od = od[(od["close"] > 0)]
        rl = (od["low"] / od["close"]).reindex(idx)
        rh = (od["high"] / od["close"]).reindex(idx)
        ro = (od["open"] / od["close"]).reindex(idx)
        ok = rl.notna() & rh.notna() & ro.notna()
        # guard against bad candles (roll gaps inside a session)
        ok &= (rl > 0.6) & (rh < 1.6)
        L[ok.values] = C[ok.values] * rl[ok].values
        H[ok.values] = C[ok.values] * rh[ok].values
        O[ok.values] = C[ok.values] * ro[ok].values
        has_hl = ok.values
    return {"label": label, "idx": idx, "C": C, "L": L, "H": H, "O": O, "days": days, "has_hl": has_hl,
            "cps": COST_PER_SIDE[sym], "sym": sym}


def run_bot(bot, D, cfg, i0, i1, use_hl=False):
    step = step_for(D["label"], *cfg["step"]) if isinstance(cfg["step"], tuple) else cfg["step"]
    a = (D["C"], D["L"], D["H"], D["O"], D["days"], D["cps"], FIN_MARKUP)
    if bot in ("grid", "grid_hedged"):
        eq, ex, st, se, ntr, nwin = rb.sim_grid(*a, step, cfg["lot"], cfg["nmax"], i0, i1, use_hl,
                                                1 if bot == "grid" else 2)
        extra = {}
    elif bot == "martingale":
        eq, ex, st, se, ntr, nwin, nseq, nsw = rb.sim_martingale(*a, step, cfg["base"], cfg["kmax"], i0, i1,
                                                                 use_hl, 20)
        extra = {"n_seq": nseq, "seq_win_rate": nsw / nseq if nseq else np.nan}
    else:
        eq, ex, st, se, ntr, nwin = rb.sim_dca(*a, step, cfg["tp"], cfg["vmult"], cfg["mmax"], cfg["gross"], i0, i1,
                                               use_hl)
        extra = {}
    return eq, ex, st, se, ntr, nwin, extra


def start_indices(idx, first="1991-01-01", horizon_years=HORIZON_YEARS):
    """First trading day of each month; keep starts with a full horizon of data after them."""
    s = pd.Series(np.arange(len(idx)), index=idx)
    s = s[s.index >= first]
    firsts = s.groupby([s.index.year, s.index.month]).first()
    out = []
    for i0 in firsts.values:
        if horizon_years == 0:
            if i0 < len(idx) - 252:
                out.append((int(i0), len(idx) - 1))
            continue
        end_date = idx[i0] + pd.DateOffset(years=horizon_years)
        i1 = idx.searchsorted(end_date) - 1
        if idx[-1] >= end_date - pd.Timedelta(days=3):
            out.append((int(i0), int(i1)))
    return out


def rolling_study(bot, D, cfg, use_hl=False, first="1991-01-01", last=None, require_hl=False):
    rows = []
    for i0, i1 in start_indices(D["idx"], first):
        if last is not None and D["idx"][i0] > pd.Timestamp(last):
            continue
        if (use_hl or require_hl) and not D["has_hl"][i0:i1 + 1].mean() > 0.9:
            continue
        eq, ex, st, se, ntr, nwin, extra = run_bot(bot, D, cfg, i0, i1, use_hl)
        e = pd.Series(eq)
        dd = float((e / e.cummax() - 1).min())
        n1y = min(252, len(eq) - 1)
        rows.append({"start": D["idx"][i0], "end": D["idx"][i1], "final": eq[-1], "min_eq": np.nanmin(eq),
                     "max_dd": dd, "stopped": st >= 0,
                     "stop_date": D["idx"][st] if st >= 0 else pd.NaT,
                     "days_to_stop": (st - i0) if st >= 0 else np.nan, "n_trades": ntr,
                     "win_rate": nwin / ntr if ntr else np.nan, "eq_1y": eq[n1y],
                     "max_expo": float(np.nanmax(ex)), **extra})
    return pd.DataFrame(rows)


def summarise(df, bot, label, cfg_name):
    fin = df["final"]
    smooth = df[(df["eq_1y"] > 1.0) & (~df["stopped"] | (df["days_to_stop"] > 252))]
    return {
        "bot": bot, "series": label, "config": cfg_name, "n_starts": len(df),
        "first_start": str(df["start"].min().date()), "last_start": str(df["start"].max().date()),
        "p_stop_out": df["stopped"].mean(), "p_loss_ge_50pct": (df["min_eq"] <= 0.5).mean(),
        "p_final_loss": (fin < 1).mean(), "mean_2y_ret": fin.mean() - 1, "median_2y_ret": fin.median() - 1,
        "p05_2y_ret": fin.quantile(0.05) - 1, "worst_2y_ret": fin.min() - 1, "best_2y_ret": fin.max() - 1,
        "median_win_rate": df["win_rate"].median(), "median_trades": df["n_trades"].median(),
        "median_max_dd": df["max_dd"].median(),
        "p_stop_given_profitable_year1": (smooth["stopped"] & (smooth["days_to_stop"] > 252)).mean()
        if len(smooth) else np.nan,
        "share_profitable_year1": len(smooth) / len(df),
        "median_seq_win_rate": df["seq_win_rate"].median() if "seq_win_rate" in df else np.nan,
    }


def trend_reference():
    """Rolling 2-year outcomes of the vol-targeted multi-speed trend system (net), same start months."""
    fut = get_dataset("fut")
    res = evaluate(lambda d: sg.multi_ewmac(d["tri"], d["ret"]), "trend", data=fut, keep_series=True)
    rows = []
    for sym, lab in [("XTIUSD", "WTI (Dec, CRUDE_W)"), ("XBRUSD", "Brent (BRENT_W)"), ("XNGUSD", "NatGas (GAS_US)")]:
        r = res["nets"][sym]
        eq = (1 + r).cumprod()
        idx = eq.index
        outs = []
        for i0, i1 in start_indices(idx, "1992-01-01"):
            e = eq.iloc[i0:i1 + 1] / eq.iloc[i0 - 1] if i0 > 0 else eq.iloc[i0:i1 + 1]
            outs.append({"final": e.iloc[-1], "min_eq": e.min()})
        o = pd.DataFrame(outs)
        rows.append({"bot": "trend (15% vol, reference)", "series": lab, "config": "multi_ewmac", "n_starts": len(o),
                     "p_stop_out": 0.0, "p_loss_ge_50pct": (o["min_eq"] <= 0.5).mean(),
                     "p_final_loss": (o["final"] < 1).mean(), "mean_2y_ret": o["final"].mean() - 1,
                     "median_2y_ret": o["final"].median() - 1, "p05_2y_ret": o["final"].quantile(0.05) - 1,
                     "worst_2y_ret": o["final"].min() - 1, "best_2y_ret": o["final"].max() - 1})
    return pd.DataFrame(rows)


def first_start(D):
    """Bots need no warm-up beyond the martingale's 20-day momentum."""
    return str(max(pd.Timestamp("1991-01-01"), D["idx"][21]).date())


def cfg_name(bot, cfg, label=None):
    st = cfg["step"]
    if isinstance(st, tuple):
        st = step_for(label or "", *st)
    if bot in ("grid", "grid_hedged"):
        return f"step{st:.1%}_lot{cfg['lot']}x_n{cfg['nmax']}"
    if bot == "martingale":
        return f"step{st:.1%}_base{cfg['base']}x_k{cfg['kmax']}"
    return f"step{st:.1%}_tp{cfg['tp']:.0%}_v{cfg['vmult']}_m{cfg['mmax']}_ladder{cfg['gross']}x"


def main():
    ps.apply()
    DATA = {lab: load_series(lab) for lab in SERIES}
    for lab, D in DATA.items():
        print(f"{lab:26s} {D['idx'][0].date()} -> {D['idx'][-1].date()}  n={len(D['C'])}  "
              f"intraday ranges on {D['has_hl'].mean():.0%} of days")

    # ------------------------------------------------------------------ 1. headline rolling study
    head_rows, per_start = [], {}
    for bot, cfg in HEADLINE.items():
        for lab, D in DATA.items():
            first = first_start(D)
            df = rolling_study(bot, D, cfg, first=first)
            per_start[(bot, lab)] = df
            head_rows.append(summarise(df, bot, lab, cfg_name(bot, cfg, lab)))
    head = pd.DataFrame(head_rows)
    ref = trend_reference()
    head = pd.concat([head, ref], ignore_index=True)
    head.to_csv(os.path.join(OUT, "e07_headline_ruin_stats.csv"), index=False)
    ps_all = pd.concat([d.assign(bot=b, series=l) for (b, l), d in per_start.items()], ignore_index=True)
    ps_all.to_csv(os.path.join(OUT, "e07_per_start_outcomes.csv"), index=False)
    cols = ["bot", "series", "config", "n_starts", "p_stop_out", "p_loss_ge_50pct", "p_final_loss", "mean_2y_ret",
            "median_2y_ret", "p05_2y_ret", "worst_2y_ret", "median_win_rate", "median_seq_win_rate",
            "share_profitable_year1", "p_stop_given_profitable_year1"]
    print("\n=== headline: monthly starts, 2-year horizon")
    print(head[cols].round(3).to_string(index=False))

    # ------------------------------------------------------------------ 2. parameter sweeps
    sweep_rows = []
    steps = [0.015, 0.03, 0.05, 0.08]
    for lab in MAIN + ["WTI front (CRUDE_ICE)", "NatGas front (GAS-LAST)"]:
        D = DATA[lab]
        first = first_start(D)
        for st in steps:
            for lot in [0.25, 0.5, 1.0]:
                for nmax in [5, 10]:
                    cfg = dict(step=st, lot=lot, nmax=nmax)
                    for gb in ["grid", "grid_hedged"]:
                        s = summarise(rolling_study(gb, D, cfg, first=first), gb, lab, cfg_name(gb, cfg))
                        s.update({"step": st, "size": lot, "depth": nmax, "full_exposure_x": lot * nmax})
                        sweep_rows.append(s)
            for base in [0.25, 0.5, 1.0]:
                for kmax in [4, 8]:
                    cfg = dict(step=st, base=base, kmax=kmax)
                    s = summarise(rolling_study("martingale", D, cfg, first=first), "martingale", lab,
                                  cfg_name("martingale", cfg))
                    s.update({"step": st, "size": base, "depth": kmax,
                              "full_exposure_x": min(base * 2 ** kmax, 9.0)})
                    sweep_rows.append(s)
            for vm in [1.0, 1.5, 2.0]:
                for gross in [3.0, 6.0]:
                    cfg = dict(step=st, tp=0.02, vmult=vm, mmax=6, gross=gross)
                    s = summarise(rolling_study("dca", D, cfg, first=first), "dca", lab, cfg_name("dca", cfg))
                    s.update({"step": st, "size": vm, "depth": 6, "full_exposure_x": gross})
                    sweep_rows.append(s)
    sweep = pd.DataFrame(sweep_rows)
    sweep.to_csv(os.path.join(OUT, "e07_parameter_sweep.csv"), index=False)
    print("\n=== sweep: share of configs with P(>=50% loss) above 10% / 25%, by bot and series")
    g = sweep.groupby(["bot", "series"]).agg(n_cfg=("config", "size"),
                                             share_p50_gt10=("p_loss_ge_50pct", lambda x: (x > 0.10).mean()),
                                             share_p50_gt25=("p_loss_ge_50pct", lambda x: (x > 0.25).mean()),
                                             min_p50=("p_loss_ge_50pct", "min"), max_p50=("p_loss_ge_50pct", "max"),
                                             best_median_ret=("median_2y_ret", "max"),
                                             best_mean_ret=("mean_2y_ret", "max"))
    print(g.round(3).to_string())
    # configs with low ruin: what do they earn?
    safe = sweep[sweep["p_loss_ge_50pct"] <= 0.02]
    print("\nconfigs with P(>=50% loss) <= 2%: median 2y return distribution by bot")
    print(safe.groupby("bot")["median_2y_ret"].describe().round(3).to_string())

    # ------------------------------------------------------------------ 3. intraday stop-outs (Oanda ranges)
    hl_rows = []
    for bot, cfg in HEADLINE.items():
        for lab in ["WTI (Dec, CRUDE_W)", "WTI front (CRUDE_ICE)", "NatGas (GAS_US)", "NatGas front (GAS-LAST)"]:
            D = DATA[lab]
            first = max(pd.Timestamp("2005-01-03"), D["idx"][260])
            for use_hl in [False, True]:
                # same start dates for both runs (windows fully covered by Oanda candles)
                df = rolling_study(bot, D, cfg, use_hl=use_hl, first=str(first.date()), last="2018-05-01",
                                   require_hl=True)
                s = summarise(df, bot, lab, cfg_name(bot, cfg, lab))
                s["intraday_stop_check"] = use_hl
                hl_rows.append(s)
    hl = pd.DataFrame(hl_rows)
    hl.to_csv(os.path.join(OUT, "e07_intraday_stopout_check.csv"), index=False)
    print("\n=== intraday (Oanda high/low) vs close-only stop-out checks, starts 2005-2018")
    print(hl[["bot", "series", "intraday_stop_check", "n_starts", "p_stop_out", "p_loss_ge_50pct",
              "median_2y_ret", "worst_2y_ret"]].round(3).to_string(index=False))

    # ------------------------------------------------------------------ 4. episodes
    episodes = [
        ("2008 H2 crash (WTI front)", "WTI front (CRUDE_ICE)", "2007-07-02", "2009-06-30"),
        ("2014-16 collapse (WTI front)", "WTI front (CRUDE_ICE)", "2013-07-01", "2016-06-30"),
        ("2020 COVID (WTI front)", "WTI front (CRUDE_ICE)", "2019-01-02", "2020-12-31"),
        ("NG 2008-12 decline", "NatGas (GAS_US)", "2007-07-02", "2012-06-29"),
        ("NG 2021-22 spike + 2023 collapse", "NatGas (GAS_US)", "2020-07-01", "2023-06-30"),
    ]
    ep_rows, ep_series = [], {}
    for name, lab, a, b in episodes:
        D = DATA[lab]
        i0 = int(D["idx"].searchsorted(pd.Timestamp(a)))
        i1 = int(D["idx"].searchsorted(pd.Timestamp(b), side="right") - 1)
        px = pd.Series(D["C"][i0:i1 + 1] / D["C"][i0], index=D["idx"][i0:i1 + 1])
        ep_series[name] = {"price": px}
        for bot, cfg in HEADLINE.items():
            eq, ex, st, se, ntr, nwin, extra = run_bot(bot, D, cfg, i0, i1)
            e = pd.Series(eq, index=D["idx"][i0:i1 + 1])
            ep_series[name][bot] = (e, D["idx"][st] if st >= 0 else None)
            # first-stage stats: until the peak equity before the stop-out
            peak_eq = e.iloc[:(st - i0) if st >= 0 else len(e)].max()
            ep_rows.append({"episode": name, "series": lab, "bot": bot, "config": cfg_name(bot, cfg, lab),
                            "start": a, "end": b, "price_change": px.iloc[-1] - 1, "price_min": px.min() - 1,
                            "peak_equity": peak_eq, "final_equity": e.iloc[-1], "stopped_out": st >= 0,
                            "stop_date": str(D["idx"][st].date()) if st >= 0 else "",
                            "closed_trades": ntr, "win_rate": nwin / ntr if ntr else np.nan, **extra})
    # a CFD referencing the expiring May-2020 WTI contract (EIA Cushing spot, which printed -36.98)
    sp = spot_daily()["XTIUSD"].dropna()
    sp = sp[(sp.index >= "2020-01-02") & (sp.index <= "2020-06-30")]
    Cs = sp.to_numpy(float)
    dys = np.r_[1.0, np.diff(sp.index.values).astype("timedelta64[D]").astype(float)]
    Ds = {"label": "WTI spot (May-20 contract to expiry)", "idx": sp.index, "C": Cs, "L": Cs, "H": Cs, "O": Cs,
          "days": dys, "cps": COST_PER_SIDE["XTIUSD"], "sym": "XTIUSD"}
    ep_series["Negative WTI: CFD on expiring front month"] = {"price": pd.Series(Cs / Cs[0], index=sp.index)}
    for bot, cfg in HEADLINE.items():
        eq, ex, st, se, ntr, nwin, extra = run_bot(bot, Ds, cfg, 0, len(Cs) - 1)
        e = pd.Series(eq, index=sp.index)
        ep_series["Negative WTI: CFD on expiring front month"][bot] = (e, sp.index[st] if st >= 0 else None)
        ep_rows.append({"episode": "Negative WTI (EIA spot path, Jan-Jun 2020)", "series": Ds["label"], "bot": bot,
                        "config": cfg_name(bot, cfg, "WTI"), "start": "2020-01-02", "end": "2020-06-30",
                        "price_change": Cs[-1] / Cs[0] - 1, "price_min": Cs.min() / Cs[0] - 1,
                        "peak_equity": e.max(), "final_equity": e.iloc[-1], "stopped_out": st >= 0,
                        "stop_date": str(sp.index[st].date()) if st >= 0 else "", "closed_trades": ntr,
                        "win_rate": nwin / ntr if ntr else np.nan, **extra})
    ep = pd.DataFrame(ep_rows)
    ep.to_csv(os.path.join(OUT, "e07_episodes.csv"), index=False)
    print("\n=== episodes (headline configs)")
    print(ep[["episode", "bot", "price_change", "price_min", "peak_equity", "final_equity", "stopped_out",
              "stop_date", "closed_trades", "win_rate"]].round(3).to_string(index=False))

    # ------------------------------------------------------------------ 5. typical pattern: open-ended runs
    # start every month and run until stop-out or end of data; report survival and the "track record"
    # a vendor could show before the blow-up; illustrate with the longest-surviving run per bot
    long_rows, long_series, surv_rows = [], {}, []
    for bot in BOTS3 + ["grid_hedged"]:
        best = None
        for lab in MAIN:
            D = DATA[lab]
            for i0, _ in start_indices(D["idx"], first_start(D), horizon_years=0):
                eq, ex, st, se, ntr, nwin, extra = run_bot(bot, D, HEADLINE[bot], i0, len(D["C"]) - 1)
                below = np.where(eq <= 0.5)[0]
                ruin_rel = below[0] if len(below) else -1          # first close with >= 50% loss
                if st >= 0 and (ruin_rel < 0 or st - i0 < ruin_rel):
                    ruin_rel = st - i0
                ruined = ruin_rel >= 0
                life = ruin_rel if ruined else (len(D["C"]) - 1 - i0)
                pre = eq[: ruin_rel if ruined and ruin_rel > 0 else (1 if ruined else len(eq))]
                surv_rows.append({"bot": bot, "series": lab, "start": D["idx"][i0], "ruined": ruined,
                                  "stopped_out": st >= 0, "years_to_ruin": life / 252 if ruined else np.nan,
                                  "years_observed": life / 252, "peak_equity_before_ruin": np.nanmax(pre),
                                  "closed_trades": ntr, "win_rate": nwin / ntr if ntr else np.nan})
                if ruined and (best is None or life > best[0]):
                    best = (life, lab, i0, i0 + ruin_rel, ntr, nwin)
        life, lab, i0, st, ntr, nwin = best
        D = DATA[lab]
        eq, *_ = run_bot(bot, D, HEADLINE[bot], i0, len(D["C"]) - 1)
        e = pd.Series(eq, index=D["idx"][i0:])
        e = e[e.index <= D["idx"][min(st + 60, len(D["C"]) - 1)]]
        long_series[bot] = (lab, e, st)
        long_rows.append({"bot": bot, "series": lab, "start": str(D["idx"][i0].date()),
                          "ruin_date": str(D["idx"][st].date()), "years_survived": life / 252,
                          "peak_equity": float(e.max()), "closed_trades": ntr,
                          "win_rate": nwin / ntr if ntr else np.nan, "equity_after_stop": float(e.iloc[-1])})
    lr = pd.DataFrame(long_rows)
    lr.to_csv(os.path.join(OUT, "e07_longest_survivors.csv"), index=False)
    surv = pd.DataFrame(surv_rows)
    surv.to_csv(os.path.join(OUT, "e07_open_ended_survival.csv"), index=False)
    ss = surv.groupby(["bot", "series"]).agg(n=("ruined", "size"), share_ruined=("ruined", "mean"),
                                             share_stopped_out=("stopped_out", "mean"),
                                             median_years_to_ruin=("years_to_ruin", "median"),
                                             p90_years_to_ruin=("years_to_ruin", lambda x: x.quantile(0.9)),
                                             median_peak_before_ruin=("peak_equity_before_ruin", "median"),
                                             median_win_rate=("win_rate", "median"))
    ss.to_csv(os.path.join(OUT, "e07_open_ended_survival_summary.csv"))
    print("\n=== open-ended runs (start every month, run until stop-out or data end)\n", ss.round(3).to_string())
    print("\n=== longest-surviving run per bot (illustration)\n", lr.round(3).to_string(index=False))

    charts(DATA, head, per_start, sweep, ep_series, long_series, ep)


# ================================================================================================
def charts(DATA, head, per_start, sweep, ep_series, long_series, ep):
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    # 1. episodes: price (top) and equity of the three bots (bottom) per episode
    names = list(ep_series.keys())
    fig, axes = plt.subplots(2, len(names), figsize=(4.0 * len(names), 6.2), sharex="col",
                             gridspec_kw={"height_ratios": [1, 1.4]})
    for j, nm in enumerate(names):
        d = ep_series[nm]
        ax = axes[0, j]
        ax.plot(d["price"].index, d["price"].values, color=ps.INK2, lw=1.1)
        ax.axhline(1.0, color=ps.AXIS, lw=0.7)
        ax.set_title(nm, fontsize=9.5)
        if j == 0:
            ax.set_ylabel("price, start = 1")
        ax2 = axes[1, j]
        for bot in ["grid", "martingale", "dca"]:
            e, sd = d[bot]
            ax2.plot(e.index, e.values, color=BOT_COLOR[bot], lw=1.2, label=BOT_LABEL[bot])
            if sd is not None:
                ax2.scatter([sd], [e.loc[sd]], s=40, color=ps.CRITICAL, zorder=4, edgecolor=ps.SURFACE,
                            linewidth=1.5)
        ax2.axhline(1.0, color=ps.AXIS, lw=0.7)
        ax2.set_ylim(-0.05, max(1.6, max(float(d[b][0].max()) for b in ["grid", "martingale", "dca"]) * 1.05))
        if j == 0:
            ax2.set_ylabel("account equity, start = 1")
        ax2.xaxis.set_major_locator(mdates.YearLocator())
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axes[1, 0].legend(loc="lower left", fontsize=7.5)
    ps.title(fig, "The same story in every crash: steady gains, then a margin stop-out", y=1.05)
    ps.subtitle(fig, "Headline settings, 1:10 leverage, stop-out at 50% margin level (red dot). Price = futures "
                     "total-return index (incl. roll yield). Last panel: CFD tracking the expiring May-2020 contract.",
                y=1.0)
    fig.tight_layout()
    ps.save(fig, os.path.join(OUT, "e07_episodes.png"))

    # 2. outcome by start month (2-year final equity), per bot, main series
    fig, axes = plt.subplots(3, 1, figsize=(11.5, 8.4), sharex=True)
    for ax, bot in zip(axes, ["grid", "martingale", "dca"]):
        for lab in MAIN:
            df = per_start[(bot, lab)]
            ok = ~df["stopped"]
            ax.scatter(df.loc[ok, "start"], df.loc[ok, "final"], s=9, color=COLOR[lab], label=lab, alpha=0.85,
                       linewidths=0)
            ax.scatter(df.loc[~ok, "start"], df.loc[~ok, "final"], s=16, color=COLOR[lab], marker="x",
                       linewidths=1.1)
        ax.axhline(1.0, color=ps.AXIS, lw=0.8)
        ax.axhline(0.5, color=ps.CRITICAL, lw=0.7)
        r = head[(head.bot == bot) & head.series.isin(MAIN)]
        txt = "  ".join(f"{l.split(' ')[0]}: stop-out {p:.0%}" for l, p in zip(r.series, r.p_stop_out))
        ax.set_title(f"{BOT_LABEL[bot]}  ({txt})", fontsize=10)
        ax.set_ylabel("equity after 2 years")
        ax.set_ylim(-0.05, 2.6)
    axes[0].legend(loc="upper left", ncol=3, fontsize=8, markerscale=1.8)
    axes[-1].xaxis.set_major_locator(mdates.YearLocator(4))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ps.title(fig, "Start a new account every month and run it for two years", y=1.03)
    ps.subtitle(fig, "Each dot = one 2-year run (x = start month). Crosses = stopped out by the broker. "
                     "Red line = half the account lost.", y=1.0)
    fig.tight_layout()
    ps.save(fig, os.path.join(OUT, "e07_outcomes_by_start.png"))

    # 3. sweep: ruin probability vs median 2y return, all configs, main series
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.4), sharey=True)
    for ax, bot in zip(axes, ["grid", "martingale", "dca"]):
        sub = sweep[(sweep.bot == bot) & sweep.series.isin(MAIN)]
        for lab in MAIN:
            x = sub[sub.series == lab]
            ax.scatter(x["median_2y_ret"] * 100, x["p_loss_ge_50pct"] * 100, s=22, color=COLOR[lab], label=lab,
                       edgecolor=ps.SURFACE, linewidth=0.8)
        ax.axvline(0, color=ps.AXIS, lw=0.8)
        ax.set_title(BOT_LABEL[bot], fontsize=10.5)
        ax.set_xlabel("median 2-year return, %")
    axes[0].set_ylabel("P(losing >= 50% of the account within 2 years), %")
    axes[0].legend(loc="upper left", fontsize=8)
    ps.title(fig, "No setting buys a decent median return without a large chance of losing half the account",
             y=1.07)
    ps.subtitle(fig, "Each dot = one parameter set (step 1.5-8%, lot / base / ladder size, depth), monthly starts "
                     "1991-2022.", y=1.0)
    ps.save(fig, os.path.join(OUT, "e07_sweep_ruin_vs_return.png"))

    # 4. typical pattern: longest-surviving open-ended run per bot
    fig, axes = plt.subplots(len(long_series), 1, figsize=(11, 8.0))
    for ax, (bot, (lab, e, st)) in zip(axes, long_series.items()):
        e = e.dropna()
        ax.plot(e.index, e.values, color=BOT_COLOR[bot], lw=1.3)
        ax.axhline(1.0, color=ps.AXIS, lw=0.7)
        sd = DATA[lab]["idx"][st]
        ax.scatter([sd], [e.loc[sd]], s=40, color=ps.CRITICAL, zorder=4, edgecolor=ps.SURFACE, linewidth=1.5)
        ax.annotate(f"ruin {sd.date()}: equity {e.loc[sd]:.2f}", (sd, e.loc[sd]), textcoords="offset points",
                    xytext=(-10, 10), ha="right", fontsize=8, color=ps.INK2)
        ax.set_title(f"{BOT_LABEL[bot]} on {lab}: longest survivor of all monthly starts", fontsize=10)
        ax.set_ylabel("equity")
    ps.title(fig, "High win rate, smooth equity, then ruin", y=1.03)
    ps.subtitle(fig, "Headline settings. Each bot's best-case history: the start month that survived longest "
                     "before ruin (stop-out or half the account lost, red dot).", y=1.0)
    fig.tight_layout()
    ps.save(fig, os.path.join(OUT, "e07_typical_pattern.png"))


if __name__ == "__main__":
    main()
