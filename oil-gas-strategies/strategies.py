"""Strategy families: setups -> order tickets.

A 'setup' row (from ogslib detectors) = [t_arm, dir, P0, P1, R, S, atr_pre, s, e, I]
  dir  = +1 bullish impulse / -1 bearish impulse
  P0   = impulse origin, P1 = impulse extreme, I = |P1 - P0|
  R, S = consolidation box high / low (box formed AFTER the impulse)

Continuation families trade in the impulse direction, retracement families against it.
"""
import numpy as np
from numba import njit
from ogslib import tickets_frame

T_, D_, P0_, P1_, R_, S_, A_, s_, e_, I_ = range(10)

# Minimum stop distance in ATR units. Without it a 2-bar box of CLOSES can be a few cents tall and R-multiples
# explode; no trader would run a stop that tight. Applied to every family before targets are computed.
FLOOR_ATR = 0.5


def _floor(side, ref, stop, a, floor=None):
    f = FLOOR_ATR if floor is None else floor
    return np.where(side > 0, np.minimum(stop, ref - f * a), np.maximum(stop, ref + f * a))


def _targets(side, entry, stop0, tgt, extra):
    """tgt = ('R', x) R-multiple | ('mm', m) measured move of impulse | ('lvl', array) explicit | ('none',)"""
    risk = np.abs(entry - stop0)
    kind = tgt[0]
    if kind == 'R':
        return entry + side * tgt[1] * risk
    if kind == 'mm':
        return entry + side * tgt[1] * extra['I']
    if kind == 'lvl':
        return tgt[1]
    return np.full(len(side), np.nan)


def cont_breakout(st, E=10, T=20, buf=0.0, stop='box', tgt=('R', 2.0), trail=0.0, be=0.0):
    """Impulse -> box -> buy-stop above box high (bull) / sell-stop below box low (bear).
    Cancelled if the opposite edge breaks first. Stop at opposite edge ('box') or box middle ('mid')."""
    n = len(st)
    tk = tickets_frame(n)
    d, a = st[:, D_], st[:, A_]
    R, S = st[:, R_], st[:, S_]
    up = d > 0
    tk['side'] = d.copy()
    tk['etype'][:] = 1
    tk['entry'] = np.where(up, R + buf * a, S - buf * a)
    tk['cancel_lo'] = np.where(up, S - buf * a, -np.inf)
    tk['cancel_hi'] = np.where(up, np.inf, R + buf * a)
    if stop == 'box':
        tk['stop0'] = np.where(up, S - buf * a, R + buf * a)
    else:
        tk['stop0'] = (R + S) / 2
    tk['stop0'] = _floor(tk['side'], tk['entry'], tk['stop0'], a)
    tk['target'] = _targets(tk['side'], tk['entry'], tk['stop0'], tgt, dict(I=st[:, I_]))
    tk['act_c'] = st[:, T_].astype(np.int64) + 1
    tk['exp_c'] = st[:, T_].astype(np.int64) + E
    tk['tstop'][:] = T
    tk['trail_k'][:] = trail
    tk['be_r'][:] = be
    return tk


def rev_breakout(st, E=10, T=20, buf=0.0, stop='box', tgt=('R', 2.0), trail=0.0, be=0.0):
    """Impulse -> box -> the box breaks AGAINST the impulse: sell-stop below box low after a bull impulse.
    tgt ('ret', r): target = P1 - dir * r * I (r=1.0 -> full retracement to the impulse origin)."""
    n = len(st)
    tk = tickets_frame(n)
    d, a = st[:, D_], st[:, A_]
    R, S = st[:, R_], st[:, S_]
    up = d > 0
    tk['side'] = -d
    tk['etype'][:] = 1
    tk['entry'] = np.where(up, S - buf * a, R + buf * a)
    tk['cancel_hi'] = np.where(up, R + buf * a, np.inf)
    tk['cancel_lo'] = np.where(up, -np.inf, S - buf * a)
    if stop == 'box':
        tk['stop0'] = np.where(up, R + buf * a, S - buf * a)
    else:
        tk['stop0'] = (R + S) / 2
    tk['stop0'] = _floor(tk['side'], tk['entry'], tk['stop0'], a)
    if tgt[0] == 'ret':
        lvl = st[:, P1_] - d * tgt[1] * st[:, I_]
        # a retracement target must lie beyond the entry; otherwise fall back to 1R
        bad = (tk['side'] * (lvl - tk['entry'])) <= 0
        risk = np.abs(tk['entry'] - tk['stop0'])
        lvl = np.where(bad, tk['entry'] + tk['side'] * risk, lvl)
        tk['target'] = lvl
    else:
        tk['target'] = _targets(tk['side'], tk['entry'], tk['stop0'], tgt, dict(I=st[:, I_]))
    tk['act_c'] = st[:, T_].astype(np.int64) + 1
    tk['exp_c'] = st[:, T_].astype(np.int64) + E
    tk['tstop'][:] = T
    tk['trail_k'][:] = trail
    tk['be_r'][:] = be
    return tk


