"""Collect every number the report shows -> results/report_data.json (+ CSV tables)."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
import strategies as S, metrics as M, data as D
RES = os.path.join(os.path.dirname(__file__), "..", "results")
rd = lambda x, k=3: None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), k)

r1 = pd.read_parquet(os.path.join(RES, "trades_all.parquet"))
r2 = pd.read_parquet(os.path.join(RES, "trades_round2.parquet"))
r3 = pd.read_parquet(os.path.join(RES, "trades_round3.parquet"))
for t in (r1, r2, r3):
    t["gross_r"] = t.gross / t.risk

def summ(g, nsym):
    s = M.summarize(g, n_symbols=nsym)
    s["gross_r"] = g.gross_r.mean()
    s["stress"] = M.stress_r(g).mean()
    s["sym_pos"] = (g.groupby("symbol").r.mean() > 0).mean()
    s["n_sym"] = g.symbol.nunique()
    return s

fam_rows, cfg_rows = [], []
for fam, f in S.FAMILIES.items():
    g = r1[r1.family == fam]
    nsym = len(f["universe"])
    per_cfg = {cid: summ(gg, nsym) | {"cfg": gg.cfg.iloc[0]} for cid, gg in g.groupby("cfg_id")}
    for cid, s in per_cfg.items():
        cfg_rows.append(dict(family=fam, cfg_id=cid, cfg=s["cfg"], n=s["n"], avg_r=rd(s["avg_r"]), h1=rd(s["h1_avg"]), h2=rd(s["h2_avg"]), t=rd(s["t"], 2), round=1))
    d = per_cfg["default"]
    best_id = max(per_cfg, key=lambda k: per_cfg[k]["avg_r"])
    b = per_cfg[best_id]
    fam_rows.append(dict(family=fam, universe=f["universe"], n_cfg=len(per_cfg),
        share_pos=rd(np.mean([v["avg_r"] > 0 for v in per_cfg.values()]), 2),
        share_both=rd(np.mean([(v["h1_avg"] > 0) and (v["h2_avg"] > 0) for v in per_cfg.values()]), 2),
        d_n=d["n"], d_week=rd(d["per_week"], 1), d_week_all=rd(d["n"] / M.WEEKS, 1), d_win=rd(d["win"], 2), d_gross=rd(d["gross_r"]), d_net=rd(d["avg_r"]),
        d_t=rd(d["t"], 2), d_h1=rd(d["h1_avg"]), d_h2=rd(d["h2_avg"]), d_hold=rd(d["hold_h"], 1), d_pf=rd(d["pf"], 2), d_cfg=d["cfg"],
        b_cfg=b["cfg"], b_net=rd(b["avg_r"]), b_t=rd(b["t"], 2), b_h1=rd(b["h1_avg"]), b_h2=rd(b["h2_avg"]), b_n=b["n"]))

# round 2 (design H1 -> test H2) and round 3
r2_rows = []
for fam, f in S.ROUND2.items():
    g = r2[r2.family == fam]
    h1, h2 = g[g.entry_time < M.SPLIT], g[g.entry_time >= M.SPLIT]
    r2_rows.append(dict(family=fam, universe=f["universe"], cfg=json.dumps(f["default"], sort_keys=True),
                        h1_n=len(h1), h1_r=rd(h1.r.mean()), h1_t=rd(h1.r.mean() / h1.r.std() * np.sqrt(len(h1)), 2),
                        h2_n=len(h2), h2_r=rd(h2.r.mean()), h2_t=rd(h2.r.mean() / h2.r.std() * np.sqrt(len(h2)), 2)))
r3_rows = []
for (fam, cid), g in r3.groupby(["family", "cfg_id"]):
    s = summ(g, len(S.ROUND3[fam]["universe"]))
    jp = g[g.symbol.isin(S.JPY)]
    r3_rows.append(dict(family=fam, cfg=g.cfg.iloc[0], n=s["n"], avg_r=rd(s["avg_r"]), t=rd(s["t"], 2), h1=rd(s["h1_avg"]), h2=rd(s["h2_avg"]),
                        jpy=rd(jp.r.mean()) if len(jp) else None, week=rd(s["per_week"], 2)))
    if not fam.startswith("R3c"):
        cfg_rows.append(dict(family=fam, cfg_id=cid, cfg=g.cfg.iloc[0], n=s["n"], avg_r=rd(s["avg_r"]), h1=rd(s["h1_avg"]), h2=rd(s["h2_avg"]), t=rd(s["t"], 2), round=3))

# instrument-level multiple-testing screen
allt = pd.concat([r1, r2, r3[~r3.family.str.startswith("R3c")]], ignore_index=True)
def tstat(x):
    return x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 2 and x.std() > 0 else np.nan
lvl = allt.groupby(["family", "cfg", "symbol"]).r.agg(["size", tstat]).rename(columns={"size": "n", "tstat": "t"})
lvl = lvl[lvl.n >= 30]
screen = dict(tests=int(len(lvl)), t_ge2=int((lvl.t >= 2).sum()), t_le_m2=int((lvl.t <= -2).sum()), chance_t_ge2=round(0.0228 * len(lvl)))

# variance ratios (from e02 output recomputed quickly)
from engine import rollover_mask
vr_rows = []
def vr(r, q):
    r = r.dropna(); x = r.rolling(q).sum().dropna()
    return x.var() / (q * r.var())
for sym in D.ALL:
    m = D.load_minutes(sym); m = m[rollover_mask(m.index)]
    b = D.resample(m, "15min"); r = np.log(b.close).diff()
    r[(b.index.to_series().diff() > pd.Timedelta("15min")).values] = np.nan
    h1, h2 = r[r.index < M.SPLIT], r[r.index >= M.SPLIT]
    vr_rows.append(dict(sym=sym, h1_4h=rd(vr(h1, 16)), h2_4h=rd(vr(h2, 16)), h1_1d=rd(vr(h1, 64)), h2_1d=rd(vr(h2, 64))))

meta = dict(start=str(D.load_minutes("EURUSD").index[0].date()), end=str(D.load_minutes("EURUSD").index[-1].date()),
            weeks=round(M.WEEKS, 1), trades_simulated=int(len(r1) + len(r2) + len(r3)),
            configs=len(cfg_rows), families=len(S.FAMILIES) + len(S.ROUND2) + 2)
out = dict(meta=meta, families=fam_rows, round2=r2_rows, round3=r3_rows, configs=cfg_rows, screen=screen, vr=vr_rows)
json.dump(out, open(os.path.join(RES, "report_data.json"), "w"), indent=1, default=str)
pd.DataFrame(fam_rows).to_csv(os.path.join(RES, "round1_families.csv"), index=False)
pd.DataFrame(cfg_rows).to_csv(os.path.join(RES, "all_configs.csv"), index=False)
print(json.dumps(meta), json.dumps(screen))
print(pd.DataFrame(fam_rows)[["family", "n_cfg", "share_pos", "share_both", "d_n", "d_week", "d_gross", "d_net", "d_t", "d_h1", "d_h2", "b_net", "b_t"]].to_string(index=False))
