import pandas as pd, numpy as np
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 500); pd.set_option('display.max_colwidth', 40)
df = pd.read_parquet('results/sweep_stage1.parquet')
df = df[(df.zero_is_n >= 15) & (df.zero_oos_n >= 8)]
g = df.groupby(['tf', 'mkt', 'fam', 'var'])
agg = g.agg(ndet=('det', 'size'), n_is=('futures_is_n', 'median'), n_oos=('futures_oos_n', 'median'),
            gross_is=('zero_is_avgR', 'median'), gross_oos=('zero_oos_avgR', 'median'),
            fut_is=('futures_is_avgR', 'median'), fut_oos=('futures_oos_avgR', 'median'),
            cfd_is=('cfd_is_avgR', 'median'), cfd_oos=('cfd_oos_avgR', 'median'),
            pos_fut_is=('futures_is_avgR', lambda x: (x > 0).mean()),
            pos_fut_oos=('futures_oos_avgR', lambda x: (x > 0).mean()))
agg = agg.reset_index()
for tf in ['1h', '4h', '1d']:
    print('=' * 30, tf)
    a = agg[agg.tf == tf].sort_values(['fam', 'var', 'mkt'])
    print(a.drop(columns=['tf']).round(3).to_string(index=False))
