import itertools
import numpy as np, pandas as pd
from ogslib import Market, detect_flags, run_tickets, non_overlap, set_costs
import strategies as S
from system import perf, vol_percentile, EXITS
mks = {'WTI_ohlc': Market('WTI', '1d'), 'WTI_eia': Market('WTI', '1d', source='eia'), 'BRENT_eia': Market('BRENT', '1d', source='eia')}

def union_setups(mk, ns, ks, ms, box_f=0.5):
    sts = [detect_flags(mk.h, mk.l, mk.c, mk.atr, n, k, m, box_f, 0.618) for n, k, m in itertools.product(ns, ks, ms)]
    st = np.vstack([s for s in sts if len(s)])
    return st[np.argsort(st[:, 0], kind='stable')]

def hyb(mk, st):
    a = run_tickets(mk, S.cont_breakout(st, E=10, **EXITS['MM1'])); b = run_tickets(mk, S.cont_breakout(st, E=10, **EXITS['TR']))
    tr = a.copy(); tr['R'] = 0.5 * a.R.values + 0.5 * b.R.values
    tr['exit_f'] = np.maximum(a.exit_f.values, b.exit_f.values); tr['exit_c'] = np.maximum(a.exit_c.values, b.exit_c.values)
    tr = non_overlap(tr); tr['entry_t'] = mk.t[tr.entry_c.values.astype(int)]; tr['exit_t'] = mk.t[tr.exit_c.values.astype(int)]
    return tr

defs = {'single 5/2.0/5': ([5], [2.0], [5]), 'union 27 (n4-6,k1.5-2.5,m4-6)': ([4, 5, 6], [1.5, 2.0, 2.5], [4, 5, 6]),
        'union k1.5 (n4-6,m4-6)': ([4, 5, 6], [1.5], [4, 5, 6]), 'union k2.0 (n4-6,m4-6)': ([4, 5, 6], [2.0], [4, 5, 6]),
        'union n3-7 k1.5 m3-7': ([3, 4, 5, 6, 7], [1.5], [3, 4, 5, 6, 7])}
for m, mk in mks.items():
    set_costs(mk, 'futures'); vp = vol_percentile(mk)
    for name, (ns, ks, ms) in defs.items():
        st = union_setups(mk, ns, ks, ms)
        for vf in [False, True]:
            s2 = st[vp[st[:, 0].astype(int)] >= 0.5] if vf else st
            tr = hyb(mk, s2)
            out = []
            for lab, a, b in [('<2005', '1900', '2004-12-31'), ('05-14', '2005', '2014-12-31'), ('15-20', '2015', '2020-04-30'), ('20-26', '2020-05-01', '2100'), ('post05 ex2020', '2005', '2100')]:
                x = tr[(tr.entry_t >= pd.Timestamp(a)) & (tr.entry_t <= pd.Timestamp(b))]
                if lab == 'post05 ex2020': x = x[x.entry_t.dt.year != 2020]
                if len(x) == 0: out.append(f'{lab}: -'); continue
                p = perf(x); out.append(f'{lab}: n{p["n"]} {p["avgR"]:+.2f}R pf{p["pf"]:.2f}')
            print(f'{m:9s} {"A+" if vf else "A "} {name:32s} | ' + ' | '.join(out))
