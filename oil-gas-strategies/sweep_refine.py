"""Stage-2C: refine the daily crude-oil continuation breakout ("flag / box breakout").
Datasets: WTI OANDA daily OHLC (1-min fills, 2005-2020.04), WTI EIA closes (1986-2026.09), Brent EIA closes
(1987-2026.09).  Design period = p2 (2005-2014).  p3 (2015-2020.04) = first validation, p4 (2020.05-2026.09) =
holdout, p1 (<2005) = out-of-era check.  Costs: futures regime (cfd regime reported separately later).
Output: results/sweep_refine.parquet"""
import itertools, time
from multiprocessing import Pool
import numpy as np, pandas as pd
from ogslib import Market, detect_flags, run_tickets, non_overlap, stats, set_costs
import strategies as S

EDGES = [pd.Timestamp('1900-01-01'), pd.Timestamp('2005-01-01'), pd.Timestamp('2015-01-01'),
         pd.Timestamp('2020-05-01'), pd.Timestamp('2100-01-01')]
PN = ['p1', 'p2', 'p3', 'p4']
GRID = list(itertools.product([2, 3, 4, 5, 7], [1.0, 1.5, 2.0, 2.5, 3.0], [2, 3, 4, 5, 6, 8], [0.5, 0.75, 1.0]))
EXITS = {
    'R2': dict(stop='box', tgt=('R', 2.0)),
    'R3': dict(stop='box', tgt=('R', 3.0)),
    'MM1': dict(stop='box', tgt=('mm', 1.0)),
    'TR2.5': dict(stop='box', tgt=('none',), trail=2.5, T=40),
    'TR3.5': dict(stop='box', tgt=('none',), trail=3.5, T=60),
    'MID_R2': dict(stop='mid', tgt=('R', 2.0)),
}


def job(args):
    name, source = args
    t0 = time.time()
    mk = Market(name, '1d', source=source)
    rows = []
    for imp_n, imp_k, cons_m, box_f in GRID:
        st = detect_flags(mk.h, mk.l, mk.c, mk.atr, imp_n, imp_k, cons_m, box_f, 0.618)
        if len(st) < 5:
            continue
        for ex, kw in EXITS.items():
            tk = S.cont_breakout(st, **kw)
            r = dict(set=f'{name}_{source}', imp_n=imp_n, imp_k=imp_k, cons_m=cons_m, box_f=box_f, exit=ex,
                     setups=len(st))
            for reg in ['futures', 'cfd']:
                set_costs(mk, reg)
                tr = non_overlap(run_tickets(mk, tk))
                et = mk.t[tr.entry_c.values.astype(int)] if len(tr) else pd.DatetimeIndex([])
                for p, a, b in zip(PN, EDGES[:-1], EDGES[1:]):
                    m_ = (et >= a) & (et < b)
                    R = tr.R.values[m_] if len(tr) else np.array([])
                    r[f'{reg}_{p}_n'] = len(R)
                    r[f'{reg}_{p}_sumR'] = R.sum() if len(R) else 0.0
                    r[f'{reg}_{p}_avgR'] = R.mean() if len(R) else np.nan
                    r[f'{reg}_{p}_win'] = (R > 0).mean() if len(R) else np.nan
            rows.append(r)
    print(name, source, len(rows), 'rows in %.0fs' % (time.time() - t0), flush=True)
    return rows


if __name__ == '__main__':
    tasks = [('WTI', 'oanda'), ('WTI', 'eia'), ('BRENT', 'eia')]
    with Pool(3) as p:
        res = p.map(job, tasks, chunksize=1)
    df = pd.DataFrame([r for rr in res for r in rr])
    df.to_parquet('results/sweep_refine.parquet')
    print('rows', len(df))
