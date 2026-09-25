"""Stage-1 broad sweep: every family x detector x exit variant on WTI & NG, 1h / 4h / 1d (OANDA 2005-2020).
Stats are computed on NON-OVERLAPPING trades (one position at a time per config), split by entry date into
IS = 2005-2014 and OOS = 2015-2020.04, under three cost regimes (zero, futures, cfd).
Output: results/sweep_stage1.parquet"""
import itertools, sys, time
from multiprocessing import Pool
import numpy as np, pandas as pd
from ogslib import (Market, detect_flags, detect_boxes, detect_impulses, detect_bases, run_tickets, non_overlap,
                    stats, set_costs)
import strategies as S

SPLIT = pd.Timestamp('2015-01-01')
REGIMES = ['zero', 'futures', 'cfd']

FLAG_GRID = list(itertools.product([1, 3, 5], [1.5, 2.0, 2.5, 3.0], [3, 5, 8], [0.5, 0.75]))

FLAG_FAMILIES = [
    ('cont_bo', dict(stop='box', tgt=('R', 1.0))),
    ('cont_bo', dict(stop='box', tgt=('R', 2.0))),
    ('cont_bo', dict(stop='box', tgt=('R', 3.0))),
    ('cont_bo', dict(stop='box', tgt=('mm', 1.0))),
    ('cont_bo', dict(stop='box', tgt=('none',), trail=2.5, T=40)),
    ('cont_bo', dict(stop='mid', tgt=('R', 2.0))),
    ('rev_bo', dict(stop='box', tgt=('R', 1.0))),
    ('rev_bo', dict(stop='box', tgt=('R', 2.0))),
    ('rev_bo', dict(stop='box', tgt=('ret', 1.0))),
    ('rev_bo', dict(stop='mid', tgt=('R', 2.0))),
    ('fade_cont', dict(tgt='edge')),
    ('fade_cont', dict(tgt=('R', 1.5))),
    ('fade_rev', dict(tgt='edge')),
    ('fade_rev', dict(tgt=('R', 1.5))),
    ('retest_cont', dict(tgt=('R', 2.0))),
    ('retest_rev', dict(tgt=('R', 2.0))),
    ('failed_rev', dict(tgt='edge')),
    ('failed_rev', dict(tgt=('R', 2.0))),
    ('failed_rev', dict(tgt=('ret', 1.0))),
    ('failed_cont', dict(tgt='edge')),
    ('failed_cont', dict(tgt=('R', 2.0))),
]


def make_tickets(mk, fam, st, kw):
    if fam == 'cont_bo':
        return S.cont_breakout(st, **kw)
    if fam == 'rev_bo':
        return S.rev_breakout(st, **kw)
    if fam == 'fade_cont':
        return S.fade_edge(st, which='cont', **kw)
    if fam == 'fade_rev':
        return S.fade_edge(st, which='rev', **kw)
    if fam == 'retest_cont':
        return S.retest(st, mk.h, mk.l, mk.c, which='cont', **kw)
    if fam == 'retest_rev':
        return S.retest(st, mk.h, mk.l, mk.c, which='rev', **kw)
    if fam == 'failed_rev':
        return S.failed_break(st, mk.h, mk.l, mk.c, which='rev', **kw)
    if fam == 'failed_cont':
        return S.failed_break(st, mk.h, mk.l, mk.c, which='cont', **kw)
    if fam == 'zone':
        return S.zone_return(st, **kw)
    if fam == 'fib':
        return S.fib_pullback(st, **kw)
    if fam == 'spike_fade':
        return S.spike_fade(st, mk.c, **kw)
    if fam == 'spike_follow':
        return S.spike_follow(st, mk.c, **kw)
    if fam == 'box_any':
        return S.straddle_any(st, **kw)
    raise ValueError(fam)


def evaluate(mk, tk, years_is, years_oos):
    out = {}
    for reg in REGIMES:
        set_costs(mk, reg)
        tr = run_tickets(mk, tk)
        tr = non_overlap(tr)
        if len(tr):
            et = mk.t[tr.entry_c.values.astype(int)]
            is_m = et < SPLIT
        else:
            is_m = np.zeros(0, bool)
        for per, msk, yrs in [('is', is_m, years_is), ('oos', ~is_m, years_oos)]:
            s = stats(tr.R.values[msk] if len(tr) else [], yrs)
            for k2 in ['n', 'win', 'avgR', 'pf', 'sumR', 't', 'maxdd']:
                out[f'{reg}_{per}_{k2}'] = s[k2]
    return out


def job(args):
    name, tf = args
    t0 = time.time()
    mk = Market(name, tf)
    yrs_is = (SPLIT - mk.t[0]).days / 365.25
    yrs_oos = (mk.t[-1] - SPLIT).days / 365.25
    rows = []

    def add(fam, det, kw, st, tk):
        r = dict(mkt=name, tf=tf, fam=fam, det=det, var=str(kw), setups=len(st), tickets=len(tk['side']))
        r.update(evaluate(mk, tk, yrs_is, yrs_oos))
        rows.append(r)

    for imp_n, imp_k, cons_m, box_f in FLAG_GRID:
        st = detect_flags(mk.h, mk.l, mk.c, mk.atr, imp_n, imp_k, cons_m, box_f, 0.618)
        det = f'flag n{imp_n} k{imp_k} m{cons_m} f{box_f}'
        if len(st) < 10:
            continue
        for fam, kw in FLAG_FAMILIES:
            tk = make_tickets(mk, fam, st, kw)
            add(fam, det, kw, st, tk)
    # origin zones
    for base_m, base_atr, imp_n, imp_k in itertools.product([3, 5], [1.0, 1.5], [1, 3], [2.0, 3.0]):
        st = detect_bases(mk.h, mk.l, mk.c, mk.atr, base_m, base_atr, imp_n, imp_k)
        if len(st) < 10:
            continue
        det = f'base m{base_m} b{base_atr} n{imp_n} k{imp_k}'
        for kw in [dict(tgt=('R', 2.0)), dict(tgt='P1'), dict(tgt=('R', 3.0))]:
            add('zone', det, kw, st, make_tickets(mk, 'zone', st, kw))
    # fib pullbacks + no-consolidation controls
    for imp_n, imp_k in itertools.product([1, 3, 5], [2.0, 2.5, 3.0]):
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
    # impulse-free box benchmark
    for cons_m, box_atr in itertools.product([3, 5, 8], [1.0, 1.5, 2.0]):
        st = detect_boxes(mk.h, mk.l, mk.c, mk.atr, cons_m, box_atr, cons_m)
        if len(st) < 10:
            continue
        det = f'box m{cons_m} b{box_atr}'
        for kw in [dict(tgt=('R', 1.0)), dict(tgt=('R', 2.0))]:
            add('box_any', det, kw, st, make_tickets(mk, 'box_any', st, kw))
    print(name, tf, 'rows', len(rows), 'in %.0fs' % (time.time() - t0), flush=True)
    return rows


if __name__ == '__main__':
    tasks = [(n, tf) for tf in ['1h', '4h', '1d'] for n in ['WTI', 'NG']]
    with Pool(4) as p:
        res = p.map(job, tasks, chunksize=1)
    df = pd.DataFrame([r for rr in res for r in rr])
    df.to_parquet('results/sweep_stage1.parquet')
    print('total rows', len(df))
