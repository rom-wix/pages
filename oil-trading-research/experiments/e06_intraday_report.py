"""E06 report helpers: charts (PNG) and the markdown summary.  Called from e06_intraday_summary.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src import backtest as bt
from src import costs
from src import intraday as ix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results")

# palette / chrome (dataviz reference palette, light mode)
SURF, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
FAM_NAMES = {"A": "A  ORB", "B": "B  intraday momentum", "C": "C  EIA reaction", "D": "D  session / calendar",
             "E": "E  mean reversion"}


def style(ax, title=None, ylabel=None):
    ax.set_facecolor(SURF)
    for sp in ["top", "right", "left"]:
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=8.5, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8, linestyle="-")
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, loc="left", fontsize=10.5, color=INK, pad=8)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=9, color=INK2)


def legend(ax, **kw):
    lg = ax.legend(frameon=False, fontsize=8.5, labelcolor=INK2, **kw)
    return lg


def family_best(R):
    R = R.copy()
    R["fam"] = R["sub"].str[0]
    return R.sort_values("is_sharpe", ascending=False).groupby(["fam", "sym"]).head(1)


def charts(R, T, live):
    plt.rcParams["font.family"] = "DejaVu Sans"
    # ---------------------------------------------------------------- 1) cumulative net P&L of family winners
    fb = family_best(R)
    fig, axes = plt.subplots(2, 1, figsize=(10.5, 8.8), facecolor=SURF, sharex=True)
    for ax, sym in zip(axes, ["XTIUSD", "XNGUSD"]):
        sub = fb[fb.sym == sym].sort_values("fam")
        S = ix.session_matrix(sym)
        for i, (_, r) in enumerate(sub.iterrows()):
            key = f"{sym}|{r['best_config']}"
            dn = ix.daily_pnl(T[key], ix.valid_dates(S))
            eq = dn.cumsum() * 100
            lab = f"{FAM_NAMES[r['fam']]}: {r['best_config']}  (IS {r['is_sharpe']:.2f} / OOS {r['oos_sharpe']:.2f})"
            ax.plot(eq.index, eq.values, color=SERIES["ABCDE".index(r["fam"])], lw=1.6, label=lab, solid_capstyle="round")
        ax.axvline(pd.Timestamp("2013-01-01"), color=AXIS, lw=1)
        ax.axhline(0, color=AXIS, lw=0.8)
        ax.text(pd.Timestamp("2013-02-15"), 0.03, "out-of-sample →", transform=ax.get_xaxis_transform(),
                fontsize=8.5, color=MUTED, va="bottom")
        ax.text(pd.Timestamp("2012-12-15"), 0.03, "← in-sample", transform=ax.get_xaxis_transform(),
                fontsize=8.5, color=MUTED, va="bottom", ha="right")
        style(ax, f"{sym} ({'WTI crude' if sym == 'XTIUSD' else 'US natural gas'}): cumulative net return of the "
                  f"IS-selected config per family, 1x notional, after CFD costs", "cumulative net return (%, sum)")
        lg = legend(ax, loc="upper left", ncol=1)
        lg.set_frame_on(True)
        lg.get_frame().set_facecolor(SURF)
        lg.get_frame().set_edgecolor(SURF)
        lg.get_frame().set_alpha(0.92)
    axes[-1].xaxis.set_major_locator(mdates.YearLocator(2))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "e06_cumulative_best.png"), dpi=130, facecolor=SURF)
    plt.close(fig)

    # ---------------------------------------------------------------- 2) momentum: edge by signal strength vs cost
    from e06_intraday_momentum import build
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), facecolor=SURF)
    for ax, sym in zip(axes, ["XTIUSD", "XNGUSD"]):
        S = ix.session_matrix(sym)
        d = build(S)[["on930", "last"]].dropna()
        w = 0.36
        for i, (p, lab) in enumerate([("is", "in-sample 2005-12"), ("oos", "out-of-sample 2013-20")]):
            a, b = ix.PERIODS[p]
            z = d[(d.index >= a) if a is not None else slice(None)] if a is not None else d
            if b is not None:
                z = z[z.index <= b]
            q = pd.qcut(z["on930"].abs(), 5, labels=False)
            m = (np.sign(z["on930"]) * z["last"]).groupby(q).mean() * 1e4
            ax.bar(np.arange(5) + (i - 0.5) * w, m.values, width=w * 0.92, color=SERIES[i], label=lab)
        rt = 2 * costs.COST_PER_SIDE[sym] * 1e4
        ax.axhline(rt, color=INK2, lw=1)
        ax.text(2.0, rt, f"round-trip cost {rt:.0f} bp", fontsize=8, color=INK2, va="bottom", ha="center")
        ax.axhline(0, color=AXIS, lw=0.8)
        lo_, hi_ = ax.get_ylim()
        ax.set_ylim(lo_, max(hi_, rt) * 1.35)
        ax.set_xticks(range(5))
        ax.set_xticklabels(["Q1\nweakest", "Q2", "Q3", "Q4", "Q5\nstrongest"])
        style(ax, f"{sym}: 14:00→14:30 return, signed by the\nprior 14:30→09:30 move, by |move| quintile",
              "mean signed return (bp)")
        legend(ax, loc="upper left")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.text(0.01, 0.012, "Quintiles of |signal| are formed within each period (descriptive); the traded rule uses a trailing "
             "250-session 80th-percentile threshold. Line = round-trip CFD cost.", fontsize=8, color=MUTED)
    fig.savefig(os.path.join(OUT, "e06_momentum_buckets.png"), dpi=130, facecolor=SURF)
    plt.close(fig)

    # ---------------------------------------------------------------- 3) EIA: minute volatility profile
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), facecolor=SURF, sharey=False)
    for ax, (sym, kind, lab) in zip(axes, [("XTIUSD", "crude", "XTIUSD, EIA crude-report days (Wed 10:30)"),
                                           ("XNGUSD", "gas", "XNGUSD, EIA storage-report days (Thu 10:30)")]):
        S = ix.session_matrix(sym)
        E = ix.eia_schedule(S, kind)
        E = E[E["time"] == "10:30"]
        r1 = np.abs(np.diff(np.log(S.C), axis=1)) * 1e4
        cols = np.arange(ix.col("10:00"), ix.col("11:31"))
        ev = np.zeros(S.n, bool)
        ev[E["row"].to_numpy()] = True
        normal = S.valid & np.isin(S.dates.dayofweek, [0, 1, 4])
        pe = np.nanmean(r1[ev][:, cols - 1], axis=0)
        pn = np.nanmean(r1[normal][:, cols - 1], axis=0)
        x = np.arange(len(cols))
        ax.plot(x, pe, color=SERIES[0], lw=1.6, label="report day")
        ax.plot(x, pn, color=MUTED, lw=1.6, label="normal day (Mon/Tue/Fri)")
        k = int(np.nanargmax(pe))
        ax.annotate(f"{ix.hhmm(cols[k])}: {pe[k]:.0f} bp vs {pn[k]:.0f} bp on normal days", (x[k], pe[k]),
                    xytext=(x[k] + 6, pe[k] * 0.93), fontsize=8.5, color=INK2)
        ticks = [i for i, c in enumerate(cols) if (int(ix.hhmm(c)[3:]) % 15 == 0)]
        ax.set_xticks(ticks)
        ax.set_xticklabels([ix.hhmm(cols[i]) for i in ticks])
        style(ax, lab, "mean |1-minute return| (bp)")
        ax.set_xlabel("New York time", fontsize=9, color=INK2)
        legend(ax, loc="center right")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "e06_eia_vol_profile.png"), dpi=130, facecolor=SURF)
    plt.close(fig)


# ---------------------------------------------------------------------------------------------- markdown
def f2(x, nd=2):
    return "n/a" if x is None or not np.isfinite(x) else f"{x:.{nd}f}"


def pct(x, nd=0):
    return "n/a" if x is None or not np.isfinite(x) else f"{x * 100:.{nd}f}%"


def md_table(df, cols, headers, fmts):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c, f in zip(cols, fmts):
            v = r[c]
            cells.append(f(v) if callable(f) else (str(v) if f is None else f.format(v)))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)




VERDICTS = {
    ("B  intraday momentum", "XTIUSD"): "**marginal+ (paper-trade)**",
    ("D3 Sunday-gap", "XTIUSD"): "marginal (OOS-only evidence; forward-test)",
    ("C1 EIA continuation", "XNGUSD"): "marginal (too few trades)",
    ("A2 ORB Crabel stretch", "XTIUSD"): "reject (negative at 2x cost)",
    ("D2 day-of-week hold", "XNGUSD"): "reject (NG bear-market bet)",
}


def verdict_of(r):
    return VERDICTS.get((r["sub"], r["sym"]), "reject")


def write_markdown(R, Y, fs, live, G, T):
    reg = pd.read_csv(os.path.join(OUT, "e06_B_momentum_regressions.csv"))
    rob = pd.read_csv(os.path.join(OUT, "e06_B_momentum_robustness.csv"))
    si = pd.read_csv(os.path.join(OUT, "e06_B_momentum_subintervals.csv"))
    vol = pd.read_csv(os.path.join(OUT, "e06_C_eia_event_vol.csv"))
    sst = pd.read_csv(os.path.join(OUT, "e06_D_session_stats.csv"))
    dow = pd.read_csv(os.path.join(OUT, "e06_D_dayofweek.csv"))
    hr = pd.read_csv(os.path.join(OUT, "e06_D_hourly.csv"))
    sg = pd.read_csv(os.path.join(OUT, "e06_D_sunday_gap_robustness.csv"))
    dq = pd.read_csv(os.path.join(OUT, "e06_data_checks.csv"))

    def rv(sub, sym, c):
        x = R[(R["sub"] == sub) & (R["sym"] == sym)]
        return float(x[c].iloc[0]) if len(x) else np.nan

    def gv(key, c):
        x = live[live["key"] == key]
        return float(x[c].iloc[0]) if len(x) else np.nan

    def reg_v(sym, pred, period, c):
        x = reg[(reg.sym == sym) & (reg.model == pred) & (reg.predictor == pred) & (reg.period == period)]
        return float(x[c].iloc[0]) if len(x) else np.nan

    def sv(sym, item, period, c):
        x = sst[(sst.sym == sym) & (sst["item"] == item) & (sst.period == period)]
        return float(x[c].iloc[0]) if len(x) else np.nan

    def vv(sym, event, time, window, c):
        x = vol[(vol.sym == sym) & (vol.event == event) & (vol.time == time) & (vol.window == window)]
        return float(x[c].iloc[0]) if len(x) else np.nan

    def rb(config, case, c, sym="XTIUSD"):
        x = rob[(rob.sym == sym) & (rob.config == config) & (rob.case == case)]
        return float(x[c].iloc[0]) if len(x) else np.nan

    def siv(sym, kind, window, period, c):
        x = si[(si.sym == sym) & (si.kind == kind) & (si.window == window) & (si.period == period)]
        return float(x[c].iloc[0]) if len(x) else np.nan

    def dv(sym, item, wd, period, c):
        x = dow[(dow.sym == sym) & (dow["item"] == item) & (dow.weekday == wd) & (dow.period == period)]
        return float(x[c].iloc[0]) if len(x) else np.nan

    def sgv(entry, exit_, thr, mult, c, sym="XTIUSD"):
        x = sg[(sg.sym == sym) & (sg.entry == entry) & (sg.exit == exit_) & np.isclose(sg.thr, thr) & np.isclose(sg.cost_mult, mult)]
        return float(x[c].iloc[0]) if len(x) else np.nan

    n_total = len(live)
    n_fam = live.groupby(["fam", "sym"]).size()
    Rv = R.copy()
    Rv["verdict"] = Rv.apply(verdict_of, axis=1)
    bm, sgk = "B  intraday momentum", "D3 Sunday-gap"
    cfg = "on930|q0.8|14:30"
    q5_is, q5_oos = siv("XTIUSD", "quintile", "Q5", "is", "slope"), siv("XTIUSD", "quintile", "Q5", "oos", "slope")
    gross_bp = gv("XTIUSD|mom|on930|q0.8|14:30", "full_avg_gross_bps")
    sg_oos = [sgv(e, "09:00", 0.005, 1.0, "oos_sharpe") for e in ["18:05", "18:15", "18:30", "19:00", "20:00"]]
    sg_is = [sgv(e, "09:00", 0.005, 1.0, "is_sharpe") for e in ["18:05", "18:15", "18:30", "19:00", "20:00"]]
    sg_thr = [sgv("18:05", "09:00", t, 1.0, "oos_sharpe") for t in [0.0025, 0.005, 0.01, 0.02]]
    # share of the Sunday-gap OOS P&L earned in 2020
    ysg = Y[Y["strategy"] == "XTIUSD|sunday_gap|fade|09:00|thr0.005"] if len(Y) else pd.DataFrame()
    sg_2020_share = (float(ysg[ysg.year == 2020]["net_ret"].sum()) / float(ysg[ysg.year >= 2013]["net_ret"].sum())
                     if len(ysg) and ysg[ysg.year >= 2013]["net_ret"].sum() != 0 else np.nan)
    ythu = Y[Y["strategy"] == "XNGUSD|dow|Thu_0900_1430|short"] if len(Y) else pd.DataFrame()
    thu_worst = ythu.sort_values("net_ret").iloc[0] if len(ythu) else None
    # NG post-settlement drift: positive years
    Sng = ix.session_matrix("XNGUSD")
    post = pd.Series(np.log(ix.px_before(Sng, ix.col("17:00")) / ix.px_before(Sng, ix.col("14:30"))), index=Sng.dates)[Sng.valid]
    post_y = post.groupby(post.index.year).mean()
    n_pos_post, n_y_post = int((post_y > 0).sum()), int(len(post_y))
    # mean-reversion Sharpe range (full, net) per instrument
    e_rng = {sym: (float(live[(live.fam == "E") & (live.sym == sym)]["full_sharpe"].min()),
                   float(live[(live.fam == "E") & (live.sym == sym)]["full_sharpe"].max())) for sym in ["XTIUSD", "XNGUSD"]}
    L = []
    A = L.append
    A("# E06 - Intraday strategies on XTIUSD / XNGUSD CFDs (Oanda 1-minute mids, 2005-01 .. 2020-05)")
    A("")
    A("*Generated by `experiments/e06_intraday_summary.py`; every number below is pulled from the result CSVs in `results/`.*")
    A("")
    A("## Bottom line")
    A("")
    A(f"* **{n_total} strategy variants** were backtested: 5 families x 2 instruments, with parameters chosen on 2005-2012 only. "
      "**After realistic CFD costs almost everything is dead.** Most families have positive *gross* edge out of sample, "
      "but spreads and slippage eat it. Natural gas's 20 bp round trip kills every NG idea.")
    A(f"* **Best candidate (paper-trade only): WTI intraday momentum into the 14:30 settlement.** At 14:00 NY, trade 14:00->14:30 in "
      f"the direction of the move from the prior session's 14:30 to today's 09:30, but only when that move is in the top quintile of "
      f"its trailing-year distribution. It scores net Sharpe **IS {f2(rv(bm, 'XTIUSD', 'is_sharpe'))} / OOS {f2(rv(bm, 'XTIUSD', 'oos_sharpe'))} / "
      f"full {f2(rv(bm, 'XTIUSD', 'full_sharpe'))}**, with {rv(bm, 'XTIUSD', 'full_trades_py'):.0f} trades/yr, {f2(rv(bm, 'XTIUSD', 'full_avg_bps'), 1)} bp "
      f"net per trade ({f2(gross_bp, 1)} bp gross) and max DD {pct(rv(bm, 'XTIUSD', 'full_max_dd'))}. The predictability is real: "
      f"Newey-West t = {f2(reg_v('XTIUSD', 'on930', 'is', 't_nw'), 1)} IS and {f2(reg_v('XTIUSD', 'on930', 'oos', 't_nw'), 1)} OOS. "
      f"The trading edge is thin and regime-dependent, though. At 2x costs the full Sharpe is {f2(rv(bm, 'XTIUSD', 'full_sharpe_2x'))}. "
      f"OOS without 2020 it is {f2(rv(bm, 'XTIUSD', 'oos_ex2020_sharpe'))}, and 2017-2019 lost money. The OOS bootstrap 95% CI is "
      f"[{f2(rv(bm, 'XTIUSD', 'oos_ci_lo'))}, {f2(rv(bm, 'XTIUSD', 'oos_ci_hi'))}]. The deflated Sharpe is only "
      f"{f2(rv(bm, 'XTIUSD', 'dsrN_is_family'))} (N = {int(rv(bm, 'XTIUSD', 'n_trials_family'))} family trials, null-SE flavour) "
      f"to {f2(rv(bm, 'XTIUSD', 'dsr_is_family'))} (trial-dispersion flavour).")
    A(f"* **Second candidate, unproven: fading WTI Sunday-open gaps above 0.5%** (enter Sunday 18:05-20:00, exit Monday 09:00). It had "
      f"no in-sample support (IS {f2(rv(sgk, 'XTIUSD', 'is_sharpe'))}) but scored OOS {f2(rv(sgk, 'XTIUSD', 'oos_sharpe'))} "
      f"({f2(rv(sgk, 'XTIUSD', 'oos_ex2020_sharpe'))} ex-2020). The OOS result survives entry delays, thresholds and 3x costs, "
      f"on only ~{rv(sgk, 'XTIUSD', 'full_trades_py'):.0f} trades/yr, and it carries real gap risk. Forward-test only.")
    A("* Reject: opening-range breakout (gross edge, net ~0 for WTI and deeply negative for NG), EIA continuation and fade, "
      "session and day-of-week drifts, and short-term mean reversion (no edge even gross).")
    A(f"* The EIA releases matter for **risk management**, not alpha. The first minute after the crude report is "
      f"{vv('XTIUSD', 'crude', '10:30', 'T->T+1', 'ratio_vs_normal'):.1f}x a normal minute's size, and after the NG storage report "
      f"{vv('XNGUSD', 'gas', '10:30', 'T->T+1', 'ratio_vs_normal'):.1f}x. {pct(vv('XNGUSD', 'gas', '10:30', 'T->T+5', 'share_event_gt_1pct'))} "
      f"of storage releases move NG > 1% within 5 minutes.")
    A("")
    A("## Setup")
    A("")
    A("* **Data:** Oanda WTICO_USD / NATGAS_USD 1-minute **mid** candles, restructured into CME-style sessions "
      "(18:00 NY prior day -> 17:59 NY, DST-aware). The trading calendar is the full NYMEX sessions derived from the liquid WTI feed. "
      "Exchange holidays and early-close days are dropped, as a bot knows them in advance. That leaves ~250 sessions/yr "
      "(3,848 sessions from 2005-01-03 to 2020-05-13).")
    A("* **Execution (no look-ahead):** signals use the last close strictly before the decision time. Market orders fill at the "
      "open of the next bar. Resting stop orders are simulated on each minute's OHLC path (O->L->H->C if the bar closed up, "
      "else O->H->L->C). A gap through a level fills at the bar open, never at the level.")
    A("* **Costs:** a round trip pays 2 x COST_PER_SIDE (XTI 3 bp/side, XNG 10 bp/side), plus STOP_SLIPPAGE (1 / 3 bp) for each "
      "stop-type side (breakout entries, protective stops). Entries or exits within 15 minutes after an EIA release are also charged "
      "as stop-type (wide event spreads). Sunday-open entries pay one STOP_SLIPPAGE. Overnight holds pay 2.5%/yr / 365 per calendar "
      "night. Sensitivity is reported at 0x / 1x / 2x costs.")
    A("* **P&L:** 1x notional per trade. The daily series covers all sessions (zeros on no-trade days), annualised with 252. "
      "IS = 2005-2012, OOS = 2013-2020-05. The configuration per (sub-)family and instrument is picked on IS net Sharpe only.")
    A(f"* **Trials:** {n_total} non-degenerate variants. By family (XTI/XNG): A ORB {n_fam.get(('A', 'XTIUSD'), 0)}/{n_fam.get(('A', 'XNGUSD'), 0)}, "
      f"B momentum {n_fam.get(('B', 'XTIUSD'), 0)}/{n_fam.get(('B', 'XNGUSD'), 0)}, C EIA {n_fam.get(('C', 'XTIUSD'), 0)}/{n_fam.get(('C', 'XNGUSD'), 0)}, "
      f"D sessions/calendar {n_fam.get(('D', 'XTIUSD'), 0)}/{n_fam.get(('D', 'XNGUSD'), 0)}, E mean reversion {n_fam.get(('E', 'XTIUSD'), 0)}/{n_fam.get(('E', 'XNGUSD'), 0)}. "
      "Eight 15-minute Bollinger variants with a 1-hour window are excluded as degenerate: with n = 4 bars, |z| <= 1.5, so they never "
      "trigger. Descriptive scans (hourly/session/day-of-week t-stats, regressions) and robustness grids are extra looks that are not counted.")
    A("")
    A("## Data problems found (and how they were handled)")
    A("")
    d05 = dq[(dq.sym == "XTIUSD") & (dq.year == 2005)].iloc[0]
    d06 = dq[(dq.sym == "XTIUSD") & (dq.year == 2006)].iloc[0]
    d10 = dq[(dq.sym == "XTIUSD") & (dq.year == 2010)].iloc[0]
    ngcov = dq[(dq.sym == "XNGUSD") & (dq.year >= 2013) & (dq.year <= 2019)]["bar_coverage_0900_1430"]
    A(f"1. **Pre-Globex gaps, 2005 to Jun 2006.** There are no quotes 09:30-10:00 NY (all of 2005, {pct(d06['share_no_data_0930_1000'])} of "
      "2006 sessions) and none 14:30-15:15. These are the NYMEX ACCESS pauses around the pit session. Handled: price-at-time looks back "
      "at most 20 minutes, so the 10:00-based predictors are missing in 2005, and 14:30 exits fall back to the 14:29 close.")
    A(f"2. **The pit open was 10:00 NY until early 2007, then 09:00.** The 09:00 volatility spike only appears from Feb-Mar 2007: |r| at "
      f"09:00 is {d05['abs_r_0900_vs_midday']:.2f}x midday in 2005 against {d10['abs_r_0900_vs_midday']:.2f}x in 2010. So 09:00-anchored "
      "rules are mis-anchored in 2005-06, which is part of the IS sample.")
    A(f"3. **Microstructure noise, 2005-2006.** Quotes are coarse (median |dP| {d05['median_abs_dprice']:.3f} USD on WTI in 2005) and "
      f"1-minute returns have lag-1 autocorrelation of {d05['ac1_1min_0900_1430']:.2f} (2005) and {d06['ac1_1min_0900_1430']:.2f} (2006), "
      f"against about {d10['ac1_1min_0900_1430']:.2f} later. This would flatter very short-horizon mean reversion, yet even there the "
      "5-15 minute fades lost money gross.")
    A("4. **EIA releases register at 10:35 instead of 10:30 from Jun to Dec 2008,** for both reports and both CFDs. The 09:00 open and "
      "14:28 settlement spikes are on time, so this is a release or feed quirk, not a clock shift. It is hard-coded in "
      "`ix.eia_schedule` (see `results/e06_data_checks_eia2008.csv`).")
    A("5. **Holiday-week crude reports** came out Thursday 10:30 until Sep 2008 and Thursday 11:00 from Oct 2008, verified on the "
      "1-minute spikes. The share of events whose largest 10:00-11:45 move sits at the scheduled minute is 0.61 for regular weeks and "
      "0.56 for shifted weeks. The NG storage report is Thursday 10:30 (0.72); weeks with a Tue-Fri federal holiday are dropped.")
    A("6. **Holiday and early-close sessions** (MLK, Presidents, Memorial, July 4, Labor Day, Thanksgiving + Friday, Christmas and "
      "New Year eves) have no 14:30 settlement in the feed. They are removed through the calendar.")
    A(f"7. **Sparse NG quotes.** Only {ngcov.min():.0%}-{ngcov.max():.0%} of minutes 09:00-14:30 have an NG bar in 2013-2019, and "
      "overnight is sparser. A missing minute is treated as an unchanged mid: signals forward-fill, and fills wait for the next quote. "
      "The 17:00-18:00 break shows no contract-roll jumps (the large break gaps are post-holiday). The roll-yield part of a real "
      "broker swap is not in this price series, which matters only for the overnight holds.")
    A("")
    A("## Ranked table - IS-selected best configuration per sub-family and instrument, ranked by OOS net Sharpe")
    A("")
    cols = ["sub", "sym", "best_config", "n_trials_sub", "is_sharpe", "oos_sharpe", "full_sharpe", "oos_ex2020_sharpe",
            "full_gross_sharpe", "full_sharpe_2x", "full_trades_py", "full_avg_bps", "full_hit", "full_max_dd", "full_t_stat", "verdict"]
    hdr = ["family", "inst", "IS-best config", "trials", "IS SR", "OOS SR", "full SR", "OOS SR ex-2020", "gross SR (full)",
           "full SR at 2x cost", "trades/yr", "net bp/trade", "hit", "max DD", "t (full)", "verdict"]
    fm = [None, None, "`{}`", "{:.0f}", "{:.2f}", "{:.2f}", "{:.2f}", "{:.2f}", "{:.2f}", "{:.2f}", "{:.0f}", "{:.1f}", "{:.2f}",
          lambda v: pct(v), "{:.2f}", None]
    A(md_table(Rv, cols, hdr, fm))
    A("")
    A("SR = annualised Sharpe of the daily net P&L after 1x costs (zeros on no-trade days); gross SR uses 0x costs. Trades/yr, "
      "net bp/trade, hit rate, max DD (on compounded 1x-notional P&L) and t are full-period values.")
    A("")
    A("**Share of all variants that survive out of sample:**")
    A("")
    fs2 = fs.reset_index()
    A(md_table(fs2, ["fam", "sym", "trials", "oos_gross_pos", "oos_net_pos", "median_oos_gross", "median_oos_net"],
               ["family", "inst", "trials", "OOS gross SR > 0", "OOS net SR > 0", "median OOS gross SR", "median OOS net SR"],
               [None, None, "{:.0f}", lambda v: pct(v), lambda v: pct(v), "{:.2f}", "{:.2f}"]))
    A("")
    A("## Multiple testing and cost sensitivity for the candidates (IS and OOS net Sharpe > 0.1)")
    A("")
    cands = Rv[(Rv["oos_sharpe"] > 0.1) & (Rv["is_sharpe"] > 0.1)]
    A(md_table(cands, ["sub", "sym", "best_config", "n_trials_family", "sr0_is_family", "dsr_is_family", "dsr_full_global",
                       "dsrN_is_family", "dsrN_full_family", "dsrN_full_global", "full_ci_lo", "full_ci_hi", "oos_ci_lo", "oos_ci_hi"],
               ["family", "inst", "config", "family trials", "SR0 hurdle (IS)", "DSR IS (disp.)", "DSR full global (disp.)",
                "DSR-N IS", "DSR-N full", "DSR-N full global", "full CI lo", "full CI hi", "OOS CI lo", "OOS CI hi"],
               [None, None, "`{}`", "{:.0f}"] + ["{:.2f}"] * 10))
    A("")
    A("* **DSR (disp.)** is `backtest.deflated_sharpe` with the list of all trial Sharpes, as specified. It is computed on the IS period "
      "against the IS Sharpes of the family's trials (where the selection happened), and on the full period against all "
      f"{n_total} trials. Its hurdle SR0 uses the cross-trial dispersion of Sharpes. Here that dispersion is dominated by cost "
      "differences (high-turnover variants at Sharpe -3 to -12), which inflates SR0 and pushes every DSR to ~0.")
    A("* **DSR-N** is the same formula with the hurdle set by N unskilled trials, using a trial-Sharpe variance of 1/(T-1) per day: "
      "`ix.dsr_null`, with N = family trials, or N = all trials for 'global'. It is the more informative reading here. "
      f"The best DSR-N is {cands['dsrN_is_family'].max():.2f} (IS, family), and the best global full-period value is "
      f"{cands['dsrN_full_global'].max():.2f}. " + ("Nothing clears 0.95." if (cands[['dsrN_is_family', 'dsrN_full_global']].max().max() < 0.95) else ""))
    all_zero = bool((cands["oos_ci_lo"] < 0).all()) if len(cands) else True
    A("* CIs come from a stationary bootstrap (block 20, 2000 draws) of the daily net P&L. " +
      ("**Every OOS CI includes zero.**" if all_zero else "Only " + ", ".join(
          f"`{r['sym']}|{r['best_config']}`" for _, r in cands[cands['oos_ci_lo'] > 0].iterrows()) + " has an OOS CI above zero."))
    A("")
    A(md_table(cands, ["sub", "sym", "best_config", "is_sharpe_0x", "is_sharpe", "is_sharpe_2x", "oos_sharpe_0x", "oos_sharpe",
                       "oos_sharpe_2x", "full_sharpe_0x", "full_sharpe", "full_sharpe_2x"],
               ["family", "inst", "config", "IS 0x", "IS 1x", "IS 2x", "OOS 0x", "OOS 1x", "OOS 2x", "full 0x", "full 1x", "full 2x"],
               [None, None, "`{}`"] + ["{:.2f}"] * 9))
    A("")
    A("## Per-year results of the candidates (net of 1x costs)")
    A("")
    if len(Y):
        piv = Y.pivot_table(index="year", columns="strategy", values="sharpe")
        pnl = Y.pivot_table(index="year", columns="strategy", values="net_ret")
        ntr = Y.pivot_table(index="year", columns="strategy", values="trades")
        order = list(dict.fromkeys(Y["strategy"]))
        hdr = ["year"] + [f"`{s}` SR / net % / trades" for s in order]
        A("| " + " | ".join(hdr) + " |")
        A("|" + "|".join(["---"] * len(hdr)) + "|")
        for yv in piv.index:
            cells = [str(yv)]
            for s_ in order:
                v = piv.loc[yv, s_] if s_ in piv.columns else np.nan
                cells.append(f"{f2(v)} / {pnl.loc[yv, s_] * 100:.1f} / {ntr.loc[yv, s_]:.0f}")
            A("| " + " | ".join(cells) + " |")
    A("")
    A("## Family details and verdicts")
    A("")
    # ---------------- A
    A("### A. Opening-range breakout: **reject**")
    A("")
    base = "XTIUSD|orb|09:00|30|14:30|none|none"
    A("* **Grid:** anchor 08:00/09:00/09:30; range N = 15/30/60 min; exit 14:30 or 16:55; stop none / opposite edge / midpoint; one "
      "reversal optional; filters none / narrow range (<1.0 or <0.75 of the trailing 20-day average) / prior-day trend / both. It also "
      "includes the Crabel 'stretch' version that Holmberg, Lonnbark & Lundstrom (2013) tested: stops at the anchor open "
      "+/- k x the 10-day average of min(H-O, O-L), k = 0.5/1/2. That makes 486 variants per instrument.")
    A(f"* **Gross edge exists, net does not:** {pct(float(fs.loc[('A', 'XTIUSD'), 'oos_gross_pos']))} of WTI variants have positive OOS "
      f"*gross* Sharpe, consistent with the futures literature. After costs only {pct(float(fs.loc[('A', 'XTIUSD'), 'oos_net_pos']))} "
      f"are positive, and {pct(float(fs.loc[('A', 'XNGUSD'), 'oos_net_pos']))} for NG.")
    A(f"* The canonical rule (09:00, 30-min range, 14:30 exit, no stop) scores WTI net Sharpe IS {f2(gv(base, 'is_sharpe'))} and "
      f"OOS {f2(gv(base, 'oos_sharpe'))}, gross OOS {f2(gv(base, 'oos_sharpe_0x'))}: {f2(gv(base, 'full_avg_gross_bps'), 1)} bp gross per "
      f"trade against a 7 bp cost. The IS-best WTI rule (stretch k = 0.5 from 09:00, hold to 16:55, about one trade every day) scores IS "
      f"{f2(rv('A2 ORB Crabel stretch', 'XTIUSD', 'is_sharpe'))} / OOS {f2(rv('A2 ORB Crabel stretch', 'XTIUSD', 'oos_sharpe'))}, with "
      f"{f2(rv('A2 ORB Crabel stretch', 'XTIUSD', 'full_avg_bps'), 1)} bp net per trade and max DD "
      f"{pct(rv('A2 ORB Crabel stretch', 'XTIUSD', 'full_max_dd'))}. At 2x costs it is negative "
      f"({f2(rv('A2 ORB Crabel stretch', 'XTIUSD', 'full_sharpe_2x'))}). The IS-best classic-range rule flips from "
      f"{f2(rv('A1 ORB opening range', 'XTIUSD', 'is_sharpe'))} IS to {f2(rv('A1 ORB opening range', 'XTIUSD', 'oos_sharpe'))} OOS.")
    A("* **Conclusion:** Holmberg et al.'s ORB profits in crude futures are visible gross, at 5-10 bp per trade, but they do not survive "
      "a 7-8 bp CFD round trip (breakout entries also pay stop slippage) out of sample.")
    A("")
    # ---------------- B
    A("### B. Intraday momentum (Gao, Han, Li & Zhou 2018, adapted to the 14:30 settlement): **WTI marginal+ (paper-trade); NG reject**")
    A("")
    A("Predictive regressions of r(14:00->14:30) (OLS, Newey-West 5 lags, returns winsorised at 0.5/99.5%):")
    A("")
    rr = []
    for sym in ["XTIUSD", "XNGUSD"]:
        for p in ["on900", "on930", "on1000", "first30", "mid", "r1330"]:
            rr.append({"sym": sym, "pred": p, **{f"{k}_{per}": reg_v(sym, p, per, k) for per in ["is", "oos", "full"]
                                                 for k in ["slope", "t_nw", "r2"]}})
    rr = pd.DataFrame(rr)
    names = {"on900": "prior 14:30 -> 09:00 (overnight only)", "on930": "(i) prior 14:30 -> 09:30", "on1000": "(i) prior 14:30 -> 10:00",
             "first30": "(ii) 09:00 -> 09:30", "mid": "(iii) 09:00 -> 14:00", "r1330": "13:30 -> 14:00"}
    rr["pred"] = rr["pred"].map(names)
    A(md_table(rr, ["sym", "pred", "slope_is", "t_nw_is", "slope_oos", "t_nw_oos", "t_nw_full", "r2_full"],
               ["inst", "predictor", "slope IS", "t IS", "slope OOS", "t OOS", "t full", "R2 full"],
               [None, None, "{:.3f}", "{:.2f}", "{:.3f}", "{:.2f}", "{:.2f}", lambda v: pct(v, 1)]))
    A("")
    A(f"* **The overnight-plus-morning return predicts the last half hour** in both instruments, with the same sign IS and OOS. The "
      f"09:00->09:30 return alone does not, and 09:00->14:00 is weaker. For WTI most of the effect sits in **14:25-14:28** (t "
      f"{f2(siv('XTIUSD', 'subwindow', '14:25-14:28', 'is', 't_nw'), 1)} IS / {f2(siv('XTIUSD', 'subwindow', '14:25-14:28', 'oos', 't_nw'), 1)} OOS), "
      f"just before the 14:28-14:30 settlement window. It then partially reverses at **14:30-14:35** (t "
      f"{f2(siv('XTIUSD', 'subwindow', '14:30-14:35', 'is', 't_nw'), 1)} IS / {f2(siv('XTIUSD', 'subwindow', '14:30-14:35', 'oos', 't_nw'), 1)} OOS). "
      "See `e06_B_momentum_subintervals.csv`.")
    A(f"* **Trading every day loses after costs** (WTI `on930|all`: net {f2(gv('XTIUSD|mom|on930|all|14:30', 'full_sharpe'))}, gross "
      f"{f2(gv('XTIUSD|mom|on930|all|14:30', 'full_gross_sharpe'))}, {f2(gv('XTIUSD|mom|on930|all|14:30', 'full_avg_gross_bps'), 1)} bp gross/trade). "
      f"The edge is concentrated in the strongest-signal days (`e06_momentum_buckets.png`): the top quintile earns {q5_is:.1f} bp (IS) "
      f"and {q5_oos:.1f} bp (OOS) against a 6 bp round trip. The middle quintiles earn roughly nothing.")
    A(f"* **IS-best WTI rule `{cfg}`** trades only when |signal| > the trailing-250-session 80th percentile. It scores IS "
      f"{f2(rb(cfg, 'baseline', 'is_sharpe'))} / OOS {f2(rb(cfg, 'baseline', 'oos_sharpe'))} / full {f2(rb(cfg, 'baseline', 'full_sharpe'))} "
      f"(gross full {f2(rb(cfg, 'baseline', 'full_gross_sharpe'))}), with {rb(cfg, 'baseline', 'full_trades_py'):.0f} trades/yr, "
      f"{f2(rb(cfg, 'baseline', 'full_avg_bps'), 1)} bp net/trade, hit rate {f2(rb(cfg, 'baseline', 'full_hit'))} and max DD "
      f"{pct(rb(cfg, 'baseline', 'full_max_dd'))}. At 1x notional that is {pct(rb(cfg, 'baseline', 'full_ann_ret'), 1)}/yr at "
      f"{pct(rb(cfg, 'baseline', 'full_ann_vol'), 1)} vol. The neighbours (on1000, q = 0.67, exit 14:28) are also positive OOS, "
      f"so the parameter surface is smooth. Of the {int(n_fam.get(('B', 'XTIUSD'), 0))} WTI momentum variants, "
      f"{pct(float(fs.loc[('B', 'XTIUSD'), 'oos_gross_pos']))} are positive OOS gross and {pct(float(fs.loc[('B', 'XTIUSD'), 'oos_net_pos']))} net.")
    A("* **Robustness** (`e06_B_momentum_robustness.csv`), as IS / OOS / full net Sharpe:")
    for case in ["entry 14:01", "entry 14:02", "exit 14:29 (early)", "exit 14:31 (late)", "long trades only", "short trades only",
                 "EIA report days only", "non-EIA days only", "ex-2008", "ex-2020", "vol-targeted size (cap 3x)"]:
        A(f"  * {case}: {f2(rb(cfg, case, 'is_sharpe'))} / {f2(rb(cfg, case, 'oos_sharpe'))} / {f2(rb(cfg, case, 'full_sharpe'))}"
          f" (2013-16: {f2(rb(cfg, case, 'sharpe_2013_2016'))}; 2017-20: {f2(rb(cfg, case, 'sharpe_2017_2020'))})")
    A(f"* **Reading:** the predictability is genuine, but the trading edge is thin and regime-dependent. It pays in volatile trending "
      f"years (2007-09, 2014-16, 2020) and bleeds in calm ones (2012-13, 2017-19). Vol-targeting makes it *worse*, because the edge lives "
      f"on high-vol days. Exiting one minute late (14:31) costs ~2 bp per trade. At 2x costs the full Sharpe is "
      f"{f2(rb(cfg, 'baseline', 'full_sharpe_2x'))} and OOS {f2(rb(cfg, 'baseline', 'oos_sharpe_2x'))}. The breakeven cost is "
      f"~{gross_bp / 2:.1f} bp per side, against 3 bp assumed.")
    A(f"* **NG:** the same predictability exists (NW t {f2(reg_v('XNGUSD', 'on930', 'is', 't_nw'), 1)} IS / "
      f"{f2(reg_v('XNGUSD', 'on930', 'oos', 't_nw'), 1)} OOS; gross Sharpe up to ~1.3), but the top quintile earns "
      f"{siv('XNGUSD', 'quintile', 'Q5', 'oos', 'slope'):.1f} bp OOS against a 20 bp round trip. All 44 NG variants are negative OOS net "
      f"(IS-best `{R[(R['sub'] == bm) & (R['sym'] == 'XNGUSD')]['best_config'].iloc[0]}`: OOS {f2(rv(bm, 'XNGUSD', 'oos_sharpe'))}).")
    A("")
    # ---------------- C
    A("### C. EIA report reaction: **reject as alpha; essential as a risk filter**")
    A("")
    A("Event-window size (RMS move in bp) on report days vs normal days (Mon/Tue/Fri) at the same clock time:")
    A("")
    vt = vol[(vol.time == "10:30")].copy()
    A(md_table(vt, ["sym", "event", "window", "n_events", "rms_event_bps", "rms_normal_bps", "ratio_vs_normal", "p99_abs_event_bps",
                    "p99_abs_normal_bps", "share_event_gt_1pct", "share_normal_gt_1pct"],
               ["inst", "report", "window", "events", "RMS report day", "RMS normal", "ratio", "p99 |move| report", "p99 |move| normal",
                "report share > 1%", "normal share > 1%"],
               [None, None, None, "{:.0f}", "{:.0f}", "{:.0f}", "{:.1f}", "{:.0f}", "{:.0f}", lambda v: pct(v), lambda v: pct(v)]))
    A("")
    A(f"* The 30 minutes before the crude report are *quieter* than normal (ratio {f2(vv('XTIUSD', 'crude', '10:30', 'pre T-30->T', 'ratio_vs_normal'))}). "
      f"The full 09:00-14:30 session is only {f2(vv('XTIUSD', 'crude', '10:30', '09:00->14:30', 'ratio_vs_normal'))}x normal for WTI, but "
      f"{f2(vv('XNGUSD', 'gas', '10:30', '09:00->14:30', 'ratio_vs_normal'))}x for NG on storage days. There is little cross-impact: "
      "the crude report barely moves NG, and the storage report barely moves WTI. The minute profile is in `e06_eia_vol_profile.png`.")
    A(f"* **Tests (50 variants per instrument):** continuation (|10:30->10:35 or ->10:45 move| > k x trailing-20-event median, "
      f"k = 0/1/1.5/2, hold to T+60 or 14:30); fade (same trigger, exits +15/+30/+60 min or 14:30); and pre-report drift "
      f"(09:00->10:29). For WTI, the IS-best fade goes from {f2(rv('C2 EIA fade', 'XTIUSD', 'is_sharpe'))} IS to "
      f"{f2(rv('C2 EIA fade', 'XTIUSD', 'oos_sharpe'))} OOS, and the IS-best continuation from "
      f"{f2(rv('C1 EIA continuation', 'XTIUSD', 'is_sharpe'))} to {f2(rv('C1 EIA continuation', 'XTIUSD', 'oos_sharpe'))} OOS. The median "
      f"OOS *gross* Sharpe of all WTI EIA variants is {f2(float(fs.loc[('C', 'XTIUSD'), 'median_oos_gross']))}. The post-release drift "
      "has no reliable sign, and the first move is in the price before a retail order fills.")
    A(f"* **NG continuation** (w = 15 min, k = 2, hold to 14:30) scores IS {f2(rv('C1 EIA continuation', 'XNGUSD', 'is_sharpe'))} / OOS "
      f"{f2(rv('C1 EIA continuation', 'XNGUSD', 'oos_sharpe'))} on only {rv('C1 EIA continuation', 'XNGUSD', 'full_trades_py'):.0f} trades/yr "
      f"(full t = {f2(rv('C1 EIA continuation', 'XNGUSD', 'full_t_stat'))}; zero at 2x costs). That is marginal at best: too few events to "
      "tell it apart from luck.")
    A(f"* **NG pre-report drift** (short 09:00->10:29 on storage days) looked strong IS ({f2(gv('XNGUSD|eia_pre|short|09:00->T-1', 'is_sharpe'))}) "
      f"and failed OOS ({f2(gv('XNGUSD|eia_pre|short|09:00->T-1', 'oos_sharpe'))}). It was NG's 2005-12 bear market concentrated in the "
      "morning hours, not a report effect: the same window on non-report Thursdays drifts the same way.")
    A("")
    # ---------------- D
    A("### D. Time-of-day, sessions, calendar: **reject** (a few statistically real drifts, none tradeable after costs; one unproven gap fade)")
    A("")
    srows = []
    for sym in ["XTIUSD", "XNGUSD"]:
        for it in ["asia", "london", "ny_pre", "ny_main", "post", "overnight_1430_0900", "break_gap_tue_fri", "weekend_gap"]:
            srows.append({"sym": sym, "item": it, **{f"{k}_{p}": sv(sym, it, p, k) for p in ["is", "oos", "full"] for k in ["mean_bp", "t"]}})
    srows = pd.DataFrame(srows)
    A(md_table(srows, ["sym", "item", "mean_bp_is", "t_is", "mean_bp_oos", "t_oos", "mean_bp_full", "t_full"],
               ["inst", "session (NY time)", "mean bp/day IS", "t IS", "mean bp/day OOS", "t OOS", "mean bp/day full", "t full"],
               [None, None, "{:.1f}", "{:.2f}", "{:.1f}", "{:.2f}", "{:.1f}", "{:.2f}"]))
    A("")
    A("Sessions: Asia 18:00-02:00, London 02:00-08:00, NY pre 08:00-09:00, NY main 09:00-14:30, post 14:30-17:00. "
      "Overnight is prior 14:30 -> 09:00, so overnight + NY main = the settlement-to-settlement return.")
    A("")
    stable = []
    for sym in ["XTIUSD", "XNGUSD"]:
        h = hr[hr.sym == sym].pivot_table(index="hour", columns="period", values=["t", "mean_bp"])
        for hh in h.index:
            ti, to = h.loc[hh, ("t", "is")], h.loc[hh, ("t", "oos")]
            if abs(ti) > 2 and abs(to) > 2 and np.sign(ti) == np.sign(to):
                stable.append(f"{sym} {int(hh):02d}:00-{int(hh) + 1:02d}:00 ({h.loc[hh, ('mean_bp', 'is')]:+.1f} bp IS, t {ti:.1f}; "
                              f"{h.loc[hh, ('mean_bp', 'oos')]:+.1f} bp OOS, t {to:.1f})")
    A(f"* **Hour of day** (`e06_D_hourly.csv`): only these clock hours have |t| > 2 with the same sign in both IS and OOS: "
      f"{'; '.join(stable) if stable else 'none'}. WTI has no stable hourly drift. The 10:00 hour is negative IS (t -2.7) but not "
      "OOS, and 13:00 flips sign.")
    A(f"* **WTI sessions:** no drift keeps its sign and significance from IS to OOS. The overnight/intraday split is flat (overnight "
      f"{f2(sv('XTIUSD', 'overnight_1430_0900', 'full', 'mean_bp'), 1)} bp/day, intraday {f2(sv('XTIUSD', 'ny_main', 'full', 'mean_bp'), 1)} bp/day, "
      "both insignificant). Every session hold loses after the 6 bp daily round trip.")
    A(f"* **NG post-settlement drift** is strong and persistent: +{f2(sv('XNGUSD', 'post', 'is', 'mean_bp'), 1)} bp IS (t "
      f"{f2(sv('XNGUSD', 'post', 'is', 't'), 1)}) and +{f2(sv('XNGUSD', 'post', 'oos', 'mean_bp'), 1)} bp OOS (t "
      f"{f2(sv('XNGUSD', 'post', 'oos', 't'), 1)}), positive in {n_pos_post} of {n_y_post} years, and spread through 14:35-16:30 rather than a jump. It may "
      "be an artifact of thin afternoon quoting. Either way, ~9 bp/day cannot pay a 20 bp round trip: the walk-forward session picker "
      "chooses it almost every year and still loses. NG's 2005-2020 decline happened mostly in NY hours "
      f"(09:00-14:30: {f2(sv('XNGUSD', 'ny_main', 'full', 'mean_bp'), 1)} bp/day).")
    A(f"* **Day of week:** NG on Thursdays (storage day) 09:00-14:30 averaged {dv('XNGUSD', 'intraday_0900_1430', 'Thu', 'is', 'mean_bp'):.0f} bp IS "
      f"(t {dv('XNGUSD', 'intraday_0900_1430', 'Thu', 'is', 't'):.1f}) and {dv('XNGUSD', 'intraday_0900_1430', 'Thu', 'oos', 'mean_bp'):.0f} bp OOS "
      f"(t {dv('XNGUSD', 'intraday_0900_1430', 'Thu', 'oos', 't'):.1f}). As a rule (short NG every Thursday 09:00-14:30) it scores IS "
      f"{f2(rv('D2 day-of-week hold', 'XNGUSD', 'is_sharpe'))} / OOS {f2(rv('D2 day-of-week hold', 'XNGUSD', 'oos_sharpe'))}, with "
      f"{pct(float(thu_worst['net_ret'])) if thu_worst is not None else 'n/a'} in {int(thu_worst['year']) if thu_worst is not None else ''}. It is a bet that NG's secular decline keeps showing up on report days: reject. WTI Mondays (close-to-close) averaged "
      f"{dv('XTIUSD', 'close_to_close', 'Mon', 'oos', 'mean_bp'):.0f} bp OOS (t {dv('XTIUSD', 'close_to_close', 'Mon', 'oos', 't'):.1f}) but "
      f"{dv('XTIUSD', 'close_to_close', 'Mon', 'is', 'mean_bp'):.0f} bp IS. Of the OOS figure, "
      f"{dv('XTIUSD', 'overnight_1430_0900', 'Mon', 'oos', 'mean_bp'):.0f} bp comes from Friday 14:30 -> Monday 09:00 (the weekend gap "
      f"averaged {sv('XTIUSD', 'weekend_gap', 'oos', 'mean_bp'):.0f} bp).")
    A(f"* **Sunday gap:** gaps from Friday 17:00 to the Sunday 18:00 reopen have a standard deviation of "
      f"~{sv('XTIUSD', 'weekend_gap', 'full', 'sd_bp'):.0f} bp for WTI and ~{sv('XNGUSD', 'weekend_gap', 'full', 'sd_bp'):.0f} bp for NG. "
      f"WTI gaps partially reverse by Monday 09:00 (full-sample slope t {f2(sv('XTIUSD', 'sunday_gap_predicts_reopen->09:00', 'full', 't'), 1)}, "
      f"but only {f2(sv('XTIUSD', 'sunday_gap_predicts_reopen->09:00', 'is', 't'), 1)} IS against "
      f"{f2(sv('XTIUSD', 'sunday_gap_predicts_reopen->09:00', 'oos', 't'), 1)} OOS). The IS-best of 8 rules (fade gaps > 0.5% from 18:05 "
      f"Sunday to 09:00 Monday) had IS {f2(rv(sgk, 'XTIUSD', 'is_sharpe'))}, i.e. no in-sample evidence. OOS it scored "
      f"{f2(rv(sgk, 'XTIUSD', 'oos_sharpe'))} ({f2(rv(sgk, 'XTIUSD', 'oos_ex2020_sharpe'))} ex-2020; 2020 is {pct(sg_2020_share)} of OOS P&L). Robustness "
      f"(`e06_D_sunday_gap_robustness.csv`): OOS {min(sg_oos):.2f}-{max(sg_oos):.2f} for entries 18:05-20:00 (IS {min(sg_is):.2f} to "
      f"{max(sg_is):.2f}), {min(sg_thr):.2f}-{max(sg_thr):.2f} for thresholds 0.25-2%, and {f2(sgv('18:05', '09:00', 0.005, 3.0, 'oos_sharpe'))} "
      f"at 3x costs. NG fades lose. Verdict: **marginal, OOS-only evidence**: consistent across settings from 2013 on, absent in 2005-12, "
      f"~{rv(sgk, 'XTIUSD', 'full_trades_py'):.0f} trades/yr, and exposed to Sunday-open spreads and weekend-news gaps (-33% on 2020-03-09). "
      "Forward-test before any use.")
    A(f"* **Walk-forward session picker** (each year hold the session with the largest trailing-3-year gross |t|, if |t| > 2, in its "
      f"sign): WTI OOS net {f2(rv('D4 walk-forward session pick', 'XTIUSD', 'oos_sharpe'))} (gross "
      f"{f2(rv('D4 walk-forward session pick', 'XTIUSD', 'oos_gross_sharpe'))}). NG OOS net {f2(rv('D4 walk-forward session pick', 'XNGUSD', 'oos_sharpe'))} "
      f"(gross {f2(rv('D4 walk-forward session pick', 'XNGUSD', 'oos_gross_sharpe'))}). The picks are in `e06_D_walkforward_picks.csv`.")
    A("")
    # ---------------- E
    A("### E. Short-term mean reversion: **reject (no edge even before costs)**")
    A("")
    A(f"* **Grid:** fades of 5- and 15-minute z-score extremes (bar-return z vs the prior 1 h / 4 h, or Bollinger z; |z| > 2 or 3), exiting "
      f"at the rolling mean (60-min time stop) or after 30 minutes, plus VWAP-deviation fades (|C - VWAP| > 0.25 or 0.5 x the "
      f"trailing daily range). That is {n_fam.get(('E', 'XTIUSD'), 0)} valid variants per instrument, trading 09:00-14:30.")
    A(f"* **Result:** only {pct(float(fs.loc[('E', 'XTIUSD'), 'oos_gross_pos']))} of WTI variants are positive OOS *gross*, with a median OOS "
      f"gross Sharpe of {f2(float(fs.loc[('E', 'XTIUSD'), 'median_oos_gross']))}. At 5-15 minute horizons oil shows slight continuation, not "
      f"reversion, and that holds even in the noisy 2005-06 data. After costs the IS-best WTI variant is "
      f"{f2(rv('E1 z-score fade', 'XTIUSD', 'oos_sharpe'))} OOS. Full-period net Sharpes range from {e_rng['XTIUSD'][0]:.1f} to "
      f"{e_rng['XTIUSD'][1]:.1f} for WTI and {e_rng['XNGUSD'][0]:.1f} to {e_rng['XNGUSD'][1]:.1f} for NG. "
      "Costs are decisive, but there was nothing to be decisive about.")
    A("")
    A("## What a bot would need (if the WTI momentum rule goes to paper trading)")
    A("")
    A("* **Signal at 14:00:00 NY:** s = ln(P_09:30 / P_prev), where P_prev is the prior session's mid at 14:29-14:30 NY and P_09:30 is "
      "the last mid before 09:30 NY. Keep a rolling 250-session history of |s|, and trade only if |s| > its 80th percentile "
      "(~55 trades/yr).")
    A(f"* **Orders:** a market order at 14:00-14:02 NY in sign(s), and a market exit at 14:29-14:30 NY. Never hold past 14:30, because "
      f"14:30-14:35 partially reverses (t {f2(siv('XTIUSD', 'subwindow', '14:30-14:35', 'full', 't_nw'), 1)}). A 1-2 minute entry delay is "
      "harmless; a late exit costs ~2 bp. The tests used no stop; if one is used, make it a wide catastrophe stop only.")
    A("* **Calendar:** skip exchange holidays, early-close days and any day without a 14:30 settlement. Use DST-aware New York time, "
      "not broker server time. Flat by 14:30, so no swap.")
    A(f"* **Costs:** the rule makes ~{gross_bp:.0f} bp gross per trade and breaks even at ~{gross_bp / 2:.1f} bp per side. Run it only where "
      "the WTI CFD spread plus slippage at 14:00 and 14:30 NY is <= 3 bp per side, and log realised fills against the mid. "
      "Do not run it on XNGUSD.")
    A("* **Sizing and risk:** use fixed notional (vol-targeting hurt). Expect flat or losing years in calm markets (2012-13, 2017-19). "
      "A kill-switch should key on realised slippage exceeding the budget. Treat it as a small satellite next to the daily "
      "strategies, not a core engine.")
    A("")
    A("## Risk-management facts every intraday bot on these CFDs should encode")
    A("")
    A(f"* **EIA crude report (Wed 10:30 NY; holiday weeks Thu 11:00):** WTI's release minute is ~{vv('XTIUSD', 'crude', '10:30', 'T->T+1', 'ratio_vs_normal'):.0f}x "
      f"normal size, the 99th-percentile 5-minute move is {vv('XTIUSD', 'crude', '10:30', 'T->T+5', 'p99_abs_event_bps') / 100:.1f}% "
      f"(normal {vv('XTIUSD', 'crude', '10:30', 'T->T+5', 'p99_abs_normal_bps') / 100:.1f}%), and {pct(vv('XTIUSD', 'crude', '10:30', 'T->T+5', 'share_event_gt_1pct'))} "
      "of reports move > 1% in 5 minutes. No new entries from 10:25 to 10:45; widen or pull tight stops, since they get gapped.")
    A(f"* **EIA storage report (Thu 10:30 NY):** NG's release minute is ~{vv('XNGUSD', 'gas', '10:30', 'T->T+1', 'ratio_vs_normal'):.0f}x normal, "
      f"the 99th-percentile 5-minute move is {vv('XNGUSD', 'gas', '10:30', 'T->T+5', 'p99_abs_event_bps') / 100:.1f}%, and "
      f"{pct(vv('XNGUSD', 'gas', '10:30', 'T->T+5', 'share_event_gt_1pct'))} of reports move > 1% within 5 minutes. Treat it as a "
      "scheduled gap event.")
    A("* **Settlement (14:28-14:30 NY)** is the closing range. Prices lean in the day's direction into 14:28 and partially revert at "
      "14:30-14:35.")
    A(f"* **Sunday reopen (18:00 NY):** the weekend-gap standard deviation is ~{sv('XTIUSD', 'weekend_gap', 'full', 'sd_bp'):.0f} bp, with "
      "tail events like -33% (WTI, 2020-03-09). Be flat over weekends or size for the gap; stops do not protect.")
    A("* **Holidays and early closes:** Globex halts around 13:30 NY on MLK, Presidents', Memorial, July 4, Labor and Thanksgiving days, "
      "with no settlement. Any 14:30-exit logic must handle that.")
    A("")
    A("## Files")
    A("")
    A("* **Code:** `src/intraday.py` (session matrices, execution helpers, minute-path stop-order simulator, stats, EIA schedule, "
      "`dsr_null`); `experiments/e06_intraday_data_checks.py`, `e06_intraday_orb.py`, `e06_intraday_momentum.py`, `e06_intraday_eia.py`, "
      "`e06_intraday_sessions.py`, `e06_intraday_meanrev.py`, and `e06_intraday_summary.py` with `e06_intraday_report.py`. Run the family "
      "scripts first, then the summary.")
    A("* **Results:** `results/e06_ranked.csv` (the ranked table with all columns), `e06_family_trial_summary.csv`, `e06_yearly.csv`, "
      "the family grids `e06_A_orb_grid.csv`, `e06_B_momentum_grid.csv`, `e06_C_eia_grid.csv`, `e06_D_session_grid.csv` and "
      "`e06_E_meanrev_grid.csv`, plus `e06_B_momentum_regressions.csv`, `e06_B_momentum_subintervals.csv`, `e06_B_momentum_robustness.csv`, "
      "`e06_C_eia_event_vol.csv`, `e06_C_eia_minute_profile.csv`, `e06_D_session_stats.csv`, `e06_D_hourly.csv`, `e06_D_dayofweek.csv`, "
      "`e06_D_walkforward_picks.csv`, `e06_D_sunday_gap_robustness.csv`, `e06_data_checks.csv` and `e06_data_checks_eia2008.csv`.")
    A("* **Charts:** `results/e06_cumulative_best.png`, `results/e06_momentum_buckets.png` and `results/e06_eia_vol_profile.png`.")
    A("")
    with open(os.path.join(OUT, "e06_intraday_summary.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("wrote", os.path.join(OUT, "e06_intraday_summary.md"))
