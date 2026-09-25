"""E06-D  Time-of-day and session effects.

  * hourly returns (NY clock hours) - mean (bp), t-stat, IS vs OOS
  * sessions: Asia 18:00-02:00, London 02:00-08:00, NY pre-open 08:00-09:00, NY main 09:00-14:30,
    post-settlement 14:30-17:00, plus the 17:00->18:00 break gap (Tue-Fri) and the weekend gap
    (Fri 17:00 -> Sun 18:00 reopen)
  * overnight (14:30 -> next session 09:00) vs intraday (09:00 -> 14:30) decomposition
  * day-of-week (close-to-close 17:00->17:00 and 09:00->14:30)
  * trading versions: hold each session every day (long / short), overnight hold with financing,
    Sunday-gap fade/follow, and a walk-forward session picker (trailing 3y t-stat, re-picked yearly).
Session returns for statistics use prices known at the boundary (last close before the time);
trading versions use market-order fills (next bar open) and charge 2 x COST_PER_SIDE per round trip,
plus FIN_MARKUP/365 per calendar night for positions held through 17:00.
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
SYMS = ["XTIUSD", "XNGUSD"]
SESS = {"asia": ("18:00", "02:00"), "london": ("02:00", "08:00"), "ny_pre": ("08:00", "09:00"),
        "ny_main": ("09:00", "14:30"), "post": ("14:30", "17:00")}


def tstat(x):
    x = pd.Series(x).dropna()
    return x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 2 and x.std() > 0 else np.nan


def split_stats(s: pd.Series, name: str, sym: str, extra=None):
    out = []
    for p, (a, b) in ix.PERIODS.items():
        x = s.dropna()
        if a is not None:
            x = x[x.index >= a]
        if b is not None:
            x = x[x.index <= b]
        out.append({"sym": sym, "item": name, "period": p, "n": len(x), "mean_bp": x.mean() * 1e4,
                    "sd_bp": x.std() * 1e4, "t": tstat(x), "ann_sharpe_gross": x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else np.nan,
                    **(extra or {})})
    return out


def reopen_px(S):
    px, jc = ix.px_exec(S, 0, max_wait=90)
    return px


def prev_close17(S):
    c = ix.px_before(S, ix.col("17:00"))
    return pd.Series(np.where(S.valid, c, np.nan)).ffill().shift(1).to_numpy()


def session_returns(S):
    P = lambda t: ix.px_before(S, ix.col(t))
    ro = reopen_px(S)
    d = pd.DataFrame(index=S.dates)
    d["asia"] = np.log(P("02:00") / ro)
    d["london"] = np.log(P("08:00") / P("02:00"))
    d["ny_pre"] = np.log(P("09:00") / P("08:00"))
    d["ny_main"] = np.log(P("14:30") / P("09:00"))
    d["post"] = np.log(P("17:00") / P("14:30"))
    gap = np.log(ro / prev_close17(S))
    mon = S.dates.dayofweek == 0
    d["break_gap_tue_fri"] = np.where(~mon, gap, np.nan)
    d["weekend_gap"] = np.where(mon, gap, np.nan)
    p1430 = P("14:30")
    prev1430 = pd.Series(np.where(S.valid, p1430, np.nan)).ffill().shift(1).to_numpy()
    d["overnight_1430_0900"] = np.log(P("09:00") / prev1430)
    d["intraday_0900_1430"] = d["ny_main"]
    d["close_to_close"] = np.log(P("17:00") / prev_close17(S))
    return d[S.valid]


def hourly_returns(S):
    out = {}
    ro = reopen_px(S)
    for h in range(24):
        if h == 17:
            continue
        a = f"{h:02d}:00"
        b = f"{(h + 1) % 24:02d}:00"
        pa = ro if h == 18 else ix.px_before(S, ix.col(a))
        pb = ix.px_before(S, ix.col(b)) if h != 16 else ix.px_before(S, ix.col("17:00"))
        out[h] = np.log(pb / pa)
    return pd.DataFrame(out, index=S.dates)[S.valid]


def hold_trades(S, start, end, direction, nights=0, entry_row_shift=0):
    """Hold from `start` to `end` (same session) every valid day."""
    rows = np.where(S.valid)[0]
    ep, ec = ix.px_exec(S, ix.col(start), max_wait=30) if start != "18:00" else ix.px_exec(S, 0, max_wait=90)
    xp, xc = ix.px_exec(S, ix.col(end), max_wait=30, fallback_before=True) if end != "17:00" else \
        (ix.px_before(S, ix.col("17:00")), np.full(S.n, ix.col("17:00") - 1))
    return ix.make_trades(S, rows, direction, ep[rows], xp[rows], ec[rows], xc[rows], n_stop=0, nights=nights)


def overnight_trades(S, direction):
    """Enter at 14:30 (market) on session d, exit 09:00 on the next valid session; financing per night."""
    v = np.where(S.valid)[0]
    ep, ec = ix.px_exec(S, ix.col("14:30"), max_wait=30, fallback_before=True)
    xp, xc = ix.px_exec(S, ix.col("09:00"), max_wait=30)
    r_in, r_out = v[:-1], v[1:]
    nights = (S.dates[r_out] - S.dates[r_in]).days.to_numpy()
    tr = ix.make_trades(S, r_out, direction, ep[r_in], xp[r_out], ec[r_in], xc[r_out], n_stop=0, nights=nights)
    return tr  # P&L booked on the exit date


def sunday_gap_trades(S, mode, exit_t, thr, entry_t="18:05"):
    """Monday sessions: gap = Fri 17:00 -> Sun reopen.  Enter at 18:05 Sunday (market; STOP_SLIPPAGE
    added for the wide Sunday-open spread), exit at exit_t on the same (Monday) session."""
    rows = np.where(S.valid & (S.dates.dayofweek == 0))[0]
    gap = np.log(reopen_px(S) / prev_close17(S))[rows]
    ep, ec = ix.px_exec(S, ix.col(entry_t), max_wait=30)
    xp, xc = ix.px_exec(S, ix.col(exit_t), max_wait=30, fallback_before=True)
    sg = np.where(np.abs(gap) > thr, np.sign(gap), 0.0)
    d = -sg if mode == "fade" else sg
    return ix.make_trades(S, rows, d, ep[rows], xp[rows], ec[rows], xc[rows], n_stop=1)


def dow_trades(S, weekday, direction):
    """Hold 09:00 -> 14:30 on one weekday only."""
    tr = hold_trades(S, "09:00", "14:30", direction)
    return tr[pd.DatetimeIndex(tr["date"]).dayofweek == weekday].reset_index(drop=True)


def walk_forward(S, sym, cands, min_t=2.0):
    """Each year Y: compute the GROSS t-stat of every candidate's trade returns over years Y-3..Y-1,
    pick the candidate with the largest |t| (if |t| > min_t, else stay flat), and trade it in the sign
    of its trailing mean for all of Y.  Costs apply to the traded P&L.  `cands`: name -> long trades."""
    picks, parts = [], []
    years = sorted(set(S.dates[S.valid].year))
    for Y in years:
        if Y < years[0] + 3:
            continue
        best, bt_ = None, 0.0
        for name, tr in cands.items():
            yy = pd.DatetimeIndex(tr["date"]).year
            t = tstat(tr["gross"][(yy >= Y - 3) & (yy <= Y - 1)])
            if np.isfinite(t) and abs(t) > abs(bt_):
                best, bt_ = name, t
        if best is None or abs(bt_) < min_t:
            picks.append({"sym": sym, "year": Y, "pick": "flat", "dir": "", "trailing_gross_t": bt_})
            continue
        tr = cands[best]
        yy = pd.DatetimeIndex(tr["date"]).year
        sub = tr[yy == Y].copy()
        if bt_ < 0:
            sub["dir"] = -sub["dir"]
            sub["gross"] = -sub["gross"]
        parts.append(sub)
        picks.append({"sym": sym, "year": Y, "pick": best, "dir": "long" if bt_ > 0 else "short", "trailing_gross_t": bt_})
    tr = pd.concat(parts, ignore_index=True) if parts else ix.make_trades(S, [], 0, [], [])
    return tr, picks


def sunday_gap_robustness():
    """Robustness of the Sunday-gap fade (checks, not selection trials): entry delay, exit time, threshold,
    cost multiple, ex-2020."""
    out = []
    for sym in ["XTIUSD", "XNGUSD"]:
        S = ix.session_matrix(sym)
        dates = ix.valid_dates(S)
        grid = [("18:05", "09:00", 0.005, m) for m in [0.0, 1.0, 2.0, 3.0]]
        grid += [(e, "09:00", 0.005, 1.0) for e in ["18:15", "18:30", "19:00", "20:00"]]
        grid += [("18:05", x, 0.005, 1.0) for x in ["02:00", "06:00", "12:00", "14:30"]]
        grid += [("18:05", "09:00", t, 1.0) for t in [0.0025, 0.01, 0.02]]
        for e, x, t, m in grid:
            tr = sunday_gap_trades(S, "fade", x, t, entry_t=e)
            row = {"sym": sym, "entry": e, "exit": x, "thr": t, "cost_mult": m}
            for p, (a, b) in ix.PERIODS.items():
                ps = ix.period_stats(tr, dates, a, b, mult=m)
                row[f"{p}_sharpe"] = ps.get("sharpe", np.nan)
                row[f"{p}_trades_py"] = ps.get("trades_py", np.nan)
                row[f"{p}_avg_bps"] = ps.get("avg_bps", np.nan)
            dn = ix.daily_pnl(tr, dates, m)
            x0 = dn[dn.index.year != 2020]
            row["full_ex2020_sharpe"] = ix.bt.sharpe(x0)
            row["oos_ex2020_sharpe"] = ix.bt.sharpe(x0[x0.index >= ix.OOS_START])
            out.append(row)
    return pd.DataFrame(out)


def main():
    stat_rows, hour_rows, grid, store, wf_picks, dow_rows = [], [], [], {}, [], []
    for sym in SYMS:
        S = ix.session_matrix(sym)
        d = session_returns(S)
        for c in d.columns:
            stat_rows += split_stats(d[c], c, sym)
        H = hourly_returns(S)
        for h in H.columns:
            hour_rows += split_stats(H[h], f"{h:02d}:00", sym, {"hour": h})
        # day of week
        for c in ["close_to_close", "intraday_0900_1430", "overnight_1430_0900"]:
            for wd in range(5):
                x = d[c][d.index.dayofweek == wd]
                dow_rows += split_stats(x, c, sym, {"weekday": ["Mon", "Tue", "Wed", "Thu", "Fri"][wd]})
        # ---- trading versions ----
        fns = {}
        for sname, (a, b) in SESS.items():
            fns[sname] = (lambda a, b: lambda dr: hold_trades(S, a, b, dr))(a, b)
        fns["overnight_1430_0900"] = lambda dr: overnight_trades(S, dr)
        for name, fn in fns.items():
            for dname, dr in [("long", 1.0), ("short", -1.0)]:
                tr = fn(dr)
                key = f"{sym}|session|{name}|{dname}"
                store[key] = tr
                grid.append({"key": key, "sym": sym, "family": "D_session", "item": name, "dir": dname, **ix.evaluate(tr, S)})
        for mode in ["fade", "follow"]:
            for xt in ["02:00", "09:00"]:
                for thr in [0.0, 0.005]:
                    tr = sunday_gap_trades(S, mode, xt, thr)
                    key = f"{sym}|sunday_gap|{mode}|{xt}|thr{thr:g}"
                    store[key] = tr
                    grid.append({"key": key, "sym": sym, "family": "D_session", "item": "sunday_gap", "dir": mode,
                                 "exit": xt, "thr": thr, **ix.evaluate(tr, S)})
        # day-of-week intraday holds (09:00 -> 14:30 on one weekday), long and short
        dnames = ["Mon", "Tue", "Wed", "Thu", "Fri"]
        for wd in range(5):
            for dname, dr in [("long", 1.0), ("short", -1.0)]:
                tr = dow_trades(S, wd, dr)
                key = f"{sym}|dow|{dnames[wd]}_0900_1430|{dname}"
                store[key] = tr
                grid.append({"key": key, "sym": sym, "family": "D_session", "item": f"dow_{dnames[wd]}", "dir": dname,
                             **ix.evaluate(tr, S)})
        # walk-forward pickers (one trial each): sessions only, and sessions + weekday holds
        cands = {name: fn(1.0) for name, fn in fns.items()}
        for label, cc in [("sessions", cands),
                          ("sessions+dow", {**cands, **{f"dow_{dnames[wd]}": dow_trades(S, wd, 1.0) for wd in range(5)}})]:
            tr, picks = walk_forward(S, sym, cc)
            key = f"{sym}|session_walkforward|{label}"
            store[key] = tr
            grid.append({"key": key, "sym": sym, "family": "D_session", "item": f"walkforward_{label}", "dir": "wf",
                         **ix.evaluate(tr, S)})
            wf_picks += [{**p, "candidates": label} for p in picks]
        # Sunday gap diagnostics: gap vs subsequent returns
        mon = S.valid & (S.dates.dayofweek == 0)
        gap = pd.Series(np.log(reopen_px(S) / prev_close17(S)), index=S.dates)[mon]
        for xt in ["20:00", "02:00", "09:00", "14:30"]:
            nxt = pd.Series(np.log(ix.px_before(S, ix.col(xt)) / reopen_px(S)), index=S.dates)[mon]
            z = pd.concat([gap.rename("gap"), nxt.rename("after")], axis=1).dropna()
            for p, (a, b) in ix.PERIODS.items():
                zz = z
                if a is not None:
                    zz = zz[zz.index >= a]
                if b is not None:
                    zz = zz[zz.index <= b]
                res = ix.nw_ols(zz["after"], zz[["gap"]], lags=2)
                stat_rows.append({"sym": sym, "item": f"sunday_gap_predicts_reopen->{xt}", "period": p, "n": len(zz),
                                  "mean_bp": np.nan, "sd_bp": np.nan, "t": res.tvalues[1], "slope": res.params[1],
                                  "ann_sharpe_gross": np.nan})
    ST = pd.DataFrame(stat_rows)
    ST.to_csv(os.path.join(OUT, "e06_D_session_stats.csv"), index=False)
    HR = pd.DataFrame(hour_rows)
    HR.to_csv(os.path.join(OUT, "e06_D_hourly.csv"), index=False)
    DW = pd.DataFrame(dow_rows)
    DW.to_csv(os.path.join(OUT, "e06_D_dayofweek.csv"), index=False)
    G = pd.DataFrame(grid)
    G.to_csv(os.path.join(OUT, "e06_D_session_grid.csv"), index=False)
    pd.DataFrame(wf_picks).to_csv(os.path.join(OUT, "e06_D_walkforward_picks.csv"), index=False)
    SG = sunday_gap_robustness()
    SG.to_csv(os.path.join(OUT, "e06_D_sunday_gap_robustness.csv"), index=False)
    pd.to_pickle(store, os.path.join(ix.CACHE, "e06_D_trades.pkl"))
    pd.set_option("display.width", 250)
    print(ST.pivot_table(index=["sym", "item"], columns="period", values=["mean_bp", "t"]).round(2).to_string())
    print(HR.pivot_table(index=["sym", "hour"], columns="period", values=["mean_bp", "t"]).round(2).to_string())
    print(DW.pivot_table(index=["sym", "item", "weekday"], columns="period", values=["mean_bp", "t"]).round(2).to_string())
    show = ["key", "is_sharpe", "oos_sharpe", "full_sharpe", "full_gross_sharpe", "oos_gross_sharpe", "full_trades_py",
            "full_avg_bps", "full_avg_gross_bps", "full_hit"]
    print(G[show].round(3).to_string(index=False))
    print(pd.DataFrame(wf_picks).to_string(index=False))
    print(SG.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
