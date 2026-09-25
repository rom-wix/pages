"""Build the compact data file embedded in the HTML report (results/report_page_data.json)."""
import json
import numpy as np, pandas as pd
from ogslib import Market, run_tickets, non_overlap, set_costs
import strategies as S
from system import setups, filter_vol, trades_from_setups, EXITS, perf

d = json.load(open('results/report_data.json'))
out = {}

# ---- continuation vs retracement on the SAME setups (System-1 boxes), post-2005, futures costs
def both_sides(name, tf, source):
    mk = Market(name, tf, source=source); set_costs(mk, 'futures')
    st = setups(mk)
    res = {'mkt': name, 'tf': tf, 'source': source, 'setups': int(len(st))}
    for vf in [False, True]:
        s2 = filter_vol(mk, st) if vf else st
        c = trades_from_setups(mk, s2, 'HYB')
        a = run_tickets(mk, S.rev_breakout(s2, E=10, stop='box', tgt=('mm', 1.0), T=20))
        b = run_tickets(mk, S.rev_breakout(s2, E=10, stop='box', tgt=('none',), trail=3.5, T=60))
        r = a.copy(); r['R'] = 0.5 * a.R.values + 0.5 * b.R.values
        r['exit_f'] = np.maximum(a.exit_f.values, b.exit_f.values); r['exit_c'] = np.maximum(a.exit_c.values, b.exit_c.values)
        tag = 'Ap' if vf else 'A'
        if not vf:
            res['p_cont_first'] = float((c.filled == 1).mean()); res['p_rev_first'] = float((r.filled == 1).mean())
        for side, tr in [('cont', c), ('rev', r)]:
            tr = non_overlap(tr)
            et = mk.t[tr.entry_c.values.astype(int)] if len(tr) else pd.DatetimeIndex([])
            x = tr[et >= pd.Timestamp('2005-01-01')]
            res[f'{side}_{tag}_n'] = int(len(x)); res[f'{side}_{tag}_avgR'] = float(x.R.mean()) if len(x) else None
            res[f'{side}_{tag}_win'] = float((x.R > 0).mean()) if len(x) else None
    return res

rows = []
for args in [('WTI', '1d', 'oanda'), ('WTI', '1d', 'eia'), ('BRENT', '1d', 'eia'), ('NG', '1d', 'oanda'), ('HH', '1d', 'eia'),
             ('WTI', '4h', 'oanda'), ('NG', '4h', 'oanda'), ('WTI', '1h', 'oanda'), ('NG', '1h', 'oanda')]:
    rows.append(both_sides(*args)); print(rows[-1], flush=True)
out['sides'] = rows

# ---- pass-through pieces
out['summary'] = d['summary']
out['costs'] = d['costs']
out['bootstrap_mc'] = d['bootstrap_mc']
out['equity'] = d['equity']
out['per_year'] = d['per_year']
out['y2026'] = d['y2026']
out['ng'] = d['ng']
out['families'] = d['families']
# heatmap: k = 1.5 slice + pooled-over-k
hm = pd.DataFrame(d['heatmap'])
out['heat'] = hm.to_dict(orient='records')
# random benchmark: keep raw arrays
out['random'] = d['random']
json.dump(out, open('results/report_page_data.json', 'w'))
print('ok', len(json.dumps(out)) / 1e3, 'KB')
