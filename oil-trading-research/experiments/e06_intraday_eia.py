"""E06-C  EIA report reaction.

Events (ix.eia_schedule): crude Weekly Petroleum Status Report (Wed 10:30 ET; holiday weeks Thu 10:30 until
Sep 2008 / Thu 11:00 from Oct 2008) traded in XTIUSD; natural-gas storage report (Thu 10:30 ET, holiday
weeks dropped) traded in XNGUSD.  Jun-Dec 2008 the release registers at 10:35 in this feed.

Rules (T = release minute; prices known at time t = last close before t; fills = next bar open):
  (i)  continuation: s = ln P(T+w)/P(T), w in {5, 15} min.  If |s| > k x trailing median |s| of the
       previous 20 events (k in 0/1/1.5/2), enter in sign(s) at T+w, exit at T+60 or 14:30.
  (ii) fade: same trigger, trade -sign(s), exit at T+w+15, T+w+30, T+60 or 14:30.
  (iii) pre-report drift: hold 09:00 -> T-1 (long or short; direction to be read from IS).
Costs: 2 x COST_PER_SIDE, plus STOP_SLIPPAGE on any side executed within 15 min after the release
(spreads are wide in the event window).
Also: event-window volatility vs normal days (risk management) and the average |1-min return| profile.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from src import intraday as ix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results")
PAIRS = [("XTIUSD", "crude"), ("XNGUSD", "gas")]


def px_before_rows(S, rows, cols, max_age=20):
    """px_before at per-event columns."""
    out = np.full(len(rows), np.nan)
    for i, (r, c) in enumerate(zip(rows, cols)):
        j = S.prv[r, c - 1]
        if j >= 0 and c - j <= max_age:
            out[i] = S.C[r, j]
    return out


def px_exec_rows(S, rows, cols, max_wait=10, fallback=False):
    px = np.full(len(rows), np.nan)
    jc = np.full(len(rows), -1)
    for i, (r, c) in enumerate(zip(rows, cols)):
        c = min(c, ix.NCOL - 1)
        j = S.nxt[r, c]
        if j < ix.NCOL and j - c <= max_wait:
            px[i], jc[i] = S.O[r, j], j
        elif fallback:
            jj = S.prv[r, c - 1]
            if jj >= 0:
                px[i], jc[i] = S.C[r, jj], c - 1
    return px, jc


def vol_table(S, sym, kind, E):
    """Event days vs normal days (valid Mon/Tue/Fri, i.e. no EIA release) at the same clock time T.
    RMS moves in bps; windows are measured with prices known at each time (last close before)."""
    out = []
    dow = S.dates.dayofweek.to_numpy()
    normal = S.valid & np.isin(dow, [0, 1, 4])
    for grp, sub in E.groupby("time"):
        T = ix.col(grp)
        wins = {"pre T-30->T": (T - 30, T), "T->T+1": (T, T + 1), "T->T+5": (T, T + 5), "T->T+15": (T, T + 15),
                "T->T+60": (T, T + 60), "T->14:30": (T, ix.col("14:30")), "09:00->14:30": (ix.col("09:00"), ix.col("14:30"))}
        is_ev = np.zeros(S.n, bool)
        is_ev[sub["row"].to_numpy()] = True
        for wname, (a, b) in wins.items():
            r = np.log(ix.px_before(S, b + 1 if wname == "T->T+1" else b, max_age=30) / ix.px_before(S, a, max_age=30))
            if wname == "T->T+1":  # the release minute itself: close of minute T vs close of minute T-1
                r = np.log(ix.px_before(S, T + 1, max_age=30) / ix.px_before(S, T, max_age=30))
            e, o = r[is_ev], r[normal]
            rms = lambda x: np.sqrt(np.nanmean(x ** 2)) * 1e4
            out.append({"sym": sym, "event": kind, "time": grp, "window": wname, "n_events": int(np.isfinite(e).sum()),
                        "rms_event_bps": rms(e), "rms_normal_bps": rms(o), "ratio_vs_normal": rms(e) / rms(o),
                        "p99_abs_event_bps": np.nanpercentile(np.abs(e), 99) * 1e4,
                        "p99_abs_normal_bps": np.nanpercentile(np.abs(o), 99) * 1e4,
                        "share_event_gt_1pct": float(np.nanmean(np.abs(e) > 0.01)),
                        "share_normal_gt_1pct": float(np.nanmean(np.abs(o) > 0.01))})
    return out


def minute_profile(S, E):
    """Average |1-min return| (bps) for minutes 10:00..11:30 on event days vs all other valid days."""
    r1 = np.abs(np.diff(np.log(S.C), axis=1)) * 1e4  # r1[:, j-1] = |ln C_j / C_{j-1}| (consecutive bars only)
    a, b = ix.col("09:50"), ix.col("11:40")
    ev = np.zeros(S.n, bool)
    reg = E[E["time"].isin(["10:30"])]
    ev[reg["row"].to_numpy()] = True
    other = S.valid & ~np.isin(np.arange(S.n), E["row"].to_numpy())
    cols = np.arange(a, b)
    prof_ev = np.nanmean(r1[ev][:, cols - 1], axis=0)
    prof_ot = np.nanmean(r1[other][:, cols - 1], axis=0)
    return pd.DataFrame({"time": [ix.hhmm(c) for c in cols], "event_abs_bps": prof_ev, "other_abs_bps": prof_ot})


def main():
    grid, store, vols, profs = [], {}, [], []
    for sym, kind in PAIRS:
        S = ix.session_matrix(sym)
        E = ix.eia_schedule(S, kind)
        vols += vol_table(S, sym, kind, E)
        # cross-impact: the other report on this instrument (risk table only)
        other_kind = "gas" if kind == "crude" else "crude"
        vols += vol_table(S, sym, other_kind, ix.eia_schedule(S, other_kind))
        p = minute_profile(S, E)
        p["sym"] = sym
        profs.append(p)

        rows = E["row"].to_numpy()
        T = E["col"].to_numpy()
        p0 = px_before_rows(S, rows, T)
        c1430 = ix.col("14:30")
        for w in [5, 15]:
            pw = px_before_rows(S, rows, T + w)
            s = np.log(pw / p0)
            med = pd.Series(np.abs(s)).rolling(20, min_periods=8).median().shift(1).to_numpy()
            ep, ec = px_exec_rows(S, rows, T + w, max_wait=10)
            ns_entry = 1.0  # entry inside the 15-minute post-release window
            for k in [0.0, 1.0, 1.5, 2.0]:
                trig = np.isfinite(s) & np.isfinite(med) & (np.abs(s) > k * med) & (s != 0)
                sg = np.where(trig, np.sign(s), 0.0)
                exits = {"T+60": T + 60, "14:30": np.full(len(T), c1430)}
                for mode in ["cont", "fade"]:
                    ex = dict(exits)
                    if mode == "fade":
                        ex = {f"T+{w + 15}": T + w + 15, f"T+{w + 30}": T + w + 30, **exits}
                    for xname, xcol in ex.items():
                        xp, xc = px_exec_rows(S, rows, xcol, max_wait=30, fallback=True)
                        n_exit = np.where(xc - T < 15, 1.0, 0.0)
                        d = sg if mode == "cont" else -sg
                        tr = ix.make_trades(S, rows, d, ep, xp, ec, xc, n_stop=ns_entry + n_exit)
                        key = f"{sym}|eia_{mode}|w{w}|k{k:g}|{xname}"
                        store[key] = tr
                        grid.append({"key": key, "sym": sym, "family": "C_eia", "mode": mode, "w": w, "k": k,
                                     "exit": xname, **ix.evaluate(tr, S)})
        # (iii) pre-report drift 09:00 -> T-1
        ep, ec = px_exec_rows(S, rows, np.full(len(T), ix.col("09:00")), max_wait=10)
        xp, xc = px_exec_rows(S, rows, T - 1, max_wait=0, fallback=True)
        for dname, dsign in [("long", 1.0), ("short", -1.0)]:
            tr = ix.make_trades(S, rows, dsign, ep, xp, ec, xc, n_stop=0)
            key = f"{sym}|eia_pre|{dname}|09:00->T-1"
            store[key] = tr
            grid.append({"key": key, "sym": sym, "family": "C_eia", "mode": "pre", "w": 0, "k": 0, "exit": "T-1",
                         "dir": dname, **ix.evaluate(tr, S)})
        # pre-report drift on non-event same weekday, for comparison (not a trial)
        dow = S.dates[rows[0]].dayofweek
        non = np.where(S.valid & (S.dates.dayofweek == dow) & ~np.isin(np.arange(S.n), rows))[0]
        a = ix.px_exec(S, ix.col("09:00"), max_wait=10)[0][non]
        b = ix.px_before(S, ix.col("10:30"))[non]
        ev_ret = np.log(xp / ep)
        nn = np.log(b / a)
        print(f"{sym} {kind}: pre-report drift 09:00->T-1 mean {np.nanmean(ev_ret) * 1e4:.1f} bp "
              f"(t={np.nanmean(ev_ret) / np.nanstd(ev_ret) * np.sqrt(np.isfinite(ev_ret).sum()):.2f}, n={np.isfinite(ev_ret).sum()}); "
              f"same weekday non-event 09:00->10:29 mean {np.nanmean(nn) * 1e4:.1f} bp (t={np.nanmean(nn) / np.nanstd(nn) * np.sqrt(np.isfinite(nn).sum()):.2f})")
    G = pd.DataFrame(grid)
    G.to_csv(os.path.join(OUT, "e06_C_eia_grid.csv"), index=False)
    V = pd.DataFrame(vols)
    V.to_csv(os.path.join(OUT, "e06_C_eia_event_vol.csv"), index=False)
    P = pd.concat(profs)
    P.to_csv(os.path.join(OUT, "e06_C_eia_minute_profile.csv"), index=False)
    pd.to_pickle(store, os.path.join(ix.CACHE, "e06_C_trades.pkl"))
    pd.set_option("display.width", 250)
    print(V[V.time.isin(["10:30", "11:00"])][["sym", "event", "time", "window", "n_events", "rms_event_bps", "rms_normal_bps",
                                               "ratio_vs_normal", "p99_abs_event_bps", "p99_abs_normal_bps", "share_event_gt_1pct", "share_normal_gt_1pct"]].round(2).to_string(index=False))
    show = ["key", "is_sharpe", "oos_sharpe", "full_sharpe", "full_gross_sharpe", "oos_gross_sharpe", "full_trades_py",
            "full_avg_bps", "full_avg_gross_bps", "is_avg_gross_bps", "oos_avg_gross_bps", "full_hit"]
    for sym, _ in PAIRS:
        g = G[G.sym == sym].sort_values("is_sharpe", ascending=False)
        print(f"\n{sym}: {len(g)} variants, top 12 by IS net Sharpe")
        print(g[show].head(12).round(3).to_string(index=False))
        print("gross-positive share OOS:", round((g.oos_sharpe_0x > 0).mean(), 2))


if __name__ == "__main__":
    main()
