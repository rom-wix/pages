"""Round 3: multi-day 4h-chart strategies (Donchian breakout, index dip-buy) + random-long drift benchmark."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
import strategies as S, runner as RN, metrics as M
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 90)
S.FAMILIES.update(S.ROUND3)
tr = RN.run_families(list(S.ROUND3), procs=4)
tr.to_parquet(os.path.join(os.path.dirname(__file__), "..", "results", "trades_round3.parquet"))
rows = []
for (fam, cid), g in tr.groupby(["family", "cfg_id"]):
    s = M.summarize(g, n_symbols=len(S.ROUND3[fam]["universe"]))
    s.update(family=fam, cfg=g.cfg.iloc[0], sym_pos=(g.groupby("symbol").r.mean() > 0).mean(), stress=M.stress_r(g).mean())
    for grp, syms in (("jpy", ["USDJPY", "EURJPY"]), ("fx_other", ["EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "EURGBP"]), ("idx", list(S.D.INDICES))):
        gg = g[g.symbol.isin(syms)]
        s[grp] = gg.r.mean() if len(gg) else np.nan
    rows.append(s)
r = pd.DataFrame(rows)
cols = ["family", "cfg", "n", "per_week", "win", "avg_r", "stress", "t", "h1_avg", "h2_avg", "sym_pos", "hold_h", "jpy", "fx_other", "idx"]
print(r.sort_values(["family", "avg_r"], ascending=[True, False])[cols].round(3).to_string(index=False))
