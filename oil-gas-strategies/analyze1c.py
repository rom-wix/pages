import pandas as pd, numpy as np
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 500)
df = pd.read_parquet('results/sweep_stage1.parquet')
df['v'] = df.fam + ' ' + df['var'].str.replace("'", "").str.replace('tgt: ', '').str.replace('stop: ', '')
d = df[(df.tf == '1d')]
cols = ['det', 'setups', 'futures_is_n', 'futures_is_avgR', 'futures_is_pf', 'futures_oos_n', 'futures_oos_avgR', 'futures_oos_pf']
for v in ['cont_bo {box, (none,), trail: 2.5, T: 40}', 'cont_bo {box, (R, 2.0)}', 'retest_cont {(R, 2.0)}', 'fib {r: 0.5, P1}']:
    for m in ['WTI', 'NG']:
        x = d[(d.v == v) & (d.mkt == m)][cols].sort_values('det')
        print('=====', v, m, ' configs:', len(x), ' IS>0: %.2f  OOS>0: %.2f  both>0: %.2f' % (
            (x.futures_is_avgR > 0).mean(), (x.futures_oos_avgR > 0).mean(),
            ((x.futures_is_avgR > 0) & (x.futures_oos_avgR > 0)).mean()))
        if v.startswith('cont_bo {box, (none'):
            print(x.round(3).to_string(index=False))
