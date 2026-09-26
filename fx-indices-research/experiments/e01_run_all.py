"""Stage 1: every family x every config x every symbol in its universe -> results/trades_all.parquet + summary."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
import runner as RN, strategies as S, metrics as M

OUT = os.path.join(os.path.dirname(__file__), "..", "results")
t = time.time()
tr = RN.run_families(list(S.FAMILIES), procs=4)
tr.to_parquet(os.path.join(OUT, "trades_all.parquet"))
print(f"{len(tr)} trades in {time.time()-t:.0f}s")

rows = []
for (fam, cid), g in tr.groupby(["family", "cfg_id"]):
    s = M.summarize(g, n_symbols=len(S.FAMILIES[fam]["universe"]))
    bs = M.by_symbol(g)
    s.update(family=fam, cfg_id=cid, cfg=g.cfg.iloc[0], sym_pos=float((bs.avg_r > 0).mean()), n_sym=len(bs),
             avg_r_stress=float(M.stress_r(g).mean()))
    rows.append(s)
summ = pd.DataFrame(rows)
summ.to_csv(os.path.join(OUT, "stage1_summary.csv"), index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 80)
cols = ["family", "cfg_id", "n", "per_week", "win", "avg_r", "avg_r_stress", "pf", "t", "sharpe", "max_dd_r", "h1_avg", "h2_avg", "sym_pos", "hold_h"]
print("\nDEFAULT configs:")
print(summ[summ.cfg_id == "default"][cols].round(3).to_string(index=False))
print("\nFamily distribution over all configs (avg R):")
fam = summ.groupby("family").agg(n_cfg=("avg_r", "size"), share_pos=("avg_r", lambda x: (x > 0).mean()),
                                 med_avg_r=("avg_r", "median"), best_avg_r=("avg_r", "max"), best_t=("t", "max"))
print(fam.round(3).to_string())
