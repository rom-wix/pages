"""Validation suite for SYSTEM 1 + data for the report (results/report_data.json)."""
import itertools, json, time
from multiprocessing import Pool
import numpy as np, pandas as pd
from ogslib import Market, detect_flags, run_tickets, non_overlap, set_costs
import strategies as S
from system import (PARAMS, EXITS, setups, filter_vol, trades_from_setups, run_system, perf, vol_percentile)

OUT = 'results/report_data.json'
PERIODS = [('all', None, None), ('1986-2004', '1900-01-01', '2004-12-31'), ('2005-2014', '2005-01-01', '2014-12-31'),
           ('2015-2020.04', '2015-01-01', '2020-04-30'), ('2020.05-2026.09', '2020-05-01', '2100-01-01'),
           ('post-2005', '2005-01-01', '2100-01-01'), ('post-2005 ex-2020', '2005-01-01', '2100-01-01')]
SETS = {'WTI_ohlc': ('WTI', 'oanda'), 'WTI_eia': ('WTI', 'eia'), 'BRENT_eia': ('BRENT', 'eia')}


def mk_of(key):
    n, s = SETS[key]
    return Market(n, '1d', source=s)


def clean(x):
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else round(float(x), 4)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (pd.Timestamp,)):
        return x.strftime('%Y-%m-%d')
    return x


def period_slice(tr, lab, a, b):
    if a is None:
        return tr
    x = tr[(tr.entry_t >= pd.Timestamp(a)) & (tr.entry_t <= pd.Timestamp(b))]
    if 'ex-2020' in lab:
        x = x[x.entry_t.dt.year != 2020]
    return x


# ------------------------------------------------------------------ 1-3: summary, equity, per-year, costs
def part_summary():
    res = {'summary': [], 'equity': {}, 'per_year': {}, 'costs': [], 'trades': {}}
    for key in SETS:
        mk = mk_of(key)
        for vf in [False, True]:
            ver = 'A+' if vf else 'A'
            tr = run_system(mk, 'HYB', vf)
            trc = run_system(mk, 'HYB', vf, regime='cfd')
            for lab, a, b in PERIODS:
                x = period_slice(tr, lab, a, b)
                if len(x) == 0:
                    continue
                p = perf(x)
                xc = period_slice(trc, lab, a, b)
                p.update(set=key, version=ver, period=lab, avgR_cfd=xc.R.mean() if len(xc) else np.nan)
                res['summary'].append(p)
            e = tr.sort_values('exit_t')
            res['equity'][f'{key}|{ver}'] = [[d.strftime('%Y-%m-%d'), float(v)] for d, v in zip(e.exit_t, np.cumsum(e.R.values))]
            yy = tr.groupby(tr.exit_t.dt.year).R.agg(['sum', 'size'])
            res['per_year'][f'{key}|{ver}'] = {int(y): [float(r['sum']), int(r['size'])] for y, r in yy.iterrows()}
            cols = ['entry_t', 'exit_t', 'dir', 'entry_px', 'stop_px', 'target_px', 'box_hi', 'box_lo', 'impulse', 'R', 'R_mm', 'R_tr']
            res['trades'][f'{key}|{ver}'] = [[clean(v) for v in row] for row in tr[cols].itertuples(index=False)]
            for reg, mult in [('zero', 1), ('futures', 1), ('cfd', 1), ('cfd', 2), ('cfd', 4)]:
                t2 = run_system(mk, 'HYB', vf, regime=reg, cost_mult=mult)
                t2 = t2[t2.entry_t >= '2005-01-01']
                res['costs'].append(dict(set=key, version=ver, regime=f'{reg}x{mult}', avgR=t2.R.mean(), n=len(t2)))
    return res