def fade_edge(st, which='cont', E=10, T=20, sbuf=0.25, tgt='edge', buf=0.0):
    """Range trade inside the post-impulse box.
    which='cont': buy the box LOW after a bull impulse (support, continuation-aligned)
    which='rev' : sell the box HIGH after a bull impulse (resistance, retracement-aligned)
    stop sbuf*ATR beyond the edge; target 'edge' (opposite edge), 'mid', or ('R', x).
    Cancelled if the box breaks on the other side first."""
    n = len(st)
    tk = tickets_frame(n)
    d, a = st[:, D_], st[:, A_]
    R, S = st[:, R_], st[:, S_]
    up = d > 0
    if which == 'cont':
        side = d.copy()
        buy_low = up  # long at S for bull, short at R for bear
    else:
        side = -d
        buy_low = ~up  # short at R for bull, long at S for bear
    tk['side'] = side
    tk['etype'][:] = 2
    tk['entry'] = np.where(buy_low, S, R)
    tk['stop0'] = np.where(buy_low, S - sbuf * a, R + sbuf * a)
    tk['stop0'] = _floor(side, tk['entry'], tk['stop0'], a)
    tk['cancel_hi'] = np.where(buy_low, R + buf * a, np.inf)
    tk['cancel_lo'] = np.where(buy_low, -np.inf, S - buf * a)
    if tgt == 'edge':
        tk['target'] = np.where(buy_low, R, S)
    elif tgt == 'mid':
        tk['target'] = (R + S) / 2
    else:
        tk['target'] = tk['entry'] + side * tgt[1] * np.abs(tk['entry'] - tk['stop0'])
    tk['act_c'] = st[:, T_].astype(np.int64) + 1
    tk['exp_c'] = st[:, T_].astype(np.int64) + E
    tk['tstop'][:] = T
    return tk


@njit(cache=True)
def _find_break_close(c, t0, E, lvl_hi, lvl_lo, want_up):
    """First bar j in (t0, t0+E] whose CLOSE breaks lvl in the wanted direction before the other side.
    returns j or -1"""
    n = len(c)
    for j in range(t0 + 1, min(t0 + E, n - 1) + 1):
        if want_up:
            if c[j] < lvl_lo:
                return -1
            if c[j] > lvl_hi:
                return j
        else:
            if c[j] > lvl_hi:
                return -1
            if c[j] < lvl_lo:
                return j
    return -1


def retest(st, h, l, c, which='cont', E=10, W=10, T=20, cb=0.1, tol=0.0, sr=0.5, tgt=('R', 2.0)):
    """Break-and-retest: after a CLOSE beyond the box edge (by cb*ATR), place a limit at the broken edge
    (+tol*ATR on the favourable side) for W bars; stop sr*ATR through the edge.
    which='cont': breakout in impulse direction; 'rev': breakdown against it."""
    rows = []
    for k in range(len(st)):
        t, d, a, R, S = int(st[k, T_]), st[k, D_], st[k, A_], st[k, R_], st[k, S_]
        side = d if which == 'cont' else -d
        if side > 0:
            j = _find_break_close(c, t, E, R + cb * a, S, True)
            if j < 0:
                continue
            rows.append((j, side, R + tol * a, R - sr * a, k))
        else:
            j = _find_break_close(c, t, E, R, S - cb * a, False)
            if j < 0:
                continue
            rows.append((j, side, S - tol * a, S + sr * a, k))
    tk = tickets_frame(len(rows))
    if not rows:
        return tk
    rr = np.array(rows)
    tk['act_c'] = rr[:, 0].astype(np.int64) + 1
    tk['exp_c'] = rr[:, 0].astype(np.int64) + W
    tk['side'] = rr[:, 1]
    tk['etype'][:] = 2
    tk['entry'] = rr[:, 2]
    tk['stop0'] = _floor(tk['side'], tk['entry'], rr[:, 3], st[rr[:, 4].astype(int), A_])
    tk['target'] = _targets(tk['side'], tk['entry'], tk['stop0'], tgt, dict(I=st[rr[:, 4].astype(int), I_]))
    tk['tstop'][:] = T
    tk['setup'] = rr[:, 4].astype(np.int64)
    return tk


