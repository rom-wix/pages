import itertools
import numpy as np, pandas as pd
from ogslib import Market, detect_flags, run_tickets, non_overlap, set_costs
import strategies as S
from system import run_system, perf, vol_percentile, EXITS, PARAMS
pd.set_option('display.width', 220); pd.set_option('display.max_rows', 200)
mks = {'WTI_ohlc': Market('WTI', '1d'), 'WTI_oanda_co': Market('WTI', '1d', close_only=True),
       'WTI_eia': Market('WTI', '1d', source='eia'), 'BRENT_eia': Market('BRENT', '1d', source='eia')}
# 1) per-year sum R (HYB, no filter and vol filter)
yr = {}
for m in ['WTI_eia', 'BRENT_eia', 'WTI_ohlc']:
    for vf in [False, True]:
        tr = run_system(mks[m], 'HYB', vf)
        yr[(m, 'A+' if vf else 'A')] = tr.groupby(tr.exit_t.dt.year).R.sum()
Y = pd.DataFrame(yr).fillna(0).round(1)
print(Y.to_string())
Y.to_csv('results/per_year_sumR.csv')
# 2) execution style on the same OANDA data: intraday stops (OHLC) vs closing basis
print('\n=== execution style, OANDA WTI 2005-2020.04 ===')
for m in ['WTI_ohlc', 'WTI_oanda_co']:
    for ex in ['MM1', 'TR', 'HYB']:
        for vf in [False, True]:
            p = perf(run_system(mks[m], ex, vf))
            print(m, ex, 'A+' if vf else 'A ', {k: round(v, 2) for k, v in p.items() if k in ['n', 'win', 'avgR', 'pf', 'sumR', 'maxddR']})
# 3) cost sensitivity (HYB)
print('\n=== cost sensitivity, HYB ===')
for m in ['WTI_ohlc', 'WTI_eia', 'BRENT_eia']:
    for vf in [False, True]:
        out = []
        for reg, mult in [('zero', 1), ('futures', 1), ('cfd', 1), ('cfd', 2), ('cfd', 4)]:
            p = perf(run_system(mks[m], 'HYB', vf, regime=reg, cost_mult=mult))
            out.append(f'{reg}x{mult}: {p["avgR"]:.2f}')
        print(m, 'A+' if vf else 'A ', ' | '.join(out))
# 4) ensemble of neighbouring settings (union of setups, one position at a time)
print('\n=== ensemble vs single ===')
for m in ['WTI_ohlc', 'WTI_eia', 'BRENT_eia']:
    mk = mks[m]; set_costs(mk, 'futures')
    sts = []
    for imp_n, imp_k, cons_m in itertools.product([4, 5, 6], [1.5, 2.0, 2.5], [4, 5, 6]):
        s = detect_flags(mk.h, mk.l, mk.c, mk.atr, imp_n, imp_k, cons_m, 0.5, 0.618)
        sts.append(s)
    st = np.vstack(sts)
    st = st[np.argsort(st[:, 0], kind='stable')]
    vp = vol_percentile(mk)
    for vf in [False, True]:
        s2 = st[vp[st[:, 0].astype(int)] >= 0.5] if vf else st
        a = run_tickets(mk, S.cont_breakout(s2, E=10, **EXITS['MM1'])); b = run_tickets(mk, S.cont_breakout(s2, E=10, **EXITS['TR']))
        tr = a.copy(); tr['R'] = 0.5 * a.R.values + 0.5 * b.R.values; tr['exit_f'] = np.maximum(a.exit_f.values, b.exit_f.values)
        tr['exit_c'] = np.maximum(a.exit_c.values, b.exit_c.values)
        tr = non_overlap(tr); tr['entry_t'] = mk.t[tr.entry_c.values.astype(int)]; tr['exit_t'] = mk.t[tr.exit_c.values.astype(int)]
        post = tr[tr.entry_t >= '2005-01-01']
        p = perf(post); p0 = perf(run_system(mk, 'HYB', vf).query("entry_t >= '2005-01-01'"))
        print(m, 'A+' if vf else 'A ', 'ensemble post-2005:', {k: round(v, 2) for k, v in p.items() if k in ['n', 'per_yr', 'avgR', 'pf', 'sumR', 'maxddR']},
              '| single:', {k: round(v, 2) for k, v in p0.items() if k in ['n', 'per_yr', 'avgR', 'pf', 'sumR', 'maxddR']})
