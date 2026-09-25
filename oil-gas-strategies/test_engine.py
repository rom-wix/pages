"""Sanity tests for the ticket simulator on hand-built paths (run: python3 test_engine.py)."""
import numpy as np
from ogslib import simulate, tickets_frame, atr


class Fake:
    def __init__(self, path, per=4, cost=0.0, slip=0.0, eps=0.0):
        # path: list of (o,h,l,c) fine bars; `per` fine bars per coarse bar
        p = np.array(path, float)
        self.fo, self.fh, self.fl, self.fc = p[:, 0].copy(), p[:, 1].copy(), p[:, 2].copy(), p[:, 3].copy()
        n = len(p)
        self.f_coarse = (np.arange(n) // per).astype(np.int64)
        nc = self.f_coarse[-1] + 1
        self.c_first = np.array([i * per for i in range(nc)], np.int64)
        self.c_last = np.array([min(i * per + per - 1, n - 1) for i in range(nc)], np.int64)
        self.c = np.array([self.fc[self.c_last[i]] for i in range(nc)])
        self.atr = np.ones(nc)
        self.cost, self.slip, self.eps = cost, slip, eps


def run(mk, **kw):
    tk = tickets_frame(1)
    for k, v in kw.items():
        tk[k][:] = v
    r = simulate(mk.fo, mk.fh, mk.fl, mk.fc, mk.f_coarse, mk.c_first, mk.c_last, mk.c, mk.atr,
                 tk['act_c'], tk['exp_c'], tk['side'], tk['etype'], tk['entry'], tk['cancel_hi'], tk['cancel_lo'],
                 tk['stop0'], tk['target'], tk['tstop'], tk['trail_k'], tk['be_r'], mk.slip, mk.cost, mk.eps)
    return r[0]

flat = [(10, 10, 10, 10)] * 4
# A: stop entry long, then target
pathA = flat + [(10.2, 10.3, 10.1, 10.2), (10.2, 10.6, 10.2, 10.55), (10.55, 10.8, 10.5, 10.8), (10.8, 11, 10.7, 11)] + \
        [(11.5, 11.6, 11.4, 11.5), (11.5, 12.6, 11.5, 12.4), (12.4, 12.5, 12.3, 12.4), (12.4, 12.4, 12.4, 12.4)]
mk = Fake(pathA, slip=0.01, cost=0.02)
r = run(mk, act_c=1, exp_c=2, side=1, etype=1, entry=10.5, stop0=9.5, target=12.5, tstop=10)
assert r[0] == 1 and r[1] == 5 and abs(r[2] - 10.51) < 1e-9, r
assert r[5] == 2 and abs(r[4] - 12.5) < 1e-9, r
assert abs(r[6] - ((12.5 - 10.51 - 0.02) / 1.0)) < 1e-9, r
print('A ok  stop-entry + target, R=%.3f' % r[6])

# B: cancel level hit before entry
pathB = flat + [(10, 10.1, 9.4, 9.5)] * 4 + [(9.5, 11, 9.5, 11)] * 4
mk = Fake(pathB)
r = run(mk, act_c=1, exp_c=2, side=1, etype=1, entry=10.5, cancel_lo=9.5, stop0=9.5, target=12.5, tstop=10)
assert r[0] == 0 and r[5] == -1, r
print('B ok  cancelled before entry')

# C: gap through entry -> fill at open; risk measured from planned level
pathC = flat + [(11.0, 11.2, 10.9, 11.1)] * 4 + [(11.1, 11.1, 9.0, 9.2)] * 4
mk = Fake(pathC)
r = run(mk, act_c=1, exp_c=2, side=1, etype=1, entry=10.5, stop0=9.5, target=13, tstop=10)
assert r[0] == 1 and abs(r[2] - 11.0) < 1e-9 and r[5] == 1 and abs(r[4] - 9.5) < 1e-9, r
assert abs(r[6] - (9.5 - 11.0) / 1.0) < 1e-9, r
print('C ok  gap fill at open, stop exit, R=%.2f' % r[6])

# D: stop and target in same fine bar -> stop first
pathD = flat + [(10.2, 10.6, 10.2, 10.55), (10.55, 10.6, 10.5, 10.6), (10.6, 13, 9, 10), (10, 10, 10, 10)]
mk = Fake(pathD)
r = run(mk, act_c=1, exp_c=2, side=1, etype=1, entry=10.5, stop0=9.5, target=12.5, tstop=10)
assert r[5] == 1, r
print('D ok  same-bar stop/target resolved as stop')

# E: time stop after 1 coarse bar
pathE = flat + [(10.2, 10.6, 10.2, 10.55)] + [(10.6, 10.7, 10.5, 10.6)] * 3 + [(10.7, 10.8, 10.6, 10.75)] * 4 + flat
mk = Fake(pathE)
r = run(mk, act_c=1, exp_c=2, side=1, etype=1, entry=10.5, stop0=9.5, target=np.nan, tstop=1)
assert r[5] == 3 and r[3] == 11 and abs(r[4] - 10.75) < 1e-9, r
print('E ok  time stop at close of coarse bar entry+1')

# F: limit entry needs penetration by eps
pathF = flat + [(10.2, 10.3, 10.0, 10.1)] * 4 + [(10.1, 10.2, 9.98, 10.1)] * 4
mk = Fake(pathF, eps=0.01)
r = run(mk, act_c=1, exp_c=1, side=1, etype=2, entry=10.0, stop0=9.5, target=11, tstop=5)
assert r[0] == 0, r
r = run(mk, act_c=1, exp_c=2, side=1, etype=2, entry=10.0, stop0=9.5, target=11, tstop=5)
assert r[0] == 1 and r[1] == 8 and abs(r[2] - 10.0) < 1e-9, r
print('F ok  limit needs penetration; fills at limit')

# G: short side mirror with target
pathG = flat + [(9.8, 9.9, 9.4, 9.45)] + [(9.45, 9.5, 9.3, 9.35)] * 3 + [(9.3, 9.35, 8.4, 8.45)] * 4
mk = Fake(pathG)
r = run(mk, act_c=1, exp_c=2, side=-1, etype=1, entry=9.5, stop0=10.5, target=8.5, tstop=10)
assert r[0] == 1 and abs(r[2] - 9.5) < 1e-9 and r[5] == 2 and abs(r[6] - 1.0) < 1e-9, r
print('G ok  short stop-entry + target, R=%.2f' % r[6])

# H: stop on the entry bar (worst case)
pathH = flat + [(10.2, 10.6, 9.4, 10.0)] + [(10, 10, 10, 10)] * 3
mk = Fake(pathH)
r = run(mk, act_c=1, exp_c=1, side=1, etype=1, entry=10.5, stop0=9.5, target=12.5, tstop=10)
assert r[5] == 5, r
print('H ok  stop inside entry bar -> stopped (worst case)')
print('all engine tests passed')
