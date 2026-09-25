"""Detailed evaluation of the daily crude-oil flag-breakout cluster + optional regime filters."""
import itertools
import numpy as np, pandas as pd
from ogslib import Market, detect_flags, run_tickets, non_overlap, stats, set_costs
import strategies as S

EDGES = [pd.Timestamp('1900-01-01'), pd.Timestamp('2005-01-01'), pd.Timestamp('2015-01-01'),
         pd.Timestamp('2020-05-01'), pd.Timestamp('2100-01-01')]
PN = ['p1', 'p2', 'p3', 'p4']
EXITS = {
    'R2': dict(stop='box', tgt=('R', 2.0)),
    'R3': dict(stop='box', tgt=('R', 3.0)),
    'MM1': dict(stop='box', tgt=('mm', 1.0)),
    'TR3.5': dict(stop='box', tgt=('none',), trail=3.5, T=60),
}


def regime_arrays(mk):
    c = pd.Series(mk.c)
    ma = c.rolling(100, min_periods=100).mean().values
    atrp = pd.Series(mk.atr / mk.c)
    # percentile of today's ATR% within the trailing 252 bars (no look-ahead)
    pr = atrp.rolling(252, min_periods=126).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True).values
    return ma, pr


def trades_for(mk, params, exit_kw, regime='futures'):
    imp_n, imp_k, cons_m, box_f = params
    st = detect_flags(mk.h, mk.l, mk.c, mk.atr, imp_n, imp_k, cons_m, box_f, 0.618)
    set_costs(mk, regime)
    tr = run_tickets(mk, S.cont_breakout(st, **exit_kw))
    tr = tr[tr.filled == 1].copy()
    ma, pr = regime_arrays(mk)
    s_idx = st[tr.setup.values.astype(int), 7].astype(int) - 1
    t_arm = st[tr.setup.values.astype(int), 0].astype(int)
    tr['with_trend'] = np.sign(mk.c[s_idx] - ma[s_idx]) * st[tr.setup.values.astype(int), 1] > 0
    tr['vol_pct'] = pr[t_arm]
    tr['entry_t'] = mk.t[tr.entry_c.values.astype(int)]
    tr['exit_t'] = mk.t[tr.exit_c.values.astype(int)]
    return tr


def summarize(tr, label):
    rows = []
    for p, a, b in zip(PN, EDGES[:-1], EDGES[1:]):
        x = tr[(tr.entry_t >= a) & (tr.entry_t < b)]
        s = stats(x.R.values)
        rows.append(dict(label=label, period=p, n=s['n'], win=s['win'], avgR=s['avgR'], pf=s['pf'], sumR=s['sumR'],
                         maxddR=s['maxdd']))
    return rows


if __name__ == '__main__':
    pd.set_option('display.width', 220); pd.set_option('display.max_rows', 400)
    mks = {'WTI_ohlc': Market('WTI', '1d'), 'WTI_eia': Market('WTI', '1d', source='eia'),
           'BRENT_eia': Market('BRENT', '1d', source='eia')}
    cands = [(5, 2.0, 5, 0.5), (5, 2.5, 5, 0.5), (4, 2.0, 5, 0.5), (5, 2.0, 6, 0.5), (3, 2.0, 5, 0.5),
             (5, 1.5, 5, 0.5), (5, 2.0, 4, 0.5), (5, 2.0, 5, 0.75)]
    rows = []
    for cand in cands:
        for ex, kw in EXITS.items():
            for mname, mk in mks.items():
                tr = non_overlap(trades_for(mk, cand, kw))
                for r in summarize(tr, f'{cand} {ex} {mname}'):
                    r.update(dict(cand=str(cand), exit=ex, set=mname)); rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv('results/candidates.csv', index=False)
    piv = df.pivot_table(index=['cand', 'exit', 'set'], columns='period', values=['n', 'avgR'])
    piv.columns = [f'{a}_{b}' for a, b in piv.columns]
    print(piv[[f'{m}_{p}' for p in PN for m in ['n', 'avgR']]].round(2).to_string())

    # regime filters on the centre candidate
    print('\n=== regime filters, centre candidate (5,2.0,5,0.5) ===')
    rows = []
    for ex, kw in EXITS.items():
        for mname, mk in mks.items():
            tr = trades_for(mk, (5, 2.0, 5, 0.5), kw)
            for flt, m_ in [('all', np.ones(len(tr), bool)), ('with_trend', tr.with_trend.values),
                            ('counter_trend', ~tr.with_trend.values),
                            ('vol_high', tr.vol_pct.values >= 0.5), ('vol_low', tr.vol_pct.values < 0.5)]:
                x = non_overlap(tr[m_])
                for r in summarize(x, ''):
                    r.update(dict(exit=ex, set=mname, filter=flt)); rows.append(r)
    f = pd.DataFrame(rows)
    pv = f.pivot_table(index=['exit', 'filter', 'set'], columns='period', values=['n', 'avgR'])
    pv.columns = [f'{a}_{b}' for a, b in pv.columns]
    print(pv[[f'{m}_{p}' for p in PN for m in ['n', 'avgR']]].round(2).to_string())
    f.to_csv('results/candidates_filters.csv', index=False)
