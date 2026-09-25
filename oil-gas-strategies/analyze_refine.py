import itertools
import numpy as np, pandas as pd
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 300)
df = pd.read_parquet('results/sweep_refine.parquet')
K = ['imp_n', 'imp_k', 'cons_m', 'box_f', 'exit']
reg = 'futures'
w = df.pivot_table(index=K, columns='set', values=[f'{reg}_{p}_{m}' for p in ['p1', 'p2', 'p3', 'p4'] for m in ['n', 'sumR']])
w.columns = [f'{s}|{c}' for c, s in w.columns]
w = w.fillna(0)
def pooled(w, sets, p):
    n = sum(w.get(f'{s}|{reg}_{p}_n', 0) for s in sets)
    r = sum(w.get(f'{s}|{reg}_{p}_sumR', 0) for s in sets)
    return n, r / np.where(n > 0, n, np.nan)
S3 = ['WTI_oanda', 'WTI_eia', 'BRENT_eia']
E2 = ['WTI_eia', 'BRENT_eia']
out = pd.DataFrame(index=w.index)
out['n_p2'], out['R_p2'] = pooled(w, S3, 'p2')
out['n_p3'], out['R_p3'] = pooled(w, S3, 'p3')
out['n_p4'], out['R_p4'] = pooled(w, E2, 'p4')
out['n_p1'], out['R_p1'] = pooled(w, E2, 'p1')
out['R_p2_oanda'] = w['WTI_oanda|futures_p2_sumR'] / w['WTI_oanda|futures_p2_n'].replace(0, np.nan)
out['R_p3_oanda'] = w['WTI_oanda|futures_p3_sumR'] / w['WTI_oanda|futures_p3_n'].replace(0, np.nan)
out = out.reset_index()
# neighbourhood smoothing of the DESIGN metric (p2) over +-1 grid step in each detector dimension (same exit)
lv = {k: sorted(out[k].unique()) for k in ['imp_n', 'imp_k', 'cons_m', 'box_f']}
key = {tuple(r[k] for k in K): i for i, r in out.iterrows()}
nb = []
for i, r in out.iterrows():
    idx = [lv[k].index(r[k]) for k in ['imp_n', 'imp_k', 'cons_m', 'box_f']]
    vals, ns = [], []
    for d in itertools.product([-1, 0, 1], repeat=4):
        j = [idx[q] + d[q] for q in range(4)]
        if any(jj < 0 or jj >= len(lv[k]) for jj, k in zip(j, ['imp_n', 'imp_k', 'cons_m', 'box_f'])):
            continue
        kk = tuple(lv[k][jj] for jj, k in zip(j, ['imp_n', 'imp_k', 'cons_m', 'box_f'])) + (r['exit'],)
        if kk in key:
            o = out.loc[key[kk]]
            if o.n_p2 > 0:
                vals.append(o.R_p2 * o.n_p2); ns.append(o.n_p2)
    nb.append(sum(vals) / sum(ns) if ns else np.nan)
out['R_p2_nbhd'] = nb
out.to_parquet('results/refine_scored.parquet')
print('=== by exit: median over all detector configs (pooled WTI_oanda+WTI_eia+Brent_eia for p2,p3; EIA for p1,p4)')
print(out.groupby('exit')[['R_p1', 'R_p2', 'R_p3', 'R_p4']].median().round(3))
print('fraction of configs positive:')
print(out.groupby('exit')[['R_p1', 'R_p2', 'R_p3', 'R_p4']].agg(lambda x: (x > 0).mean()).round(2))
for dim in ['imp_n', 'imp_k', 'cons_m', 'box_f']:
    print('=== marginal by', dim, '(median over other dims, all exits)')
    print(out.groupby(dim)[['n_p2', 'R_p2', 'R_p3', 'R_p4', 'R_p1']].median().round(3))
sel = out[(out.n_p2 >= 60)].sort_values('R_p2_nbhd', ascending=False)
print('=== top 25 by NEIGHBOURHOOD design score (p2 only), with later periods shown')
print(sel.head(25).round(3).to_string(index=False))
