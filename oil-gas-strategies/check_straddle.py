import itertools
import numpy as np, pandas as pd
from ogslib import Market, detect_boxes, run_tickets, non_overlap, set_costs
import strategies as S
from system import setups, filter_vol, trades_from_setups, perf, vol_percentile

def hyb_rev(mk, st):
    a = run_tickets(mk, S.rev_breakout(st, E=10, stop='box', tgt=('mm', 1.0), T=20))
    b = run_tickets(mk, S.rev_breakout(st, E=10, stop='box', tgt=('none',), trail=3.5, T=60))
    r = a.copy(); r['R'] = 0.5 * a.R.values + 0.5 * b.R.values
    r['exit_f'] = np.maximum(a.exit_f.values, b.exit_f.values); r['exit_c'] = np.maximum(a.exit_c.values, b.exit_c.values)
    return r

def label(mk, tr):
    tr = tr.copy(); tr['entry_t'] = mk.t[tr.entry_c.values.astype(int)]; tr['exit_t'] = mk.t[tr.exit_c.values.astype(int)]; return tr

P = [('<2005', '1900', '2004-12-31'), ('05-14', '2005', '2014-12-31'), ('15-20', '2015', '2020-04-30'), ('20-26', '2020-05-01', '2100'), ('post05', '2005', '2100')]
ROWS = []
def show(mk, tr, name):
    out = []
    for lab, a, b in P:
        x = tr[(tr.entry_t >= a) & (tr.entry_t <= b)]
        if len(x) == 0: out.append(f'{lab}: -'); continue
        p = perf(x); out.append(f'{lab}: n{p["n"]} {p["avgR"]:+.2f}R pf{p["pf"]:.2f} sum{p["sumR"]:+.0f}')
        ROWS.append(dict(set=CUR, variant=name.strip(), period=lab, n=p['n'], avgR=p['avgR'], pf=p['pf'], sumR=p['sumR']))
    print(f'{name:40s} | ' + ' | '.join(out))

for key, (name, src) in {'WTI_ohlc': ('WTI', 'oanda'), 'WTI_eia': ('WTI', 'eia'), 'BRENT_eia': ('BRENT', 'eia')}.items():
    CUR = key
    mk = Market(name, '1d', source=src); set_costs(mk, 'futures')
    st = setups(mk)
    h = (st[:, 4] - st[:, 5]) / st[:, 6]
    print(f'==== {key}: System-1 setups {len(st)}, box height / ATR: median {np.median(h):.2f}, p25 {np.percentile(h,25):.2f}, p75 {np.percentile(h,75):.2f}')
    for vf in [False, True]:
        s2 = filter_vol(mk, st) if vf else st
        c = trades_from_setups(mk, s2, 'HYB'); r = hyb_rev(mk, s2)
        both = pd.concat([c[c.filled == 1], r[r.filled == 1]])
        tag = 'A+' if vf else 'A '
        show(mk, label(mk, non_overlap(c)), f'{tag} continuation only')
        show(mk, label(mk, non_overlap(both)), f'{tag} two-sided (OCO)')
        # impulse-free control boxes with similar geometry: 4-6 bar boxes, height <= median System-1 height (in ATR)
        sts = [detect_boxes(mk.h, mk.l, mk.c, mk.atr, m, float(np.median(h)), m) for m in [4, 5, 6]]
        bx = np.vstack(sts); bx = bx[np.argsort(bx[:, 0], kind='stable')]
        if vf: bx = bx[vol_percentile(mk)[bx[:, 0].astype(int)] >= 0.5]
        # give control boxes an 'impulse size' for the measured-move target = median System-1 impulse / ATR
        bx = bx.copy(); bx[:, 9] = np.median(st[:, 9] / st[:, 6]) * bx[:, 6]
        up = bx.copy(); up[:, 1] = 1.0; dn = bx.copy(); dn[:, 1] = -1.0
        cu = trades_from_setups(mk, up, 'HYB'); cd = trades_from_setups(mk, dn, 'HYB')
        ctrl = pd.concat([cu[cu.filled == 1], cd[cd.filled == 1]])
        show(mk, label(mk, non_overlap(ctrl)), f'{tag} CONTROL: any tight box, two-sided')

import json
d = json.load(open('results/report_page_data.json'))
d['straddle'] = ROWS
json.dump(d, open('results/report_page_data.json', 'w'))
pd.DataFrame(ROWS).to_csv('results/straddle_and_control.csv', index=False)
print('saved', len(ROWS))
