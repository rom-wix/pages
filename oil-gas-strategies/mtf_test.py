"""Multi-timeframe variant: impulse must be large in DAILY-ATR terms; the consolidation box and entry are on 1h/4h."""
import itertools
from multiprocessing import Pool
import numpy as np, pandas as pd
from ogslib import Market, detect_flags, run_tickets, non_overlap, stats, set_costs
import strategies as S
SPLIT = pd.Timestamp('2015-01-01')

def daily_atr_on(mk, dmk):
    # ATR of the last COMPLETED daily session, mapped onto intraday bars (no look-ahead)
    lab = (mk.t + pd.Timedelta(hours=6)).floor('D')
    pos = np.searchsorted(dmk.t.values, lab.values) - 1
    out = np.full(len(mk.t), np.nan)
    ok = pos >= 0
    out[ok] = dmk.atr[pos[ok]]
    return out

def job(args):
    name, tf = args
    mk = Market(name, tf); dmk = Market(name, '1d')
    set_costs(mk, 'futures')
    datr = daily_atr_on(mk, dmk)
    bpd = {'1h': 23, '4h': 6}[tf]
    rows = []
    for imp_days, k, cons_m, box_f in itertools.product([0.5, 1, 2, 3], [1.0, 1.5, 2.0, 2.5], [3, 6, 12], [0.5, 0.75]):
        imp_n = max(1, int(round(imp_days * bpd)))
        st = detect_flags(mk.h, mk.l, mk.c, datr, imp_n, k, cons_m, box_f, 0.618)
        if len(st) < 10: continue
        st = st.copy(); st[:, 6] = mk.atr[st[:, 7].astype(int) - 1]   # intraday ATR for stop floor / trailing
        for ex, kw in [('R2', dict(tgt=('R', 2.0))), ('R3', dict(tgt=('R', 3.0))),
                       ('TR', dict(tgt=('none',), trail=3.0, T=bpd * 10))]:
            tk = S.cont_breakout(st, E=cons_m * 2, **kw)
            tr = non_overlap(run_tickets(mk, tk))
            et = mk.t[tr.entry_c.values.astype(int)] if len(tr) else pd.DatetimeIndex([])
            r = dict(mkt=name, tf=tf, imp_days=imp_days, k=k, cons_m=cons_m, box_f=box_f, exit=ex)
            for per, m_ in [('is', et < SPLIT), ('oos', et >= SPLIT)]:
                R = tr.R.values[m_] if len(tr) else np.array([])
                r[f'n_{per}'] = len(R); r[f'avgR_{per}'] = R.mean() if len(R) else np.nan
            rows.append(r)
    return rows

if __name__ == '__main__':
    with Pool(4) as p:
        res = p.map(job, [('WTI', '4h'), ('NG', '4h'), ('WTI', '1h'), ('NG', '1h')])
    df = pd.DataFrame([r for rr in res for r in rr]); df.to_parquet('results/mtf_test.parquet')
    pd.set_option('display.width', 200)
    d = df[(df.n_is >= 30) & (df.n_oos >= 15)]
    print(d.groupby(['mkt', 'tf', 'exit'])[['n_is', 'avgR_is', 'avgR_oos']].median().round(3))
    print(d.groupby(['mkt', 'tf', 'exit']).apply(lambda x: pd.Series({'pos_is': (x.avgR_is > 0).mean(), 'pos_oos': (x.avgR_oos > 0).mean(), 'both': ((x.avgR_is > 0) & (x.avgR_oos > 0)).mean()})).round(2))
    print(d.groupby(['mkt', 'tf', 'imp_days'])[['avgR_is', 'avgR_oos']].median().round(3))
