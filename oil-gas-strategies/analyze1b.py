import pandas as pd, numpy as np
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 500)
df = pd.read_parquet('results/sweep_stage1.parquet')
df = df[(df.zero_is_n >= 15) & (df.zero_oos_n >= 8)]
df['v'] = df.fam + ' ' + df['var'].str.replace("'", "").str.replace('tgt: ', '').str.replace('stop: ', '')
g = df.groupby(['tf', 'v', 'mkt'])
agg = g.agg(nd=('det', 'size'), nIS=('futures_is_n', 'median'), nOOS=('futures_oos_n', 'median'),
            gIS=('zero_is_avgR', 'median'), gOOS=('zero_oos_avgR', 'median'),
            fIS=('futures_is_avgR', 'median'), fOOS=('futures_oos_avgR', 'median'),
            cOOS=('cfd_oos_avgR', 'median')).reset_index()
w = agg.pivot_table(index=['tf', 'v'], columns='mkt', values=['gIS', 'gOOS', 'fIS', 'fOOS', 'nIS'])
w.columns = [f'{a}_{b}' for a, b in w.columns]
w = w[['nIS_WTI', 'gIS_WTI', 'gOOS_WTI', 'fIS_WTI', 'fOOS_WTI', 'nIS_NG', 'gIS_NG', 'gOOS_NG', 'fIS_NG', 'fOOS_NG']]
for tf in ['1h', '4h', '1d']:
    print('=' * 20, tf, '(median over detector settings; g=gross avg R, f=futures-cost avg R)')
    print(w.loc[tf].round(3).to_string())
