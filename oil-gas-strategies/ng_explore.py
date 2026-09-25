"""Natural-gas specific exploration: seasonality / volatility regime x families, daily bars."""
import itertools
import numpy as np, pandas as pd
from ogslib import Market, detect_flags, detect_impulses, run_tickets, non_overlap, stats, set_costs
import strategies as S
from candidates import regime_arrays, EDGES, PN

mks = {'NG_ohlc': Market('NG', '1d'), 'HH_eia': Market('HH', '1d', source='eia')}
fams = {
    'cont_R2': lambda mk, st: S.cont_breakout(st, tgt=('R', 2.0)),
    'rev_R2': lambda mk, st: S.rev_breakout(st, tgt=('R', 2.0)),
    'rev_ret1': lambda mk, st: S.rev_breakout(st, tgt=('ret', 1.0)),
    'failed_rev_edge': lambda mk, st: S.failed_break(st, mk.h, mk.l, mk.c, which='rev', tgt='edge'),
}
rows = []
for mname, mk in mks.items():
    set_costs(mk, 'futures')
    ma, pr = regime_arrays(mk)
    month = mk.t.month
    for imp_n, imp_k, cons_m, box_f in itertools.product([3, 5], [1.5, 2.0, 2.5], [3, 5], [0.5, 0.75]):
        st = detect_flags(mk.h, mk.l, mk.c, mk.atr, imp_n, imp_k, cons_m, box_f, 0.618)
        if len(st) < 10: continue
        for fn_name, fn in fams.items():
            tr = run_tickets(mk, fn(mk, st)); tr = tr[tr.filled == 1].copy()
            if not len(tr): continue
            t_arm = st[tr.setup.values.astype(int), 0].astype(int)
            tr['winter'] = np.isin(month[t_arm], [11, 12, 1, 2, 3])
            tr['volhi'] = pr[t_arm] >= 0.5
            tr['et'] = mk.t[tr.entry_c.values.astype(int)]
            for flt, m_ in [('all', np.ones(len(tr), bool)), ('winter', tr.winter.values), ('summer', ~tr.winter.values),
                            ('volhi', tr.volhi.values), ('vollo', ~tr.volhi.values)]:
                x = non_overlap(tr[m_])
                for p, a, b in zip(PN, EDGES[:-1], EDGES[1:]):
                    y = x[(x.et >= a) & (x.et < b)]
                    if len(y) < 3: continue
                    rows.append(dict(set=mname, fam=fn_name, flt=flt, period=p, n=len(y), avgR=y.R.mean()))
    for imp_n, imp_k in itertools.product([1, 3, 5], [2.0, 2.5, 3.0]):
        st = detect_impulses(mk.h, mk.l, mk.c, mk.atr, imp_n, imp_k, imp_n + 1)
        for fn_name, tk in [('fib50', S.fib_pullback(st, r=0.5, tgt='P1')), ('fib618', S.fib_pullback(st, r=0.618, tgt='P1')),
                            ('spike_fade50', S.spike_fade(st, mk.c, r=0.5))]:
            tr = run_tickets(mk, tk); tr = tr[tr.filled == 1].copy()
            if not len(tr): continue
            t_arm = st[tr.setup.values.astype(int), 0].astype(int)
            tr['winter'] = np.isin(month[t_arm], [11, 12, 1, 2, 3]); tr['volhi'] = pr[t_arm] >= 0.5
            tr['et'] = mk.t[tr.entry_c.values.astype(int)]
            for flt, m_ in [('all', np.ones(len(tr), bool)), ('winter', tr.winter.values), ('summer', ~tr.winter.values),
                            ('volhi', tr.volhi.values), ('vollo', ~tr.volhi.values)]:
                x = non_overlap(tr[m_])
                for p, a, b in zip(PN, EDGES[:-1], EDGES[1:]):
                    y = x[(x.et >= a) & (x.et < b)]
                    if len(y) < 3: continue
                    rows.append(dict(set=mname, fam=fn_name, flt=flt, period=p, n=len(y), avgR=y.R.mean()))
df = pd.DataFrame(rows)
q = df.groupby(['fam', 'flt', 'set', 'period']).agg(cfg=('avgR', 'size'), n=('n', 'median'), avgR=('avgR', 'median'),
                                                   pos=('avgR', lambda x: (x > 0).mean())).reset_index()
w = q.pivot_table(index=['fam', 'flt', 'set'], columns='period', values=['avgR', 'pos'])
w.columns = [f'{a}_{b}' for a, b in w.columns]
pd.set_option('display.width', 200); pd.set_option('display.max_rows', 300)
print(w[[c for p in PN for c in (f'avgR_{p}', f'pos_{p}') if c in w.columns]].round(2).to_string())
