import itertools
import numpy as np, pandas as pd
from ogslib import Market, detect_flags, non_overlap, set_costs
from system import run_system, perf, trades_from_setups, filter_vol, setups
pd.set_option('display.width', 220)
res = []
for name in ['WTI', 'NG']:
    mk = Market(name, '4h')
    for vf in [False, True]:
        for reg, mult in [('zero', 1), ('futures', 1), ('cfd', 1), ('cfd', 2)]:
            tr = run_system(mk, 'HYB', vf, regime=reg, cost_mult=mult)
            for lab, a, b in [('05-14', '2005', '2014-12-31'), ('15-20', '2015', '2020-04-30'), ('all', '2005', '2021')]:
                x = tr[(tr.entry_t >= a) & (tr.entry_t <= b)]
                p = perf(x); res.append(dict(mkt=name, ver='A+' if vf else 'A', cost=f'{reg}x{mult}', per=lab, n=p['n'], win=p.get('win'), avgR=p.get('avgR'), pf=p.get('pf'), sumR=p.get('sumR'), ddR=p.get('maxddR')))
df = pd.DataFrame(res)
print(df.pivot_table(index=['mkt', 'ver', 'cost'], columns='per', values=['n', 'avgR', 'pf']).round(2).to_string())
# neighbourhood: single configs on WTI 4h A+, futures
mk = Market('WTI', '4h'); set_costs(mk, 'futures')
rows = []
for n, k, m in itertools.product([2, 3, 4, 5, 6, 8, 10], [1.0, 1.5, 2.0, 2.5], [2, 3, 4, 5, 6, 8, 10]):
    st = filter_vol(mk, detect_flags(mk.h, mk.l, mk.c, mk.atr, n, k, m, 0.5, 0.618))
    if len(st) < 10: continue
    tr = non_overlap(trades_from_setups(mk, st, 'HYB'))
    et = mk.t[tr.entry_c.values.astype(int)]
    rows.append(dict(n=n, k=k, m=m, N=len(tr), avg_is=tr.R[et < '2015'].mean(), avg_oos=tr.R[et >= '2015'].mean()))
g = pd.DataFrame(rows)
print('\nWTI 4h A+ single configs: frac IS>0 %.2f, OOS>0 %.2f, both %.2f' % ((g.avg_is > 0).mean(), (g.avg_oos > 0).mean(), ((g.avg_is > 0) & (g.avg_oos > 0)).mean()))
print(g.pivot_table(index='n', columns='m', values='avg_is').round(2))
print(g.pivot_table(index='n', columns='m', values='avg_oos').round(2))
# 2026 sample (CFD) on 4h, WTI & Brent
for nm in ['WTI', 'BRENT']:
    m2 = Market(nm, '4h', source='getdata')
    for vf in [False, True]:
        tr = run_system(m2, 'HYB', vf, regime='cfd')
        print(nm, '2026 4h', 'A+' if vf else 'A', perf(tr) if len(tr) else 'no trades')
