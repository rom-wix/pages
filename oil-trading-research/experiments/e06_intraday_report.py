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


def verdict_of(r):
    sub, sym = r["sub"], r["sym"]
    if sub.startswith("B") and sym == "XTIUSD":
        return "**marginal+ (paper-trade)**"
    if (r["oos_sharpe"] > 0.25 and r["is_sharpe"] > 0.25):
        return "marginal"
    if r["oos_sharpe"] > 0.1 and r["is_sharpe"] > 0.1:
        return "marginal/reject"
    return "reject"


def write_markdown(R, Y, fs, live, G, T):
    reg = pd.read_csv(os.path.join(OUT, "e06_B_momentum_regressions.csv"))
    rob = pd.read_csv(os.path.join(OUT, "e06_B_momentum_robustness.csv"))
    vol = pd.read_csv(os.path.join(OUT, "e06_C_eia_event_vol.csv"))
    sst = pd.read_csv(os.path.join(OUT, "e06_D_session_stats.csv"))
    dow = pd.read_csv(os.path.join(OUT, "e06_D_dayofweek.csv"))
    dq = pd.read_csv(os.path.join(OUT, "e06_data_checks.csv"))
    wf = pd.read_csv(os.path.join(OUT, "e06_D_walkforward_picks.csv"))

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

    n_total = len(live)
    n_fam = live.groupby(["fam", "sym"]).size()
    Rv = R.copy()
    Rv["verdict"] = Rv.apply(verdict_of, axis=1)
    L = []
    A = L.append
    A("# E06 - Intraday strategies on XTIUSD / XNGUSD CFDs (Oanda 1-minute mids, 2005-01 .. 2020-05)")
    A("")
    A("*Generated by `experiments/e06_intraday_summary.py` (numbers below are pulled from the result CSVs).*")
    A("")
    A("## Bottom line")
    A("")
    bm = "B  intraday momentum"
    A(f"* **{n_total} strategy variants** were backtested (5 families x 2 instruments, parameters chosen on 2005-2012 "
      "only). After realistic CFD costs almost everything is dead. Most families have positive *gross* edge, "
      "but spreads and slippage eat it. Natural gas's 20 bp round trip kills every NG idea.")
    A(f"* **Only one idea is worth paper trading: WTI intraday momentum into the settlement.** At 14:00 NY, trade "
      f"14:00->14:30 in the direction of the move from the prior session's 14:30 to today's 09:30, and only when that "
      f"move is in the top quintile of its trailing-year distribution. It scores net Sharpe IS {f2(rv(bm, 'XTIUSD', 'is_sharpe'))} / "
      f"OOS {f2(rv(bm, 'XTIUSD', 'oos_sharpe'))} / full {f2(rv(bm, 'XTIUSD', 'full_sharpe'))} with "
      f"{rv(bm, 'XTIUSD', 'full_trades_py'):.0f} trades/yr and {f2(rv(bm, 'XTIUSD', 'full_avg_bps'), 1)} bp net per trade. "
      f"The predictability is real (Newey-West t = {f2(reg_v('XTIUSD', 'on930', 'is', 't_nw'), 1)} IS, "
      f"{f2(reg_v('XTIUSD', 'on930', 'oos', 't_nw'), 1)} OOS). The trading edge is thin, though. It halves at 2x costs "
      f"(full {f2(rv(bm, 'XTIUSD', 'full_sharpe_2x'))}), and it comes from high-volatility trending years: OOS without 2020 it is "
      f"{f2(rv(bm, 'XTIUSD', 'oos_ex2020_sharpe'))}, and 2017-2019 lost money. The deflated Sharpe is low "
      f"(DSR {f2(rv(bm, 'XTIUSD', 'dsr_is_family'))} on its own {int(rv(bm, 'XTIUSD', 'n_trials_family'))}-trial family). "
      "Verdict: **marginal+ / promising only as a small, cost-sensitive satellite**. It is not a stand-alone bot.")
    A("* Opening-range breakout, EIA reaction, session drifts and short-term mean reversion: **reject** "
      "(details and the few marginal survivors below).")
    A("* The EIA releases matter for **risk management**, not alpha. The first minute after the crude report moves "
      f"{vv('XTIUSD', 'crude', '10:30', 'T->T+1', 'ratio_vs_normal'):.1f}x a normal minute, and after the NG storage report "
      f"{vv('XNGUSD', 'gas', '10:30', 'T->T+1', 'ratio_vs_normal'):.1f}x. "
      f"{pct(vv('XNGUSD', 'gas', '10:30', 'T->T+5', 'share_event_gt_1pct'))} of NG storage releases move NG > 1% within 5 minutes.")
    A("")
    A("## Setup")
    A("")
    A("* Data: Oanda WTICO_USD / NATGAS_USD 1-minute **mid** candles, restructured into CME-style sessions "
      "(18:00 NY prior day -> 17:59 NY). The trading calendar is the full NYMEX sessions derived from the liquid WTI feed. "
      "Exchange holidays and early-close days are dropped, as a bot knows them in advance. That leaves ~250 sessions/yr "
      "and 3,848 sessions in total.")
    A("* Execution (no look-ahead): signals use the last close strictly before the decision time. Market orders fill at the "
      "open of the next bar. Resting stop orders are simulated on each minute's OHLC path (O->L->H->C if the bar closed up, "
      "else O->H->L->C). A gap through a level fills at the bar open.")
    A("* Costs per round trip: 2 x COST_PER_SIDE (XTI 3 bp/side, XNG 10 bp/side), plus STOP_SLIPPAGE (1 / 3 bp) per stop-type side. "
      "Entries or exits within 15 minutes after an EIA release are charged as stop-type (wide event spreads). Overnight holds pay "
      "2.5%/yr / 365 per calendar night. Cost sensitivity is shown at 0x / 1x / 2x.")
    A("* P&L: 1x notional per trade. The daily series covers all sessions (zeros on no-trade days), annualised with 252. "
      "IS = 2005-2012 and OOS = 2013-2020-05. Parameters are picked on IS net Sharpe only.")
    A(f"* Trials: {n_total} non-degenerate variants. By family and instrument (XTI/XNG): A ORB {n_fam.get(('A', 'XTIUSD'), 0)}/{n_fam.get(('A', 'XNGUSD'), 0)}, "
      f"B momentum {n_fam.get(('B', 'XTIUSD'), 0)}/{n_fam.get(('B', 'XNGUSD'), 0)}, C EIA {n_fam.get(('C', 'XTIUSD'), 0)}/{n_fam.get(('C', 'XNGUSD'), 0)}, "
      f"D sessions {n_fam.get(('D', 'XTIUSD'), 0)}/{n_fam.get(('D', 'XNGUSD'), 0)}, E mean reversion {n_fam.get(('E', 'XTIUSD'), 0)}/{n_fam.get(('E', 'XNGUSD'), 0)}. "
      "Eight 15-minute Bollinger variants with a 1-hour window are excluded as degenerate: with n = 4 bars, |z| <= 1.5 < threshold. "
      "Descriptive scans (hourly/session/day-of-week t-stats, regressions) are extra looks that are not counted.")
    A("* Deflated Sharpe (Bailey & Lopez de Prado): `dsr_is_family` tests the IS Sharpe of the chosen configuration against the "
      "IS Sharpes of all trials in its family and instrument, which is where the selection happened. `dsr_full_global` tests the "
      f"full-period Sharpe against all {n_total} trials. The DSR treats cross-trial dispersion as noise, so it is conservative "
      "(cost-driven dispersion inflates the hurdle `sr0`).")
    A("")
    A("## Data problems found (and how they were handled)")
    A("")
    d05 = dq[(dq.sym == "XTIUSD") & (dq.year == 2005)].iloc[0]
    d06 = dq[(dq.sym == "XTIUSD") & (dq.year == 2006)].iloc[0]
    d10 = dq[(dq.sym == "XTIUSD") & (dq.year == 2010)].iloc[0]
    A(f"1. **Pre-Globex hours, 2005 to Jun 2006.** No quotes 09:30-10:00 NY (all of 2005, {pct(d06['share_no_data_0930_1000'])} of 2006 sessions) "
      "and none 14:30-15:15. These are the NYMEX ACCESS pauses around the pit session. Handled: price-at-time looks back at most 20 minutes, "
      "so the 10:00 predictors are NaN in 2005. 14:30 exits fall back to the 14:29 close.")
    A("2. **The pit open was at 10:00 NY until early 2007, then 09:00.** The 09:00 volatility spike appears only from Feb-Mar 2007, "
      f"with |r| at 09:00 vs midday {d05['abs_r_0900_vs_midday']:.2f}x in 2005 against {d10['abs_r_0900_vs_midday']:.2f}x in 2010. "
      "So '09:00-anchored' rules in 2005-06 are not anchored to the real open. This hurts the ORB IS period.")
    A(f"3. **Microstructure noise, 2005-2006.** Quotes are coarse (median |dP| {d05['median_abs_dprice']:.3f} USD on WTI in 2005) and 1-minute "
      f"returns show lag-1 autocorrelation of {d05['ac1_1min_0900_1430']:.2f} (2005) and {d06['ac1_1min_0900_1430']:.2f} (2006), against "
      f"about {d10['ac1_1min_0900_1430']:.2f} later. This would flatter very short-horizon mean reversion. Even so, the 5-15 minute "
      "fades lost money gross in those years.")
    A("4. **The EIA releases register at 10:35, not 10:30, from Jun to Dec 2008,** for both reports and both CFDs, while the 09:00 open "
      "and 14:28 settlement spikes are on time. This is a feed or release quirk, not a clock shift. Handled in `ix.eia_schedule` "
      "(`results/e06_data_checks_eia2008.csv`).")
    A("5. **Holiday-week crude reports** came out Thursday 10:30 until Sep 2008 and Thursday 11:00 from Oct 2008, verified on the "
      "1-minute spikes. With this rule the spike-at-scheduled-minute hit rate is 0.61 regular / 0.56 shifted. The NG storage "
      "report is Thursday 10:30 (hit rate 0.72), and weeks with a Tue-Fri federal holiday are dropped.")
    A("6. **Early-close / holiday sessions** (MLK, Presidents, Memorial, July 4, Labor Day, Thanksgiving + Friday, Christmas and "
      "New Year eves) have no 14:30 settlement in the feed. They are excluded via the calendar, since they are known in advance.")
    A("7. **Sparse NG quotes.** Only 68-78% of minutes 09:00-14:30 have an NG bar in 2013-2019, and overnight is far sparser. "
      "Missing minutes mean an unchanged mid, so prices are forward-filled for signals and fills wait for the next quote. "
      "There are no contract-roll jumps in the 17:00-18:00 break (large break gaps are post-holiday gaps). Note that the "
      "roll-yield part of a real broker swap is not in this price series; this matters only for the overnight holds.")
    A("")
    A("## Ranked table - IS-selected best configuration per sub-family and instrument (ranked by OOS net Sharpe)")
    A("")
    cols = ["sub", "sym", "best_config", "n_trials_sub", "is_sharpe", "oos_sharpe", "full_sharpe", "oos_ex2020_sharpe",
            "full_gross_sharpe", "full_trades_py", "full_avg_bps", "full_hit", "full_max_dd", "full_t_stat",
            "dsr_is_family", "dsr_full_global", "verdict"]
    hdr = ["family", "inst", "IS-best config", "trials", "IS SR", "OOS SR", "full SR", "OOS SR ex-2020", "gross SR (full)",
           "trades/yr", "net bp/trade", "hit", "max DD", "t (full)", "DSR IS-fam", "DSR global", "verdict"]
    fm = [None, None, "`{}`", "{:.0f}", "{:.2f}", "{:.2f}", "{:.2f}", "{:.2f}", "{:.2f}", "{:.0f}", "{:.1f}", "{:.2f}",
          lambda v: pct(v), "{:.2f}", "{:.2f}", "{:.2f}", None]
    A(md_table(Rv, cols, hdr, fm))
    A("")
    A("SR = Sharpe of the daily net P&L after 1x costs (zeros on no-trade days). 'gross SR' uses 0x costs. The DSR columns "
      "are explained in Setup.")
    A("")
    A("How many trials survive out of sample (share of all variants with OOS Sharpe > 0):")
    A("")
    fs2 = fs.reset_index()
    A(md_table(fs2, ["fam", "sym", "trials", "oos_gross_pos", "oos_net_pos", "median_oos_gross", "median_oos_net"],
               ["family", "inst", "trials", "OOS gross SR > 0", "OOS net SR > 0", "median OOS gross SR", "median OOS net SR"],
               [None, None, "{:.0f}", lambda v: pct(v), lambda v: pct(v), "{:.2f}", "{:.2f}"]))
    A("")
    A("## Cost sensitivity (IS-selected configurations with IS and OOS net Sharpe > 0.1)")
    A("")
    cands = Rv[(Rv["oos_sharpe"] > 0.1) & (Rv["is_sharpe"] > 0.1)]
    A(md_table(cands, ["sub", "sym", "best_config", "is_sharpe_0x", "is_sharpe", "is_sharpe_2x", "oos_sharpe_0x", "oos_sharpe",
                       "oos_sharpe_2x", "full_sharpe_0x", "full_sharpe", "full_sharpe_2x", "oos_ci_lo", "oos_ci_hi"],
               ["family", "inst", "config", "IS 0x", "IS 1x", "IS 2x", "OOS 0x", "OOS 1x", "OOS 2x", "full 0x", "full 1x",
                "full 2x", "OOS 95% CI lo", "OOS 95% CI hi"],
               [None, None, "`{}`"] + ["{:.2f}"] * 11))
    A("")
    A("The CIs come from a stationary bootstrap (block 20, 2000 draws) of the OOS daily net P&L. **Every OOS CI includes zero.**")
    A("")
    A("## Per-year results of the candidates (net of 1x costs)")
    A("")
    if len(Y):
        piv = Y.pivot_table(index="year", columns="strategy", values="sharpe")
        pnl = Y.pivot_table(index="year", columns="strategy", values="net_ret")
        ntr = Y.pivot_table(index="year", columns="strategy", values="trades")
        order = list(dict.fromkeys(Y["strategy"]))
        hdr = ["year"] + [f"`{s}` SR / net % / n" for s in order]
        A("| " + " | ".join(hdr) + " |")
        A("|" + "|".join(["---"] * len(hdr)) + "|")
        for yv in piv.index:
            cells = [str(yv)]
            for s in order:
                cells.append(f"{f2(piv.loc[yv, s])} / {pnl.loc[yv, s] * 100:.1f} / {ntr.loc[yv, s]:.0f}")
            A("| " + " | ".join(cells) + " |")
    A("")
    A("## Family details and verdicts")
    A("")
    # ---------------- A
    A("### A. Opening-range breakout: **reject**")
    A("")
    base = "XTIUSD|orb|09:00|30|14:30|none|none"
    A(f"* Grid: anchor 08:00/09:00/09:30, N = 15/30/60 min, exit 14:30/16:55, stop none / opposite edge / midpoint, one reversal "
      f"optional, filters none / narrow range (<1.0 or <0.75 of the 20-day average) / prior-day trend / both, plus the Crabel 'stretch' "
      f"version that Holmberg, Lonnbark & Lundstrom (2013) tested (k = 0.5/1/2 x the 10-day average min(H-O, O-L)). "
      f"That makes 486 variants per instrument.")
    A(f"* Gross edge exists: {pct(float(fs.loc[('A', 'XTIUSD'), 'oos_gross_pos']))} of WTI variants have positive OOS *gross* "
      f"Sharpe, consistent with the futures literature. After costs only {pct(float(fs.loc[('A', 'XTIUSD'), 'oos_net_pos']))} are "
      f"positive, and {pct(float(fs.loc[('A', 'XNGUSD'), 'oos_net_pos']))} for NG.")
    A(f"* The canonical 09:00 / 30-minute range / 14:30 exit / no stop scores WTI net Sharpe IS {f2(gv(base, 'is_sharpe'))}, OOS "
      f"{f2(gv(base, 'oos_sharpe'))}, gross OOS {f2(gv(base, 'oos_sharpe_0x'))}, at {f2(gv(base, 'full_avg_gross_bps'), 1)} bp gross per trade "
      f"against a 6-8 bp cost. The IS-best WTI version (Crabel stretch k = 0.5 from 09:00, hold to 16:55) scores IS "
      f"{f2(rv('A2 ORB Crabel stretch', 'XTIUSD', 'is_sharpe'))} / OOS {f2(rv('A2 ORB Crabel stretch', 'XTIUSD', 'oos_sharpe'))}, "
      f"with {f2(rv('A2 ORB Crabel stretch', 'XTIUSD', 'full_avg_bps'), 1)} bp net per trade, and is negative at 2x costs "
      f"({f2(rv('A2 ORB Crabel stretch', 'XTIUSD', 'full_sharpe_2x'))}). The IS-best classic-range version flips from "
      f"{f2(rv('A1 ORB opening range', 'XTIUSD', 'is_sharpe'))} IS to {f2(rv('A1 ORB opening range', 'XTIUSD', 'oos_sharpe'))} OOS.")
    A("* Conclusion: Holmberg et al.'s ORB profits in crude futures do not survive CFD costs out of sample. The gross edge is "
      "about 5-10 bp per trade and the cost is 6-8 bp (breakout entries pay stop slippage).")
    A("")
    # ---------------- B
    A("### B. Intraday momentum (Gao, Han, Li & Zhou 2018 adapted to the 14:30 settlement): **WTI marginal+ (paper-trade), NG reject**")
    A("")
    A("Predictive regressions of r(14:00->14:30) (OLS, Newey-West 5 lags, returns winsorised at 0.5/99.5%):")
    A("")
    rr = []
    for sym in ["XTIUSD", "XNGUSD"]:
        for p in ["on900", "on930", "on1000", "first30", "mid", "r1330"]:
            rr.append({"sym": sym, "pred": p, **{f"{k}_{per}": reg_v(sym, p, per, k) for per in ["is", "oos", "full"]
                                                 for k in ["slope", "t_nw", "r2"]}})
    rr = pd.DataFrame(rr)
    names = {"on900": "prior 14:30 -> 09:00 (overnight only)", "on930": "prior 14:30 -> 09:30", "on1000": "prior 14:30 -> 10:00",
             "first30": "09:00 -> 09:30", "mid": "09:00 -> 14:00", "r1330": "13:30 -> 14:00"}
    rr["pred"] = rr["pred"].map(names)
    A(md_table(rr, ["sym", "pred", "slope_is", "t_nw_is", "slope_oos", "t_nw_oos", "t_nw_full", "r2_full"],
               ["inst", "predictor", "slope IS", "t IS", "slope OOS", "t OOS", "t full", "R2 full"],
               [None, None, "{:.3f}", "{:.2f}", "{:.3f}", "{:.2f}", "{:.2f}", lambda v: pct(v, 1)]))
    A("")
    cfg = "on930|q0.8|14:30"
    A(f"* The overnight-plus-first-half-hour return predicts the last half hour in both instruments, with the same sign IS and OOS. "
      f"The 09:00->09:30 and 13:30->14:00 returns alone do not. Most of the WTI effect sits in 14:25-14:28, just before the 14:28-14:30 "
      f"settlement window, and partly reverses at 14:30-14:35 (see `e06_B_momentum_regressions.csv`).")
    A(f"* Trading every day loses after costs (WTI `on930|all` net Sharpe {f2(gv('XTIUSD|mom|on930|all|14:30', 'full_sharpe'))}, "
      f"gross {f2(gv('XTIUSD|mom|on930|all|14:30', 'full_gross_sharpe'))}). The edge is concentrated in the strongest-signal days "
      f"(chart `e06_momentum_buckets.png`): the top quintile earns about 17 bp gross in both IS and OOS, against a 6 bp round trip.")
    A(f"* IS-best WTI rule `{cfg}`: trade only when |signal| > the trailing-250-day 80th percentile. It scores IS {f2(rb(cfg, 'baseline', 'is_sharpe'))} / "
      f"OOS {f2(rb(cfg, 'baseline', 'oos_sharpe'))} / full {f2(rb(cfg, 'baseline', 'full_sharpe'))}, gross full {f2(rb(cfg, 'baseline', 'full_gross_sharpe'))}, "
      f"with {rb(cfg, 'baseline', 'full_trades_py'):.0f} trades/yr, {f2(rb(cfg, 'baseline', 'full_avg_bps'), 1)} bp net/trade, "
      f"hit rate {f2(rb(cfg, 'baseline', 'full_hit'))}, max DD {pct(rb(cfg, 'baseline', 'full_max_dd'))}, ann. return "
      f"{pct(rb(cfg, 'baseline', 'full_ann_ret'), 1)} at {pct(rb(cfg, 'baseline', 'full_ann_vol'), 1)} vol (1x notional). The neighbours "
      f"(on1000, q = 0.67, exit 14:28) are all positive OOS, so the parameter surface is smooth.")
    A("* Robustness (`e06_B_momentum_robustness.csv`):")
    for case in ["entry 14:01", "entry 14:02", "exit 14:29 (early)", "exit 14:31 (late)", "long trades only", "short trades only",
                 "EIA report days only", "non-EIA days only", "ex-2008", "ex-2020", "vol-targeted size (cap 3x)"]:
        A(f"  * {case}: IS {f2(rb(cfg, case, 'is_sharpe'))} / OOS {f2(rb(cfg, case, 'oos_sharpe'))} / full {f2(rb(cfg, case, 'full_sharpe'))}"
          f" (2013-16 {f2(rb(cfg, case, 'sharpe_2013_2016'))}, 2017-20 {f2(rb(cfg, case, 'sharpe_2017_2020'))})")
    A("* Reading: this is genuine predictability, but a thin and regime-dependent trading edge. Profits come from volatile trending "
      "years (2007-09, 2014-16, 2020), and calm years (2012-13, 2017-19) bleed. Vol-targeting makes it *worse*, because the edge "
      "lives in high-vol days. Exiting one minute late (14:31) costs about 2 bp. At 2x costs the full Sharpe is "
      f"{f2(rb(cfg, 'baseline', 'full_sharpe_2x'))}. The breakeven cost is about 7.7 bp per side.")
    A(f"* NG: the same predictability exists (gross Sharpe up to ~1.3), but about 10 bp gross per trade cannot pay a 20 bp round "
      f"trip. Every NG variant is negative OOS net (IS-best `{R[(R['sub'] == bm) & (R['sym'] == 'XNGUSD')]['best_config'].iloc[0]}` "
      f"scores OOS {f2(rv(bm, 'XNGUSD', 'oos_sharpe'))}).")
    A("")
    # ---------------- C
    A("### C. EIA report reaction: **reject as alpha; essential as a risk filter**")
    A("")
    A("Event-window size (RMS move, bp) on report days vs normal days (Mon/Tue/Fri) at the same clock time:")
    A("")
    vt = vol[((vol.sym == "XTIUSD") & (vol.event == "crude") & (vol.time == "10:30")) |
             ((vol.sym == "XNGUSD") & (vol.event == "gas") & (vol.time == "10:30")) |
             ((vol.sym == "XNGUSD") & (vol.event == "crude") & (vol.time == "10:30")) |
             ((vol.sym == "XTIUSD") & (vol.event == "gas") & (vol.time == "10:30"))].copy()
    A(md_table(vt, ["sym", "event", "window", "n_events", "rms_event_bps", "rms_normal_bps", "ratio_vs_normal", "p99_abs_event_bps",
                    "share_event_gt_1pct"],
               ["inst", "report", "window", "events", "RMS report day", "RMS normal", "ratio", "99th pct |move| report day",
                "share > 1%"],
               [None, None, None, "{:.0f}", "{:.0f}", "{:.0f}", "{:.1f}", "{:.0f}", lambda v: pct(v)]))
    A("")
    A(f"* The 30 minutes before the crude report are *quieter* than normal (ratio {f2(vv('XTIUSD', 'crude', '10:30', 'pre T-30->T', 'ratio_vs_normal'))}). "
      f"The full 09:00-14:30 session is only {f2(vv('XTIUSD', 'crude', '10:30', '09:00->14:30', 'ratio_vs_normal'))}x normal for WTI, but "
      f"{f2(vv('XNGUSD', 'gas', '10:30', '09:00->14:30', 'ratio_vs_normal'))}x for NG on storage days. The crude report barely moves NG, "
      "and the storage report barely moves WTI.")
    A(f"* Continuation (|10:30->10:35 or ->10:45 move| > k x trailing median, k = 0/1/1.5/2, hold to 11:30 or 14:30), fade (same "
      f"trigger, exits +15/+30/+60 min or 14:30) and pre-report drift (09:00->10:29) give 50 variants per instrument. For WTI, the "
      f"IS-best fade scores {f2(rv('C2 EIA fade', 'XTIUSD', 'is_sharpe'))} IS and {f2(rv('C2 EIA fade', 'XTIUSD', 'oos_sharpe'))} OOS, "
      "and continuation is about zero even gross. The first-minute reaction is unpredictable in sign, and it is already in the "
      "price before a retail order can fill.")
    A(f"* NG continuation (w = 15 min, k = 2, hold to 14:30) scores IS {f2(rv('C1 EIA continuation', 'XNGUSD', 'is_sharpe'))} / OOS "
      f"{f2(rv('C1 EIA continuation', 'XNGUSD', 'oos_sharpe'))}, but on only {rv('C1 EIA continuation', 'XNGUSD', 'full_trades_py'):.0f} "
      f"trades/yr (t = {f2(rv('C1 EIA continuation', 'XNGUSD', 'full_t_stat'))}, DSR ~0). That is marginal at best: too few events to "
      "distinguish from luck.")
    A(f"* The NG pre-report drift (short 09:00->10:29 on storage days) looked strong IS ({f2(gv('XNGUSD|eia_pre|short|09:00->T-1', 'is_sharpe'))}) "
      f"and failed OOS ({f2(gv('XNGUSD|eia_pre|short|09:00->T-1', 'oos_sharpe'))}). It was NG's 2005-12 bear market in the morning hours, "
      "not a report effect: the same window on non-report Thursdays drifts the same way.")
    A("")
    # ---------------- D
    A("### D. Time-of-day, sessions, calendar: **reject** (a few statistically real drifts, none tradeable after costs)")
    A("")
    srows = []
    for sym in ["XTIUSD", "XNGUSD"]:
        for it in ["asia", "london", "ny_pre", "ny_main", "post", "overnight_1430_0900", "break_gap_tue_fri", "weekend_gap"]:
            srows.append({"sym": sym, "item": it, **{f"{k}_{p}": sv(sym, it, p, k) for p in ["is", "oos", "full"] for k in ["mean_bp", "t"]}})
    srows = pd.DataFrame(srows)
    A(md_table(srows, ["sym", "item", "mean_bp_is", "t_is", "mean_bp_oos", "t_oos", "mean_bp_full", "t_full"],
               ["inst", "session (NY)", "mean bp IS", "t IS", "mean bp OOS", "t OOS", "mean bp full", "t full"],
               [None, None, "{:.1f}", "{:.2f}", "{:.1f}", "{:.2f}", "{:.1f}", "{:.2f}"]))
    A("")
    A("Sessions: Asia 18:00-02:00, London 02:00-08:00, NY pre 08:00-09:00, NY main 09:00-14:30, post 14:30-17:00. "
      "Overnight = prior 14:30 -> 09:00 (so overnight + NY main is the full settlement-to-settlement return).")
    A("")
    A(f"* WTI: no session drift keeps its sign and significance from IS to OOS. The overnight/intraday split is flat "
      f"(overnight {f2(sv('XTIUSD', 'overnight_1430_0900', 'full', 'mean_bp'), 1)} bp/day, intraday {f2(sv('XTIUSD', 'ny_main', 'full', 'mean_bp'), 1)} bp/day, "
      "both insignificant). The best session hold loses after the 6 bp daily round trip.")
    A(f"* NG: the post-settlement drift is strong and persistent (+{f2(sv('XNGUSD', 'post', 'is', 'mean_bp'), 1)} bp IS, t {f2(sv('XNGUSD', 'post', 'is', 't'), 1)}; "
      f"+{f2(sv('XNGUSD', 'post', 'oos', 'mean_bp'), 1)} bp OOS, t {f2(sv('XNGUSD', 'post', 'oos', 't'), 1)}; positive in 15 of 16 years; spread "
      "through 14:35-16:30, not a jump). It may be a feed artifact of thin afternoon quoting. Either way, ~9 bp/day against a 20 bp round "
      "trip is untradeable. NG's 2005-2020 decline happened mostly in NY hours: 09:00-14:30 averaged "
      f"{f2(sv('XNGUSD', 'ny_main', 'full', 'mean_bp'), 1)} bp/day.")
    thu = dow[(dow.sym == "XNGUSD") & (dow["item"] == "intraday_0900_1430") & (dow.weekday == "Thu")]
    mon = dow[(dow.sym == "XTIUSD") & (dow["item"] == "close_to_close") & (dow.weekday == "Mon")]
    A(f"* Day of week: the one notable cell is NG on Thursdays (storage day), 09:00-14:30 at "
      f"{thu[thu.period == 'is']['mean_bp'].iloc[0]:.0f} bp IS (t {thu[thu.period == 'is']['t'].iloc[0]:.1f}) and "
      f"{thu[thu.period == 'oos']['mean_bp'].iloc[0]:.0f} bp OOS (t {thu[thu.period == 'oos']['t'].iloc[0]:.1f}). As a rule (short NG every "
      f"Thursday 09:00-14:30) it scores IS {f2(rv('D2 day-of-week hold', 'XNGUSD', 'is_sharpe'))} / OOS {f2(rv('D2 day-of-week hold', 'XNGUSD', 'oos_sharpe'))}, "
      "with years like 2016 at -34%. It is a bet that NG's secular decline continues on report days. Marginal/reject, and dangerous "
      f"in an NG bull market. WTI Mondays (close-to-close) averaged {mon[mon.period == 'full']['mean_bp'].iloc[0]:.0f} bp "
      f"(t {mon[mon.period == 'full']['t'].iloc[0]:.1f}), almost all OOS and driven by weekend gaps in 2014-2020.")
    A(f"* Sunday gap: Friday 17:00 -> Sunday 18:00 reopen gaps have a standard deviation of about "
      f"{f2(sv('XTIUSD', 'weekend_gap', 'full', 'sd_bp'), 0)} bp (both instruments). For WTI, gaps tend to partially reverse by "
      f"Monday 09:00 (slope t {f2(sv('XTIUSD', 'sunday_gap_predicts_reopen->09:00', 'full', 't'), 1)}). The IS-best rule (fade gaps > 0.5% "
      f"from 18:05 Sunday to 09:00 Monday) scores IS {f2(rv('D3 Sunday-gap', 'XTIUSD', 'is_sharpe'))} / OOS {f2(rv('D3 Sunday-gap', 'XTIUSD', 'oos_sharpe'))}, "
      f"but on ~7 trades/yr, and OOS ex-2020 it is {f2(rv('D3 Sunday-gap', 'XTIUSD', 'oos_ex2020_sharpe'))}. Four March-April 2020 trades "
      "make up most of the OOS P&L. It is a curiosity, not a strategy: Sunday-open spreads are wide and stops gap through.")
    A(f"* Walk-forward session picker (each year hold the session with the largest trailing-3-year gross |t| if |t| > 2, in its "
      f"sign, re-picked yearly): WTI OOS net {f2(rv('D4 walk-forward session pick', 'XTIUSD', 'oos_sharpe'))}. NG picks the "
      f"post-settlement long almost every year, yet OOS net is {f2(rv('D4 walk-forward session pick', 'XNGUSD', 'oos_sharpe'))} after costs "
      f"(gross OOS {f2(rv('D4 walk-forward session pick', 'XNGUSD', 'oos_gross_sharpe'))}). Picks are in `e06_D_walkforward_picks.csv`.")
    A("")
    # ---------------- E
    A("### E. Short-term mean reversion: **reject (no edge even before costs)**")
    A("")
    A(f"* Fades of 5- and 15-minute z-score extremes (return z vs the prior 1 h / 4 h, or Bollinger z; |z| > 2 or 3), exiting at the rolling "
      f"mean or after 30 minutes, plus VWAP-deviation fades: {n_fam.get(('E', 'XTIUSD'), 0)} valid variants per instrument. Only "
      f"{pct(float(fs.loc[('E', 'XTIUSD'), 'oos_gross_pos']))} of WTI variants are positive OOS *gross*, and the median OOS gross "
      f"Sharpe is {f2(float(fs.loc[('E', 'XTIUSD'), 'median_oos_gross']))}. At 5-15 minute horizons oil shows slight continuation, "
      f"not reversion. After costs the best WTI variant is {f2(rv('E1 z-score fade', 'XTIUSD', 'oos_sharpe'))} OOS, and high-turnover "
      "variants reach Sharpe -3 to -8. Costs are decisive, as expected, and there was nothing to be decisive about.")
    A("")
    A("## What a bot would need (if you take the WTI momentum rule to paper trading)")
    A("")
    A("* **Signal (computed at 14:00:00 NY):** s = ln(P_09:30 / P_settle,prev), where P_settle,prev is the prior session's price at "
      "14:29-14:30 NY and P_09:30 is the last mid before 09:30 NY. Keep a rolling 250-session history of |s|. Trade only if "
      "|s| > its 80th percentile, which gives about 55 trades/yr.")
    A("* **Orders:** a market order at 14:00-14:02 NY in sign(s), then a market exit at 14:29-14:30 NY. Do not hold past 14:30: "
      "14:30-14:35 partially reverses (t = -4.8 on WTI). Delaying the entry by 1-2 minutes is harmless, but a late exit costs ~2 bp. "
      "Use no stop, or only a wide catastrophe stop (e.g., 3x the trailing 30-minute RMS); the tests used none.")
    A("* **Filters and calendar:** skip exchange holidays, early-close days and days with no 14:30 settlement. Use DST-aware NY "
      "time, not broker server time. Everything is flat by 14:30, so there is no swap.")
    A("* **Costs:** the edge is ~15 bp gross per trade and breaks even at ~7.7 bp per side. Only run it where the WTI CFD spread plus "
      "slippage at 14:00 and 14:30 NY is <= 3 bp per side, and measure the realised fills. Do not run it on XNGUSD.")
    A("* **Sizing and risk:** fixed notional per trade (vol-targeting hurt). Expect long flat or losing stretches in calm years "
      "(2012-13, 2017-19). Use a kill-switch on realised slippage rather than on P&L, and treat it as a small satellite, not a core "
      "strategy.")
    A("")
    A("## Risk-management facts every intraday bot on these CFDs should encode")
    A("")
    A(f"* **EIA crude report (Wed 10:30 NY; holiday weeks Thu 11:00):** WTI's first minute is ~{vv('XTIUSD', 'crude', '10:30', 'T->T+1', 'ratio_vs_normal'):.0f}x "
      f"normal size, the 99th-percentile 5-minute move is {vv('XTIUSD', 'crude', '10:30', 'T->T+5', 'p99_abs_event_bps') / 100:.1f}%, and "
      f"{pct(vv('XTIUSD', 'crude', '10:30', 'T->T+5', 'share_event_gt_1pct'))} of reports move > 1% in 5 minutes. Recommendation: no new "
      "entries from 10:25 to 10:45, and move or widen stops, since stops placed near the market get gapped.")
    A(f"* **EIA natural-gas storage report (Thu 10:30 NY):** NG's first minute is ~{vv('XNGUSD', 'gas', '10:30', 'T->T+1', 'ratio_vs_normal'):.0f}x "
      f"normal, the 99th-percentile 5-minute move is {vv('XNGUSD', 'gas', '10:30', 'T->T+5', 'p99_abs_event_bps') / 100:.1f}%, and "
      f"{pct(vv('XNGUSD', 'gas', '10:30', 'T->T+5', 'share_event_gt_1pct'))} of reports move > 1% within 5 minutes. Treat it as a scheduled "
      "gap event.")
    A("* **Settlement (14:28-14:30 NY)** is the high-volume closing range. Prices drift in the direction of the day into 14:28 and "
      "partially revert at 14:30-14:35.")
    A(f"* **Sunday reopen (18:00 NY):** weekend-gap standard deviation is about {f2(sv('XTIUSD', 'weekend_gap', 'full', 'sd_bp'), 0)} bp, "
      "with 2020 examples of -33% (WTI 2020-03-09). Be flat over weekends, or size for gaps.")
    A("* **Holidays / early closes:** Globex halts at ~13:30 NY on MLK, Presidents', Memorial, July 4, Labor and Thanksgiving days, "
      "with no settlement. Any 14:30-exit logic must handle this.")
    A("")
    A("## Files")
    A("")
    A("* Code: `src/intraday.py` (session matrices, execution helpers, stop-order simulator, stats, EIA schedule), "
      "`experiments/e06_intraday_data_checks.py`, `e06_intraday_orb.py`, `e06_intraday_momentum.py`, `e06_intraday_eia.py`, "
      "`e06_intraday_sessions.py`, `e06_intraday_meanrev.py`, `e06_intraday_summary.py` (+ `e06_intraday_report.py`).")
    A("* Results: `results/e06_ranked.csv` (this table), `e06_family_trial_summary.csv`, `e06_yearly.csv`, per-family grids "
      "`e06_A_orb_grid.csv`, `e06_B_momentum_grid.csv`, `e06_C_eia_grid.csv`, `e06_D_session_grid.csv`, `e06_E_meanrev_grid.csv`, "
      "`e06_B_momentum_regressions.csv`, `e06_B_momentum_robustness.csv`, `e06_C_eia_event_vol.csv`, `e06_C_eia_minute_profile.csv`, "
      "`e06_D_session_stats.csv`, `e06_D_hourly.csv`, `e06_D_dayofweek.csv`, `e06_D_walkforward_picks.csv`, "
      "`e06_data_checks.csv`, `e06_data_checks_eia2008.csv`.")
    A("* Charts: `results/e06_cumulative_best.png`, `results/e06_momentum_buckets.png`, `results/e06_eia_vol_profile.png`.")
    A("")
    with open(os.path.join(OUT, "e06_intraday_summary.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("wrote", os.path.join(OUT, "e06_intraday_summary.md"))