# ------------------------------------------------------------------ 4: parameter heatmaps (single configs)
def heat_job(args):
    key, vf = args
    mk = mk_of(key)
    set_costs(mk, 'futures')
    out = []
    for n, k, m in itertools.product([2, 3, 4, 5, 6, 7, 8], [1.0, 1.5, 2.0, 2.5, 3.0], [2, 3, 4, 5, 6, 8]):
        st = detect_flags(mk.h, mk.l, mk.c, mk.atr, n, k, m, 0.5, 0.618)
        if vf:
            st = filter_vol(mk, st)
        if len(st) == 0:
            continue
        tr = non_overlap(trades_from_setups(mk, st, 'HYB'))
        if len(tr) == 0:
            continue
        et = mk.t[tr.entry_c.values.astype(int)]
        x = tr[et >= pd.Timestamp('2005-01-01')]
        out.append(dict(set=key, version='A+' if vf else 'A', imp_n=n, imp_k=k, cons_m=m, n=len(x),
                        sumR=x.R.sum(), avgR=x.R.mean() if len(x) else np.nan))
    return out


# ------------------------------------------------------------------ 5: random-timing benchmark
def rand_job(args):
    key, vf, seed, iters = args
    rng = np.random.default_rng(seed)
    mk = mk_of(key)
    set_costs(mk, 'futures')
    st = setups(mk)
    if vf:
        st = filter_vol(mk, st)
    t = st[:, 0].astype(int)
    post = mk.t[t] >= pd.Timestamp('2005-01-01')
    st = st[post]
    t = st[:, 0].astype(int)
    a = mk.atr[t]
    d = st[:, 1]
    u = np.where(d > 0, st[:, 4] - mk.c[t], mk.c[t] - st[:, 5]) / a
    h = (st[:, 4] - st[:, 5]) / a
    ia = st[:, 9] / a
    lo = int(np.searchsorted(mk.t.values, np.datetime64('2005-01-01')))
    hi = len(mk.c) - 30
    vp = vol_percentile(mk) if vf else None
    pool_idx = np.arange(max(lo, 300), hi)
    if vf:
        pool_idx = pool_idx[vp[pool_idx] >= 0.5]
    res = []
    for _ in range(iters):
        tt = np.sort(rng.choice(pool_idx, size=len(st), replace=False))
        j = rng.integers(0, len(st), size=len(st))
        aa = mk.atr[tt]
        dd = d[j]
        R_ = np.where(dd > 0, mk.c[tt] + u[j] * aa, mk.c[tt] - u[j] * aa + h[j] * aa)
        S_ = R_ - h[j] * aa
        fake = np.zeros((len(tt), 10))
        fake[:, 0] = tt; fake[:, 1] = dd; fake[:, 4] = R_; fake[:, 5] = S_; fake[:, 6] = aa; fake[:, 9] = ia[j] * aa
        fake[:, 2] = np.where(dd > 0, S_, R_); fake[:, 3] = np.where(dd > 0, R_, S_)
        fake[:, 7] = tt - 10; fake[:, 8] = tt - 5
        tr = non_overlap(trades_from_setups(mk, fake, 'HYB'))
        res.append(float(tr.R.mean()) if len(tr) else np.nan)
    return (key, vf, res)


# ------------------------------------------------------------------ 6-7: bootstrap & Monte Carlo
def boot_mc(tr, per_yr, rng, n_boot=10000):
    R = tr.R.values
    bs = rng.choice(R, size=(n_boot, len(R)), replace=True).mean(axis=1)
    out = dict(avgR=R.mean(), ci_lo=np.percentile(bs, 2.5), ci_hi=np.percentile(bs, 97.5), p_neg=(bs <= 0).mean())
    ntr = max(int(round(per_yr * 10)), 1)
    for risk in [0.01, 0.02]:
        sims = rng.choice(R, size=(n_boot, ntr), replace=True)
        eq = np.cumprod(1 + risk * sims, axis=1)
        peak = np.maximum.accumulate(np.concatenate([np.ones((n_boot, 1)), eq], axis=1), axis=1)[:, 1:]
        dd = (1 - eq / peak).max(axis=1)
        cagr = eq[:, -1] ** (1 / 10) - 1
        out[f'r{int(risk * 100)}'] = dict(cagr_p5=np.percentile(cagr, 5), cagr_p50=np.percentile(cagr, 50),
                                          cagr_p95=np.percentile(cagr, 95), dd_p50=np.percentile(dd, 50),
                                          dd_p95=np.percentile(dd, 95), p_loss10y=(eq[:, -1] < 1).mean())
    return out


