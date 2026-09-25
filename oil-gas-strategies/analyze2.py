import pandas as pd, numpy as np
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 500)
df = pd.read_parquet('results/sweep_close_daily.parquet')
df['v'] = df.fam + ' ' + df['var'].str.replace("'", "").str.replace('tgt: ', '').str.replace('stop: ', '')
keep_v = ['cont_bo {box, (R, 2.0)}', 'cont_bo {box, (none,), trail: 2.5, T: 40}', 'cont_bo {mid, (R, 2.0)}',
          'cont_bo {box, (mm, 1.0)}', 'retest_cont {(R, 2.0)}', 'rev_bo {box, (R, 2.0)}', 'rev_bo {box, (ret, 1.0)}',
          'fade_cont {edge}', 'fade_rev {edge}', 'failed_rev {edge}', 'failed_cont {(R, 2.0)}',
          'fib {r: 0.5, P1}', 'fib {r: 0.618, P1}', 'fib {r: 0.382, P1}', 'zone {P1}', 'zone {(R, 2.0)}',
          'spike_fade {r: 0.5}', 'spike_follow {(R, 2.0)}', 'box_any {(R, 2.0)}']
rows = []
for (s, v), x in df[df.v.isin(keep_v)].groupby(['set', 'v']):
    r = dict(set=s, v=v, nd=len(x))
    for p in ['p1', 'p2', 'p3', 'p4']:
        xx = x[x[f'futures_{p}_n'] >= 5]
        r[f'{p}_n'] = xx[f'futures_{p}_n'].median() if len(xx) else np.nan
        r[f'{p}'] = xx[f'futures_{p}_avgR'].median() if len(xx) else np.nan
        r[f'{p}+'] = (xx[f'futures_{p}_avgR'] > 0).mean() if len(xx) else np.nan
    rows.append(r)
a = pd.DataFrame(rows)
order = ['WTI_oanda', 'WTI_oanda_co', 'WTI_eia', 'BRENT_eia', 'NG_oanda', 'NG_oanda_co', 'HH_eia']
for v in keep_v:
    b = a[a.v == v].set_index('set').reindex(order)
    print('=====', v)
    print(b.drop(columns=['v']).round(2).to_string())