@njit(cache=True)
def _find_failure(h, l, c, t0, E, X, R, S, buf_a, up_break):
    """Look for a probe beyond an edge (high > R+buf for up_break, low < S-buf otherwise) within E bars,
    then a CLOSE back inside the box within X bars of the probe. Returns (q, extreme) or (-1, nan).
    Aborts if the opposite edge is probed first."""
    n = len(c)
    j = -1
    for i in range(t0 + 1, min(t0 + E, n - 1) + 1):
        if up_break:
            if l[i] < S - buf_a:
                return -1, np.nan
            if h[i] > R + buf_a:
                j = i
                break
        else:
            if h[i] > R + buf_a:
                return -1, np.nan
            if l[i] < S - buf_a:
                j = i
                break
    if j < 0:
        return -1, np.nan
    ext = h[j] if up_break else l[j]
    for q in range(j, min(j + X, n - 1) + 1):
        if up_break:
            ext = max(ext, h[q])
            if c[q] < R:
                return q, ext
        else:
            ext = min(ext, l[q])
            if c[q] > S:
                return q, ext
    return -1, np.nan


def failed_break(st, h, l, c, which='rev', E=10, X=3, T=20, buf=0.0, sb=0.1, tgt='edge'):
    """which='rev' : bull impulse, box, breakout ABOVE box fails (close back inside) -> SHORT next open
                     (turtle-soup / upthrust; retracement trade). Target opposite edge / ('ret', r) / ('R', x).
    which='cont': bull impulse, box, breakdown BELOW box fails -> LONG next open (spring; continuation)."""
    rows = []
    for k in range(len(st)):
        t, d, a, R, S = int(st[k, T_]), st[k, D_], st[k, A_], st[k, R_], st[k, S_]
        # direction of the probe that must fail
        probe_up = (d > 0) if which == 'rev' else (d < 0)
        q, ext = _find_failure(h, l, c, t, E, X, R, S, buf * a, probe_up)
        if q < 0:
            continue
        side = -1.0 if probe_up else 1.0
        stop = ext + sb * a if probe_up else ext - sb * a
        rows.append((q, side, stop, k))
    tk = tickets_frame(len(rows))
    if not rows:
        return tk
    rr = np.array(rows)
    ks = rr[:, 3].astype(int)
    tk['act_c'] = rr[:, 0].astype(np.int64) + 1
    tk['exp_c'] = rr[:, 0].astype(np.int64) + 1
    tk['side'] = rr[:, 1]
    tk['etype'][:] = 0
    tk['stop0'] = rr[:, 2]
    # reference price for targets: the failure bar close
    ref = c[rr[:, 0].astype(int)]
    side = tk['side']
    tk['stop0'] = _floor(side, ref, tk['stop0'], st[ks, A_])
    risk = np.abs(ref - tk['stop0'])
    if tgt == 'edge':
        tk['target'] = np.where(side < 0, st[ks, S_], st[ks, R_])
    elif isinstance(tgt, tuple) and tgt[0] == 'R':
        tk['target'] = ref + side * tgt[1] * risk
    elif isinstance(tgt, tuple) and tgt[0] == 'ret':
        lvl = st[ks, P1_] - st[ks, D_] * tgt[1] * st[ks, I_]
        bad = side * (lvl - ref) <= 0
        tk['target'] = np.where(bad, ref + side * risk, lvl)
    tk['tstop'][:] = T
    tk['setup'] = ks
    return tk


def zone_return(st, E=40, T=20, tol=0.0, sb=0.25, tgt=('R', 2.0), cancel_ext=None):
    """Supply/demand origin zone (setups from detect_bases): after a bull impulse leaves a tight base, buy the
    first return to the base top (proximal line), stop sb*ATR below the base bottom (distal line)."""
    n = len(st)
    tk = tickets_frame(n)
    d, a = st[:, D_], st[:, A_]
    zh, zl = st[:, R_], st[:, S_]
    up = d > 0
    tk['side'] = d.copy()
    tk['etype'][:] = 2
    tk['entry'] = np.where(up, zh + tol * a, zl - tol * a)
    tk['stop0'] = np.where(up, zl - sb * a, zh + sb * a)
    tk['stop0'] = _floor(tk['side'], tk['entry'], tk['stop0'], a)
    if tgt == 'P1':
        tk['target'] = st[:, P1_]
    else:
        tk['target'] = _targets(tk['side'], tk['entry'], tk['stop0'], tgt, dict(I=st[:, I_]))
    if cancel_ext is not None:
        tk['cancel_hi'] = np.where(up, st[:, P1_] + cancel_ext * st[:, I_], np.inf)
        tk['cancel_lo'] = np.where(up, -np.inf, st[:, P1_] - cancel_ext * st[:, I_])
    tk['act_c'] = st[:, T_].astype(np.int64) + 1
    tk['exp_c'] = st[:, T_].astype(np.int64) + E
    tk['tstop'][:] = T
    return tk


