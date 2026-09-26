"""Round 2: the four configs fixed from the first-half event study, simulated with costs; judged on Jun-Sep."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
import strategies as S, runner as RN, metrics as M
pd.set_option("display.width", 250)
S.FAMILIES.update(S.ROUND2)
out = []
for fam, f in S.ROUND2.items():
    trs = [RN.run_one(fam, "default", f["default"], s) for s in f["universe"]]
    tr = pd.concat([t for t in trs if len(t)], ignore_index=True)
    out.append(tr)
    for half, g in (("H1 (design)", tr[tr.entry_time < M.SPLIT]), ("H2 (test)", tr[tr.entry_time >= M.SPLIT])):
        s = M.summarize(g, n_symbols=len(f["universe"]))
        bs = g.groupby("symbol").r.mean()
        print(f"{fam:22s} {half:12s} n={s['n']:4d} /wk/sym={s['per_week']*2.0:4.1f} win={s['win']:.2f} avgR={s['avg_r']:+.3f} t={s['t']:+.2f} "
              f"PF={s['pf']:.2f} sumR={s['sum_r']:+.1f} stressR={M.stress_r(g).mean():+.3f} hold={s['hold_h']:.1f}h  by sym: " +
              " ".join(f"{k}:{v:+.2f}" for k, v in bs.items()))
pd.concat(out).to_parquet(os.path.join(os.path.dirname(__file__), "..", "results", "trades_round2.parquet"))