# ------------------------------------------------------------------ 8: event study / continuation vs retracement
def event_job(args):
    name, tf, source = args
    mk = Market(name, tf, source=source)
    set_costs(mk, 'futures')
    st = detect_flags(mk.h, mk.l, mk.c, mk.atr, 5, 1.5, 5, 0.5, 0.618)
    out = dict(mkt=name, tf=tf, source=source, setups=len(st))
    cont = run_tickets(mk, S.cont_breakout(st, E=10, **EXITS['MM1']))
    rev = run_tickets(mk, S.rev_breakout(st, E=10, stop='box', tgt=('mm', 1.0), T=20))
    out['p_cont_first'] = float((cont.filled == 1).mean())
    out['p_rev_first'] = float((rev.filled == 1).mean())
    out['p_none'] = 1 - out['p_cont_first'] - out['p_rev_first']
    c = non_overlap(cont); r = non_overlap(rev)
    et_c = mk.t[c.entry_c.values.astype(int)] if len(c) else pd.DatetimeIndex([])
    et_r = mk.t[r.entry_c.values.astype(int)] if len(r) else pd.DatetimeIndex([])
    cut = pd.Timestamp('2005-01-01')
    out['cont_avgR'] = float(c.R[et_c >= cut].mean()) if len(c) else None
    out['rev_avgR'] = float(r.R[et_r >= cut].mean()) if len(r) else None
    out['cont_win'] = float((c.R[et_c >= cut] > 0).mean()) if len(c) else None
    out['rev_win'] = float((r.R[et_r >= cut] > 0).mean()) if len(r) else None
    out['cont_n'] = int((et_c >= cut).sum()); out['rev_n'] = int((et_r >= cut).sum())
    # same system on this market/timeframe, cfd + futures
    for reg in ['futures', 'cfd']:
        t2 = run_system(mk, 'HYB', False, regime=reg)
        t2 = t2[t2.entry_t >= cut] if len(t2) else t2
        out[f'sys_{reg}_avgR'] = float(t2.R.mean()) if len(t2) else None
        out[f'sys_{reg}_n'] = int(len(t2))
        t3 = run_system(mk, 'HYB', True, regime=reg)
        t3 = t3[t3.entry_t >= cut] if len(t3) else t3
        out[f'sysAp_{reg}_avgR'] = float(t3.R.mean()) if len(t3) else None
        out[f'sysAp_{reg}_n'] = int(len(t3))
    return out


