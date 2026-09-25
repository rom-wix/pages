"""Stage-2A: closing-basis (close-only) daily tests.
 1. Calibration: OANDA daily bars degraded to close-only, same period as the OHLC tests (2005-2020).
 2. Extension: EIA spot closes  WTI 1986-2026, Brent 1987-2026, Henry Hub 1997-2026.
Periods: P1 < 2005, P2 2005-2014, P3 2015-2020.04, P4 2020.05-2026.09 (post-OANDA, never used for design).
Output: results/sweep_close_daily.parquet"""
import itertools, time
from multiprocessing import Pool
import numpy as np, pandas as pd
from ogslib import Market, detect_flags, detect_boxes, detect_impulses, detect_bases, run_tickets, non_overlap, stats, set_costs
from sweep import FLAG_FAMILIES, make_tickets

EDGES = [pd.Timestamp('1900-01-01'), pd.Timestamp('2005-01-01'), pd.Timestamp('2015-01-01'),
         pd.Timestamp('2020-05-01'), pd.Timestamp('2100-01-01')]
PNAMES = ['p1', 'p2', 'p3', 'p4']
# close-only volatility (mean |dClose|) is ~0.65x the true-range ATR, so thresholds are scanned a bit wider
FLAG_GRID = list(itertools.product([1, 3, 5], [1.5, 2.0, 2.5, 3.0, 3.5], [3, 5, 8], [0.5, 0.75]))


def evaluate(mk, tk):
    out = {}
    for reg in ['zero', 'futures']:
        set_costs(mk, reg)
        tr = non_overlap(run_tickets(mk, tk))
        et = mk.t[tr.entry_c.values.astype(int)] if len(tr) else pd.DatetimeIndex([])
        for p, a, b in zip(PNAMES, EDGES[:-1], EDGES[1:]):
            msk = (et >= a) & (et < b)
            s = stats(tr.R.values[msk] if len(tr) else [])
            out[f'{reg}_{p}_n'] = s['n']
            out[f'{reg}_{p}_avgR'] = s['avgR']
            out[f'{reg}_{p}_sumR'] = s['sumR']
            out[f'{reg}_{p}_win'] = s['win']
    return out


def job(args):
    name, source, close_only = args
    t0 = time.time()
    mk = Market(name, '1d', source=source, close_only=close_only)
    tag = f'{name}_{source}' + ('_co' if close_only else '')
    rows = []

    def add(fam, det, kw, st, tk):
        r = dict(set=tag, mkt=name, source=source, close_only=close_only, fam=fam, det=det, var=str(kw), setups=len(st))
        r.update(evaluate(mk, tk))
        rows.append(r)

    for imp_n, imp_k, cons_m, box_f in FLAG_GRID:
        st = detect_flags(mk.h, mk.l, mk.c, mk.atr, imp_n, imp_k, cons_m, box_f, 0.618)
        if len(st) < 10:
            continue
        det = f'flag n{imp_n} k{imp_k} m{cons_m} f{box_f}'
        for fam, kw in FLAG_FAMILIES:
            add(fam, det, kw, st, make_tickets(mk, fam, st, kw))
    for base_m, base_atr, imp_n, imp_k in itertools.product([3, 5], [1.0, 1.5], [1, 3], [2.0, 3.0]):
        st = detect_bases(mk.h, mk.l, mk.c, mk.atr, base_m, base_atr, imp_n, imp_k)
        if len(st) < 10:
            continue
        det = f'base m{base_m} b{base_atr} n{imp_n} k{imp_k}'
        for kw in [dict(tgt=('R', 2.0)), dict(tgt='P1')]:
            add('zone', det, kw, st, make_tickets(mk, 'zone', st, kw))
    for imp_n, imp_k in itertools.product([1, 3, 5], [2.0, 2.5, 3.0, 3.5]):
        st = detect_impulses(mk.h, mk.l, mk.c, mk.atr, imp_n, imp_k, imp_n + 1)
        if len(st) < 10:
            continue
        det = f'imp n{imp_n} k{imp_k}'
        for r_ in [0.382, 0.5, 0.618]:
            for tg in ['P1', ('R', 2.0)]:
                kw = dict(r=r_, tgt=tg)
                add('fib', det, kw, st, make_tickets(mk, 'fib', st, kw))
        for kw in [dict(r=0.382), dict(r=0.5)]:
            add('spike_fade', det, kw, st, make_tickets(mk, 'spike_fade', st, kw))
        for kw in [dict(tgt=('R', 1.0)), dict(tgt=('R', 2.0))]:
            add('spike_follow', det, kw, st, make_tickets(mk, 'spike_follow', st, kw))
    for cons_m, box_atr in itertools.product([3, 5, 8], [1.0, 1.5, 2.0]):
        st = detect_boxes(mk.h, mk.l, mk.c, mk.atr, cons_m, box_atr, cons_m)
        if len(st) < 10:
            continue
        det = f'box m{cons_m} b{box_atr}'
        for kw in [dict(tgt=('R', 1.0)), dict(tgt=('R', 2.0))]:
            add('box_any', det, kw, st, make_tickets(mk, 'box_any', st, kw))
    print(tag, len(rows), 'rows in %.0fs' % (time.time() - t0), flush=True)
    return rows


if __name__ == '__main__':
    tasks = [('WTI', 'oanda', False), ('NG', 'oanda', False), ('WTI', 'oanda', True), ('NG', 'oanda', True),
             ('WTI', 'eia', False), ('BRENT', 'eia', False), ('HH', 'eia', False)]
    with Pool(4) as p:
        res = p.map(job, tasks, chunksize=1)
    df = pd.DataFrame([r for rr in res for r in rr])
    df.to_parquet('results/sweep_close_daily.parquet')
    print('rows', len(df))