def fib_pullback(st, r=0.5, rs=1.0, sb=0.1, E=20, T=20, tgt='P1', cancel_ext=0.5):
    """Continuation after a retracement: limit buy at P1 - r*I after a bull impulse, stop at P1 - rs*I - sb*ATR,
    target the impulse extreme ('P1') or R-multiple. Cancelled if price first extends cancel_ext*I beyond P1."""
    n = len(st)
    tk = tickets_frame(n)
    d, a, P1, I = st[:, D_], st[:, A_], st[:, P1_], st[:, I_]
    tk['side'] = d.copy()
    tk['etype'][:] = 2
    tk['entry'] = P1 - d * r * I
    tk['stop0'] = P1 - d * rs * I - d * sb * a
    tk['stop0'] = _floor(tk['side'], tk['entry'], tk['stop0'], a)
    if tgt == 'P1':
        tk['target'] = P1.copy()
    else:
        tk['target'] = _targets(tk['side'], tk['entry'], tk['stop0'], tgt, dict(I=I))
    up = d > 0
    tk['cancel_hi'] = np.where(up, P1 + cancel_ext * I, np.inf)
    tk['cancel_lo'] = np.where(up, -np.inf, P1 - cancel_ext * I)
    tk['act_c'] = st[:, T_].astype(np.int64) + 1
    tk['exp_c'] = st[:, T_].astype(np.int64) + E
    tk['tstop'][:] = T
    return tk


def spike_fade(st, c, r=0.5, sb=0.25, T=10):
    """Control for the retracement idea WITHOUT waiting for consolidation: fade the impulse at the next open,
    stop sb*ATR beyond the impulse extreme, target an r retracement of the impulse."""
    n = len(st)
    tk = tickets_frame(n)
    d, a, P1, I = st[:, D_], st[:, A_], st[:, P1_], st[:, I_]
    tk['side'] = -d
    tk['etype'][:] = 0
    ref = c[st[:, T_].astype(int)]
    tk['stop0'] = _floor(-d, ref, P1 + d * sb * a, a)
    lvl = P1 - d * r * I
    bad = (-d) * (lvl - ref) <= 0
    tk['target'] = np.where(bad, ref - d * np.abs(ref - tk['stop0']), lvl)
    tk['act_c'] = st[:, T_].astype(np.int64) + 1
    tk['exp_c'] = st[:, T_].astype(np.int64) + 1
    tk['tstop'][:] = T
    return tk


def spike_follow(st, c, sb=0.0, T=10, tgt=('R', 2.0)):
    """Control for the continuation idea WITHOUT waiting for consolidation: go with the impulse at next open,
    stop at the impulse origin (minus sb*ATR). R-multiple target anchored on the signal-bar close."""
    n = len(st)
    tk = tickets_frame(n)
    d, a, P0 = st[:, D_], st[:, A_], st[:, P0_]
    tk['side'] = d.copy()
    tk['etype'][:] = 0
    ref = c[st[:, T_].astype(int)]
    tk['stop0'] = _floor(d, ref, P0 - d * sb * a, a)
    tk['target'] = _targets(tk['side'], ref, tk['stop0'], tgt, dict(I=st[:, I_]))
    tk['act_c'] = st[:, T_].astype(np.int64) + 1
    tk['exp_c'] = st[:, T_].astype(np.int64) + 1
    tk['tstop'][:] = T
    return tk


def straddle_any(st, E=10, T=20, tgt=('R', 2.0)):
    """Benchmark on impulse-free boxes (detect_boxes): OCO stop orders on both edges; stop = opposite edge."""
    n = len(st)
    R, S = st[:, R_], st[:, S_]
    L = tickets_frame(n)
    L['side'][:] = 1.0
    L['etype'][:] = 1
    L['entry'] = R.copy()
    L['cancel_lo'] = S.copy()
    L['stop0'] = S.copy()
    Sh = tickets_frame(n)
    Sh['side'][:] = -1.0
    Sh['etype'][:] = 1
    Sh['entry'] = S.copy()
    Sh['cancel_hi'] = R.copy()
    Sh['stop0'] = R.copy()
    for tk in (L, Sh):
        tk['stop0'] = _floor(tk['side'], tk['entry'], tk['stop0'], st[:, A_])
        tk['target'] = _targets(tk['side'], tk['entry'], tk['stop0'], tgt, dict(I=np.zeros(n)))
        tk['act_c'] = st[:, T_].astype(np.int64) + 1
        tk['exp_c'] = st[:, T_].astype(np.int64) + E
        tk['tstop'][:] = T
    out = {}
    for key in L:
        out[key] = np.concatenate([L[key], Sh[key]])
    return out