# ------------------------------------------------------------------ 9: 2026 case study
def part_2026():
    res = {}
    for key, (name, src) in [('WTI_eia', ('WTI', 'eia')), ('BRENT_eia', ('BRENT', 'eia'))]:
        mk = Market(name, '1d', source=src)
        for vf in [False, True]:
            tr = run_system(mk, 'HYB', vf)
            x = tr[tr.exit_t >= '2025-10-01']
            res[f'{key}|{"A+" if vf else "A"}'] = [dict(entry=r.entry_t.strftime('%Y-%m-%d'), exit=r.exit_t.strftime('%Y-%m-%d'),
                                                        dir=int(r.dir), entry_px=r.entry_px, stop=r.stop_px, target=r.target_px,
                                                        box_hi=r.box_hi, box_lo=r.box_lo, R=r.R, R_mm=r.R_mm, R_tr=r.R_tr,
                                                        exit_mm=r.exit_px_mm, exit_tr=r.exit_px_tr,
                                                        box_from=r.imp_end_t.strftime('%Y-%m-%d'), box_to=r.arm_t.strftime('%Y-%m-%d'),
                                                        imp_from=r.imp_start_t.strftime('%Y-%m-%d'))
                                                   for r in x.itertuples()]
        s = mk.bars.close.loc['2025-10-01':]
        res[f'{key}|px'] = [[d.strftime('%Y-%m-%d'), float(v)] for d, v in s.items()]
    # OHLC version on the 2026 CFD sample (no A+ filter possible: only ~6 months of bars)
    for name in ['WTI', 'BRENT']:
        mk = Market(name, '1d', source='getdata')
        tr = run_system(mk, 'HYB', False)
        res[f'{name}_cfd2026|A'] = [dict(entry=r.entry_t.strftime('%Y-%m-%d'), exit=r.exit_t.strftime('%Y-%m-%d'), dir=int(r.dir),
                                         entry_px=r.entry_px, stop=r.stop_px, target=r.target_px, R=r.R, box_hi=r.box_hi,
                                         box_lo=r.box_lo) for r in tr.itertuples()] if len(tr) else []
        b = mk.bars
        res[f'{name}_cfd2026|ohlc'] = [[d.strftime('%Y-%m-%d'), float(o), float(h), float(l), float(c)]
                                       for d, o, h, l, c in zip(b.index, b.open, b.high, b.low, b.close)]
    return res


# ------------------------------------------------------------------ 10: family matrix from the sweeps
def part_families():
    df = pd.read_parquet('results/sweep_stage1.parquet')
    rep = {'cont_bo': "{'stop': 'box', 'tgt': ('R', 2.0)}", 'rev_bo': "{'stop': 'box', 'tgt': ('R', 2.0)}",
           'fade_cont': "{'tgt': 'edge'}", 'fade_rev': "{'tgt': 'edge'}", 'retest_cont': "{'tgt': ('R', 2.0)}",
           'retest_rev': "{'tgt': ('R', 2.0)}", 'failed_rev': "{'tgt': 'edge'}", 'failed_cont': "{'tgt': ('R', 2.0)}",
           'fib': "{'r': 0.5, 'tgt': 'P1'}", 'zone': "{'tgt': 'P1'}", 'spike_fade': "{'r': 0.5}",
           'spike_follow': "{'tgt': ('R', 2.0)}", 'box_any': "{'tgt': ('R', 2.0)}"}
    rows = []
    for fam, var in rep.items():
        d = df[(df.fam == fam) & (df['var'] == var) & (df.zero_is_n >= 10) & (df.zero_oos_n >= 5)]
        for (tf, mkt), x in d.groupby(['tf', 'mkt']):
            rows.append(dict(fam=fam, tf=tf, mkt=mkt, cfg=len(x), n_is=x.futures_is_n.median(), n_oos=x.futures_oos_n.median(),
                             gross_is=x.zero_is_avgR.median(), gross_oos=x.zero_oos_avgR.median(),
                             fut_is=x.futures_is_avgR.median(), fut_oos=x.futures_oos_avgR.median(),
                             cfd_oos=x.cfd_oos_avgR.median(), pos_is=(x.futures_is_avgR > 0).mean(),
                             pos_oos=(x.futures_oos_avgR > 0).mean()))
    d2 = pd.read_parquet('results/sweep_close_daily.parquet')
    rows2 = []
    for fam, var in rep.items():
        d = d2[(d2.fam == fam) & (d2['var'] == var)]
        for s, x in d.groupby('set'):
            r = dict(fam=fam, set=s, cfg=len(x))
            for p in ['p1', 'p2', 'p3', 'p4']:
                xx = x[x[f'futures_{p}_n'] >= 5]
                r[p] = xx[f'futures_{p}_avgR'].median() if len(xx) else np.nan
                r[p + '_pos'] = (xx[f'futures_{p}_avgR'] > 0).mean() if len(xx) else np.nan
            rows2.append(r)
    return dict(stage1=rows, closing=rows2)


