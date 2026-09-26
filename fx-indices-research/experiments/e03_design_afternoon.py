"""Design (Feb-May only): US index afternoon momentum. At signal time T (NY), side = sign(P_T / P_ref - 1);
forward = return from T to 15:58 NY. Report mean signed forward return (bp) and t by |move|/ATR bucket."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
import data as D, strategies as S
pd.set_option("display.width", 250)
SPLIT = pd.Timestamp("2026-06-01")
HALF = sys.argv[1] if len(sys.argv) > 1 else "H1"

def px_at(lm, tod):
    return lm[lm.tod == tod].groupby("date")["close"].last()

rows = []
for sym in ["US500", "NAS100", "US30", "US2000"]:
    lm = S.local_minutes(sym, "America/New_York")
    atr = S.atr_prev(sym)
    sess = S.session_stats(sym, "America/New_York", S.hm("09:30"), S.hm("16:00"))
    sess = sess[sess.first_tod == S.hm("09:30")]
    prev_close = sess.close.shift()
    open_ = sess.open
    p_end = px_at(lm, S.hm("15:57"))
    for T in ["11:00", "12:00", "13:00", "14:00", "15:00", "15:30"]:
        pT = px_at(lm, S.hm(T) - 1)
        for ref_name, ref in (("prev_close", prev_close), ("open", open_)):
            df = pd.concat([pT, ref, p_end, atr], axis=1, keys=["pT", "ref", "end", "atr"]).dropna()
            df = df[(df.index < SPLIT) if HALF == "H1" else (df.index >= SPLIT)]
            mv = (df.pT - df.ref) / df.atr
            fwd = np.sign(df.pT - df.ref) * (np.log(df.end / df.pT)) * 1e4
            for lo in (0.0, 0.25, 0.5, 0.75):
                sel = mv.abs() >= lo
                f = fwd[sel]
                rows.append(dict(sym=sym, T=T, ref=ref_name, min_mv=lo, n=len(f), mean_bp=f.mean(),
                                 t=f.mean() / f.std() * np.sqrt(len(f)) if len(f) > 2 else np.nan))
r = pd.DataFrame(rows)
piv = r.pivot_table(index=["ref", "min_mv", "T"], columns="sym", values="mean_bp").round(1)
piv["avg"] = piv.mean(axis=1).round(1)
tt = r.pivot_table(index=["ref", "min_mv", "T"], columns="sym", values="t").round(1)
nn = r.pivot_table(index=["ref", "min_mv", "T"], columns="sym", values="n")
print(f"{HALF}: mean signed afternoon return (bp)"); print(piv.to_string())
print(f"\n{HALF}: t-stats"); print(tt.to_string())
print(f"\n{HALF}: n (US500)"); print(nn["US500"].unstack("T").to_string())
