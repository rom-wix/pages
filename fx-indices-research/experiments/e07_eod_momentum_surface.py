"""End-of-day momentum surface: signal window x size filter -> last-30-min trade, all 8 indices, by half.
Signals (all end 30 min before the cash close, T30): penult = T60->T30, h90 = T90->T30, session = open->T30,
day = prior cash close->T30. Filter |signal move| >= f * ATR. Trade T30 -> close-1min, SL 0.25 ATR. Costs as usual."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
import data as D, strategies as S, costs as K, metrics as M
from engine import simulate, MARKET
pd.set_option("display.width", 250)

def eod(sym, sig, fmin, sl_atr=0.25):
    tz, o, c = D.CASH_SESSION[sym]
    so, sc = S.hm(o), S.hm(c)
    lm = S.local_minutes(sym, tz)
    atr = S.atr_prev(sym)
    sess = S.session_stats(sym, tz, so, sc)
    sess = sess[sess.first_tod == so]
    at = lambda t: lm[lm.tod == t].groupby("date")["close"].last()
    p30 = at(sc - 31)
    ref = {"penult": at(sc - 61), "h90": at(sc - 91), "session": sess.open, "day": sess.close.shift()}[sig]
    rows = []
    for d in sess.index:
        a, e, r0 = atr.get(d, np.nan), p30.get(d, np.nan), ref.get(d, np.nan)
        if np.isnan(a) or np.isnan(e) or np.isnan(r0):
            continue
        mv = e - r0
        if abs(mv) < fmin * a or mv == 0:
            continue
        side = int(np.sign(mv))
        t0 = S.ts(d, sc - 30, tz)
        rows.append(dict(side=side, etype=MARKET, t_active=t0, t_expire=t0 + pd.Timedelta(minutes=3), entry_px=np.nan,
                         sl_px=e - side * sl_atr * a, tp_px=np.nan, t_exit=S.ts(d, sc - 1, tz), mv_atr=mv / a))
    od = pd.DataFrame(rows)
    if not len(od):
        return od
    m = D.load_minutes(sym)
    tr = simulate(m, od, K.cost_rt(sym), K.slip_base(sym), 0.1, 0.0)
    tr["symbol"] = sym
    return tr

res = []
alltr = []
for sig in ["penult", "h90", "session", "day"]:
    for f in [0.0, 0.1, 0.2, 0.3, 0.5]:
        trs = pd.concat([eod(s, sig, f) for s in D.INDICES], ignore_index=True)
        trs["sig"], trs["fmin"] = sig, f
        alltr.append(trs)
        for scope, syms in (("US", S.US_IDX), ("ROW", S.ROW_IDX), ("ALL", D.INDICES)):
            g = trs[trs.symbol.isin(syms)]
            h1, h2 = g[g.entry_time < M.SPLIT].r, g[g.entry_time >= M.SPLIT].r
            res.append(dict(sig=sig, fmin=f, scope=scope, n=len(g), avg_r=g.r.mean(), t=g.r.mean() / g.r.std() * np.sqrt(len(g)),
                            h1=h1.mean(), h2=h2.mean(), sym_pos=(g.groupby("symbol").r.mean() > 0).mean(),
                            gross_bp=(g.gross / g.entry * 1e4).mean()))
r = pd.DataFrame(res)
pd.concat(alltr).to_parquet(os.path.join(os.path.dirname(__file__), "..", "results", "eod_surface_trades.parquet"))
for scope in ("ALL", "US", "ROW"):
    print(f"\n{scope}:")
    print(r[r.scope == scope].pivot_table(index="sig", columns="fmin", values=["avg_r", "t", "h1", "h2", "n"]).round(2).to_string())