# ------------------------------------------------------------------ 11: natural-gas candidates
def part_ng():
    out = []
    for key, (name, src) in [('NG_ohlc', ('NG', 'oanda')), ('HH_eia', ('HH', 'eia'))]:
        mk = Market(name, '1d', source=src)
        for vf in [False, True]:
            tr = run_system(mk, 'HYB', vf)
            for lab, a, b in PERIODS:
                x = period_slice(tr, lab, a, b)
                if len(x) == 0:
                    continue
                p = perf(x); p.update(set=key, version=('A+' if vf else 'A'), period=lab, system='S1 flag breakout')
                out.append(p)
        # experimental: retracement breakout, winter setups only
        set_costs(mk, 'futures')
        st = setups(mk)
        st = st[np.isin(mk.t[st[:, 0].astype(int)].month, [11, 12, 1, 2, 3])]
        a = run_tickets(mk, S.rev_breakout(st, E=10, stop='box', tgt=('R', 2.0), T=20))
        tr = non_overlap(a)
        tr['entry_t'] = mk.t[tr.entry_c.values.astype(int)]; tr['exit_t'] = mk.t[tr.exit_c.values.astype(int)]
        for lab, a_, b_ in PERIODS:
            x = period_slice(tr, lab, a_, b_)
            if len(x) == 0:
                continue
            p = perf(x); p.update(set=key, version='winter', period=lab, system='NG winter retracement (experimental)')
            out.append(p)
    return out


if __name__ == '__main__':
    t0 = time.time()
    rng = np.random.default_rng(7)
    data = {'generated': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'), 'params': PARAMS}
    data.update(part_summary()); print('summary %.0fs' % (time.time() - t0), flush=True)
    with Pool(4) as pool:
        heat = pool.map(heat_job, [(k, v) for k in SETS for v in [False, True]])
        data['heatmap'] = [r for rr in heat for r in rr]
        print('heatmaps %.0fs' % (time.time() - t0), flush=True)
        jobs = []
        for key in SETS:
            for vf in [False, True]:
                it = 60 if key == 'WTI_ohlc' else 250
                jobs += [(key, vf, 1000 + 17 * i + (1 if vf else 0) + 97 * list(SETS).index(key), it) for i in range(4)]
        rr = pool.map(rand_job, jobs)
        rb = {}
        for key, vf, res in rr:
            rb.setdefault(f'{key}|{"A+" if vf else "A"}', []).extend(res)
        data['random'] = rb
        print('random %.0fs' % (time.time() - t0), flush=True)
        ev = pool.map(event_job, [('WTI', '1d', 'oanda'), ('NG', '1d', 'oanda'), ('WTI', '1d', 'eia'), ('BRENT', '1d', 'eia'),
                                   ('HH', '1d', 'eia'), ('WTI', '4h', 'oanda'), ('NG', '4h', 'oanda'), ('WTI', '1h', 'oanda'),
                                   ('NG', '1h', 'oanda')])
        data['event'] = ev
        print('events %.0fs' % (time.time() - t0), flush=True)
    bm = {}
    for key in SETS:
        mk = mk_of(key)
        for vf in [False, True]:
            tr = run_system(mk, 'HYB', vf)
            post = tr[tr.entry_t >= '2005-01-01']
            yrs = (min(tr.exit_t.max(), pd.Timestamp('2026-09-22')) - pd.Timestamp('2005-01-01')).days / 365.25
            bm[f'{key}|{"A+" if vf else "A"}'] = boot_mc(post, len(post) / yrs, rng)
    data['bootstrap_mc'] = bm
    data['y2026'] = part_2026(); print('2026 %.0fs' % (time.time() - t0), flush=True)
    data['families'] = part_families()
    data['ng'] = part_ng(); print('ng %.0fs' % (time.time() - t0), flush=True)
    with open(OUT, 'w') as f:
        json.dump(clean(data), f)
    print('wrote', OUT, 'in %.0fs' % (time.time() - t0))
