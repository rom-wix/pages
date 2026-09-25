"""Event study: impulse -> consolidation box -> which edge breaks first, and what follows."""
import time, sys
import numpy as np, pandas as pd
from ogslib import Market, detect_flags, detect_boxes, run_tickets, non_overlap, stats
import strategies as S

t0 = time.time()
mk = {}
for name in ['WTI', 'NG']:
    for tf in ['1h', '4h', '1d']:
        mk[(name, tf)] = Market(name, tf)
print('markets built in %.1fs' % (time.time() - t0))
for k, m in mk.items():
    print(k, len(m.bars), 'fine', len(m.fo), 'median ATR %.3f' % np.nanmedian(m.atr))

rows = []
for (name, tf), m in mk.items():
    for imp_n, imp_k in [(1, 2.0), (3, 2.5), (5, 3.0)]:
        for cons_m in [3, 5, 8]:
            st = detect_flags(m.h, m.l, m.c, m.atr, imp_n, imp_k, cons_m, 0.5, 0.618)
            if len(st) < 20:
                continue
            # first-break statistics with symmetric 1R targets (box-height distance) and opposite-edge stops
            for fam, fn in [('cont', S.cont_breakout), ('rev', S.rev_breakout)]:
                tk = fn(st, E=10, T=20, tgt=('R', 1.0))
                tr = run_tickets(m, tk)
                f = tr[tr.filled == 1]
                s = stats(f.R)
                rows.append(dict(mkt=name, tf=tf, imp_n=imp_n, imp_k=imp_k, cons_m=cons_m, setups=len(st), fam=fam,
                                 fill_rate=len(f) / len(st), n=s['n'], win=s['win'], avgR=s['avgR']))
df = pd.DataFrame(rows)
pd.set_option('display.width', 200)
print(df.round(3).to_string())
df.to_csv('results/event_study_first_break.csv', index=False)
