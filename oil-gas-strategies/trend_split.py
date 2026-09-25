"""Does the pre-impulse trend decide continuation vs retracement?
Each setup is classified WITH-trend if the impulse direction agrees with sign(close - SMA_L) measured on the bar
BEFORE the impulse started (no look-ahead), COUNTER-trend otherwise.  L = 100 trading days on every timeframe."""
import itertools
from multiprocessing import Pool
import numpy as np, pandas as pd
from ogslib import Market, detect_flags, run_tickets, non_overlap, stats, set_costs
import strategies as S

BARS_PER_DAY = {'1h': 23, '4h': 6, '1d': 1}
EDGES = [pd.Timestamp('1900-01-01'), pd.Timestamp('2005-01-01'), pd.Timestamp('2015-01-01'),
         pd.Timestamp('2020-05-01'), pd.Timestamp('2100-01-01')]
PN = ['p1', 'p2', 'p3', 'p4']


def sma(x, n):
    s = pd.Series(x).rolling(n, min_periods=n).mean().values
    return s


def job(args):
    name, tf, source, close_only = args
    mk = Market(name, tf, source=source, close_only=close_only)
    set_costs(mk, 'futures')
    L = 100 * BARS_PER_DAY[tf]
    ma = sma(mk.c, L)
    tag = f'{name}_{source}_{tf}' + ('_co' if close_only else '')
    grid = itertools.product([1, 3, 5], [1.5, 2.0, 2.5, 3.0], [3, 5, 8], [0.5, 0.75])
    rows = []
    for imp_n, imp_k, cons_m, box_f in grid:
        st = detect_flags(mk.h, mk.l, mk.c, mk.atr, imp_n, imp_k, cons_m, box_f, 0.618)
        if len(st) < 20:
            continue
        s_idx = st[:, 7].astype(int) - 1
        pre = np.sign(mk.c[s_idx] - ma[s_idx])
        align = pre * st[:, 1]  # +1 with-trend, -1 counter-trend, nan if MA not ready
        for fam, fn, kw in [('cont', S.cont_breakout, dict(tgt=('R', 2.0))),
                            ('cont_trail', S.cont_breakout, dict(tgt=('none',), trail=2.5, T=40)),
                            ('rev', S.rev_breakout, dict(tgt=('R', 2.0))),
                            ('rev_ret', S.rev_breakout, dict(tgt=('ret', 1.0)))]:
            tk = fn(st, **kw)
            tr = run_tickets(mk, tk)
            tr = tr[tr.filled == 1].copy()
            tr['aln'] = align[tr.setup.values.astype(int)]
            tr['et'] = mk.t[tr.entry_c.values.astype(int)]
            for cls, lab in [(1, 'with'), (-1, 'counter')]:
                sub = non_overlap(tr[tr['aln'] == cls])
                for p, a, b in zip(PN, EDGES[:-1], EDGES[1:]):
                    x = sub[(sub.et >= a) & (sub.et < b)]
                    if len(x) == 0:
                        continue
                    rows.append(dict(set=tag, tf=tf, det=f'n{imp_n} k{imp_k} m{cons_m} f{box_f}', fam=fam,
                                     trend=lab, period=p, n=len(x), avgR=x.R.mean(), sumR=x.R.sum(),
                                     win=(x.R > 0).mean()))
    print(tag, 'done', flush=True)
    return rows


if __name__ == '__main__':
    tasks = [('WTI', '1d', 'oanda', False), ('NG', '1d', 'oanda', False), ('WTI', '1d', 'eia', False),
             ('BRENT', '1d', 'eia', False), ('HH', '1d', 'eia', False), ('WTI', '4h', 'oanda', False),
             ('NG', '4h', 'oanda', False), ('WTI', '1h', 'oanda', False), ('NG', '1h', 'oanda', False)]
    with Pool(4) as p:
        res = p.map(job, tasks, chunksize=1)
    df = pd.DataFrame([r for rr in res for r in rr])
    df.to_parquet('results/trend_split.parquet')
    q = df[df.n >= 5].groupby(['set', 'fam', 'trend', 'period']).agg(
        cfg=('avgR', 'size'), n_med=('n', 'median'), avgR_med=('avgR', 'median'),
        pos=('avgR', lambda x: (x > 0).mean())).reset_index()
    w = q.pivot_table(index=['set', 'fam', 'trend'], columns='period', values=['avgR_med', 'pos', 'n_med'])
    w.columns = [f'{a}_{b}' for a, b in w.columns]
    cols = [c for p in PN for c in (f'n_med_{p}', f'avgR_med_{p}', f'pos_{p}') if c in w.columns]
    pd.set_option('display.width', 250); pd.set_option('display.max_rows', 500)
    print(w[cols].round(2).to_string())
