"""Core library for the oil & gas post-impulse consolidation study.

Pipeline:  fine bars (1-minute where available)  ->  coarse signal bars (1h / 4h / 1d)
           setup detector (impulse -> consolidation box) on coarse bars
           strategy family -> order tickets (stop / limit / market entries, stop, target, time stop)
           ticket simulator walks the FINE path, so stop-vs-target ordering inside a coarse bar is resolved
           by the actual minute-by-minute sequence (no optimistic same-bar assumptions).

Conventions
  * Signals use information up to the close of coarse bar t; orders are live from the open of bar t+1.
  * Stop entries fill at max(open, level) (+ slippage); limit entries need the price to trade THROUGH the
    level by `eps`; gaps fill at the open.
  * On the entry bar only the protective stop is checked (worst case); targets from the next fine bar on.
  * If stop and target are both touched in the same fine bar the stop is assumed first.
  * R-multiple = (side * (exit - entry) - round_trip_cost) / planned_risk, planned_risk = |entry_level - stop|.
"""
import os
import numpy as np
import pandas as pd
from numba import njit

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get('OGS_DATA', os.path.join(_HERE, 'data'))          # processed bars (data_build.py)
SRC = os.environ.get('OGS_SRC', os.path.join(_HERE, 'sources'))         # cloned source repos (fetch_data.sh)

# Cost regimes, in price units.  cost = round-trip spread + commission per trade; slip = extra slippage applied
# to every STOP fill (stop entries and protective stops); eps = how far price must trade through a limit.
#   futures : CL 1-tick spread + ~$3 RT commission; NG 1-2 ticks + commission
#   cfd     : typical retail CFD spreads (USOIL/UKOIL avg ~3-4c, NATGAS avg ~0.8-1.4c; BrokerChooser data)
COST_REGIMES = {
    'futures': {'WTI': dict(cost=0.015, slip=0.01, eps=0.005), 'BRENT': dict(cost=0.015, slip=0.01, eps=0.005),
                'NG': dict(cost=0.002, slip=0.001, eps=0.0005), 'HH': dict(cost=0.002, slip=0.001, eps=0.0005)},
    'cfd': {'WTI': dict(cost=0.04, slip=0.01, eps=0.005), 'BRENT': dict(cost=0.04, slip=0.01, eps=0.005),
            'NG': dict(cost=0.010, slip=0.001, eps=0.0005), 'HH': dict(cost=0.010, slip=0.001, eps=0.0005)},
    'zero': {k: dict(cost=0.0, slip=0.0, eps=0.0) for k in ['WTI', 'BRENT', 'NG', 'HH']},
}
COSTS = COST_REGIMES['cfd']
CLOSE_ONLY_ATR_SCALE = 1.95


def set_costs(mk, regime):
    if isinstance(regime, dict):  # custom {'cost':..., 'slip':..., 'eps':...}
        mk.cost, mk.slip, mk.eps = regime['cost'], regime['slip'], regime.get('eps', 0.0)
        return mk
    cc = COST_REGIMES[regime].get(mk.name, COST_REGIMES[regime]['WTI'])
    mk.cost, mk.slip, mk.eps = cc['cost'], cc['slip'], cc['eps']
    return mk


# --------------------------------------------------------------------------------------------- data

def _ny(idx_utc):
    return idx_utc.tz_localize('UTC').tz_convert('America/New_York').tz_localize(None)


def load_fine(name, source='oanda'):
    """Fine execution bars indexed in New York local time (tz-naive)."""
    if source == 'oanda':
        inst = {'WTI': 'WTICO_USD', 'NG': 'NATGAS_USD'}[name]
        m = pd.read_parquet(f'{DATA}/{inst}_1m.parquet').loc[:'2020-04-15']
        m.index = _ny(m.index)
        return m
    if source == 'getdata':
        import glob
        sym = {'WTI': 'usoil', 'BRENT': 'ukoil'}[name]
        fs = glob.glob(f'{SRC}/getdata-finance/{sym}-1m-ohlcv-commodities-historical-data/*.csv')
        if not fs:
            fs = glob.glob(f'{SRC}/getdata-finance/{sym}-1h-ohlcv-commodities-historical-data/*.csv')
        h = pd.read_csv(fs[0])
        h['datetime'] = pd.to_datetime(h['datetime'], utc=True).dt.tz_localize(None)
        h = h.set_index('datetime')[['open', 'high', 'low', 'close', 'volume']].sort_index()
        h.index = _ny(h.index)
        return h
    if source == 'eia':
        s = pd.read_parquet(f'{DATA}/{name}_eia_1d.parquet')['close']
        s = s[s > 0]  # the -36.98 WTI print of 2020-04-20 breaks ratio maths; drop that single day
        return pd.DataFrame({'open': s, 'high': s, 'low': s, 'close': s, 'volume': 0.0})
    raise ValueError(source)


def coarse_labels(idx, tf):
    if tf == '1h':
        return idx.floor('h')
    if tf == '4h':
        return (idx + pd.Timedelta(hours=6)).floor('4h') - pd.Timedelta(hours=6)
    if tf == '1d':
        return (idx + pd.Timedelta(hours=6)).floor('D')
    raise ValueError(tf)


class Market:
    """Fine path + coarse bars with exact fine<->coarse index mapping."""

    def __init__(self, name, tf, source='oanda', fine=None, close_only=False):
        self.name, self.tf, self.source = name, tf, source
        f = load_fine(name, source) if fine is None else fine
        if source in ('eia', 'frame'):
            # 'frame': caller-supplied bars used as-is (one fine bar per coarse bar), e.g. a broker's daily CSV
            lab = f.index
        else:
            lab = coarse_labels(f.index, tf)
            if tf == '1d':
                keep = lab.dayofweek < 5
                f, lab = f[keep], lab[keep]
        f = f.copy()
        f['lab'] = lab
        g = f.groupby('lab', sort=True)
        cb = g.agg(open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last'),
                   volume=('volume', 'sum'), n=('close', 'size'))
        if tf == '1d' and source not in ('eia', 'frame'):
            # drop holiday stubs (< ~2 trading hours); their bars are removed from the fine path too
            step_min = max(1.0, np.median(np.diff(f.index.values).astype('timedelta64[m]').astype(float)))
            good = cb.index[cb['n'] >= 120 / step_min]
            f = f[f['lab'].isin(good)]
            cb = cb.loc[good]
        if close_only:
            # degrade to a closing-price-only series (used to calibrate the EIA close-only tests)
            cb = cb.assign(open=cb.close, high=cb.close, low=cb.close)
            f = pd.DataFrame({'open': cb.close.values, 'high': cb.close.values, 'low': cb.close.values,
                              'close': cb.close.values, 'volume': 0.0, 'lab': cb.index}, index=cb.index)
        self.fine = f
        self.bars = cb
        lab_vals = f['lab'].values
        codes = np.searchsorted(cb.index.values, lab_vals)
        self.f_coarse = codes.astype(np.int64)
        n = len(cb)
        first = np.full(n, -1, np.int64)
        last = np.full(n, -1, np.int64)
        idx = np.arange(len(codes))
        # codes are non-decreasing
        chg = np.r_[True, codes[1:] != codes[:-1]]
        first[codes[chg]] = idx[chg]
        endm = np.r_[codes[1:] != codes[:-1], True]
        last[codes[endm]] = idx[endm]
        self.c_first, self.c_last = first, last
        self.fo = f['open'].values.astype(np.float64)
        self.fh = f['high'].values.astype(np.float64)
        self.fl = f['low'].values.astype(np.float64)
        self.fc = f['close'].values.astype(np.float64)
        self.o = cb['open'].values.astype(np.float64)
        self.h = cb['high'].values.astype(np.float64)
        self.l = cb['low'].values.astype(np.float64)
        self.c = cb['close'].values.astype(np.float64)
        self.t = cb.index
        self.atr = atr(self.h, self.l, self.c, 20)
        if close_only or source == 'eia':
            # close-only 'ATR' (mean |dClose|) is ~half the true-range ATR of the same market; rescale so that
            # parameters expressed in ATR units mean the same thing on OHLC and close-only data.
            # Calibrated on the 2005-2020 OANDA overlap: median ratio 1.96 (WTI), 1.90 (NG).
            self.atr = self.atr * CLOSE_ONLY_ATR_SCALE
        cc = COSTS.get(name, COSTS['WTI'])
        self.cost, self.slip, self.eps = cc['cost'], cc['slip'], cc['eps']


@njit(cache=True)
def atr(h, l, c, n):
    m = len(c)
    tr = np.empty(m)
    tr[0] = h[0] - l[0]
    for i in range(1, m):
        a = h[i] - l[i]
        b = abs(h[i] - c[i - 1])
        d = abs(l[i] - c[i - 1])
        tr[i] = max(a, max(b, d))
    out = np.full(m, np.nan)
    s = 0.0
    for i in range(m):
        s += tr[i]
        if i >= n:
            s -= tr[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


# --------------------------------------------------------------------------------------------- setups

@njit(cache=True)
def detect_flags(h, l, c, atr, imp_n, imp_k, cons_m, box_f, max_ret):
    """Impulse (imp_n bars, net close-to-close move >= imp_k * pre-impulse ATR) followed by a consolidation
    of exactly cons_m bars whose total range <= box_f * impulse size and which retraces <= max_ret of the
    impulse.  Returns rows: t_arm, dir, P0 (impulse origin), P1 (impulse extreme), R (box high), S (box low),
    atr_pre, s (impulse first bar), e (impulse last bar), I (impulse size)."""
    n = len(c)
    out = np.empty((n, 10))
    k = 0
    last_t = -1
    for t in range(imp_n + cons_m + 21, n):
        e = t - cons_m
        s = e - imp_n + 1
        if s <= last_t:
            continue
        a = atr[s - 1]
        if not (a > 0):
            continue
        net = c[e] - c[s - 1]
        if abs(net) < imp_k * a:
            continue
        d = 1.0 if net > 0 else -1.0
        hi = h[s]
        lo = l[s]
        for j in range(s, e + 1):
            hi = max(hi, h[j])
            lo = min(lo, l[j])
        lo = min(lo, c[s - 1])
        hi = max(hi, c[s - 1])
        if d > 0:
            P0, P1 = lo, hi
        else:
            P0, P1 = hi, lo
        I = hi - lo
        R = h[e + 1]
        S = l[e + 1]
        for j in range(e + 1, t + 1):
            R = max(R, h[j])
            S = min(S, l[j])
        if R - S > box_f * I:
            continue
        if d > 0:
            if S < P1 - max_ret * I:
                continue
        else:
            if R > P1 + max_ret * I:
                continue
        out[k, 0] = t
        out[k, 1] = d
        out[k, 2] = P0
        out[k, 3] = P1
        out[k, 4] = R
        out[k, 5] = S
        out[k, 6] = a
        out[k, 7] = s
        out[k, 8] = e
        out[k, 9] = I
        k += 1
        last_t = t
    return out[:k]


@njit(cache=True)
def detect_boxes(h, l, c, atr, cons_m, box_atr, min_gap):
    """Benchmark: any tight box of cons_m bars (range <= box_atr * ATR measured before the box), no impulse
    requirement.  Rows: t_arm, 0, nan, nan, R, S, atr_pre, s, e, 0"""
    n = len(c)
    out = np.empty((n, 10))
    k = 0
    last_t = -10 ** 9
    for t in range(cons_m + 21, n):
        if t - last_t < min_gap:
            continue
        b0 = t - cons_m + 1
        a = atr[b0 - 1]
        if not (a > 0):
            continue
        R = h[b0]
        S = l[b0]
        for j in range(b0, t + 1):
            R = max(R, h[j])
            S = min(S, l[j])
        if R - S > box_atr * a:
            continue
        out[k, 0] = t
        out[k, 1] = 0.0
        out[k, 2] = np.nan
        out[k, 3] = np.nan
        out[k, 4] = R
        out[k, 5] = S
        out[k, 6] = a
        out[k, 7] = b0
        out[k, 8] = b0 - 1
        out[k, 9] = 0.0
        k += 1
        last_t = t
    return out[:k]


@njit(cache=True)
def detect_impulses(h, l, c, atr, imp_n, imp_k, min_gap):
    """Plain impulse detector (armed at the impulse's last bar).  Rows as detect_flags with R=S=nan."""
    n = len(c)
    out = np.empty((n, 10))
    k = 0
    last_e = -10 ** 9
    for e in range(imp_n + 21, n):
        s = e - imp_n + 1
        if s - last_e < min_gap:
            continue
        a = atr[s - 1]
        if not (a > 0):
            continue
        net = c[e] - c[s - 1]
        if abs(net) < imp_k * a:
            continue
        d = 1.0 if net > 0 else -1.0
        hi = max(h[s], c[s - 1])
        lo = min(l[s], c[s - 1])
        for j in range(s, e + 1):
            hi = max(hi, h[j])
            lo = min(lo, l[j])
        out[k, 0] = e
        out[k, 1] = d
        out[k, 2] = lo if d > 0 else hi
        out[k, 3] = hi if d > 0 else lo
        out[k, 4] = np.nan
        out[k, 5] = np.nan
        out[k, 6] = a
        out[k, 7] = s
        out[k, 8] = e
        out[k, 9] = hi - lo
        k += 1
        last_e = e
    return out[:k]


@njit(cache=True)
def detect_bases(h, l, c, atr, base_m, base_atr, imp_n, imp_k):
    """Supply/demand 'origin zone': a tight base of base_m bars (range <= base_atr*ATR) immediately followed by
    an impulse of imp_n bars (net move >= imp_k*ATR) leaving the base.  Armed at the impulse's last bar.
    Rows: t_arm(e), dir, P0(base far edge), P1(impulse extreme), zone_hi, zone_lo, atr_pre, s, e, I"""
    n = len(c)
    out = np.empty((n, 10))
    k = 0
    last_e = -10 ** 9
    for e in range(base_m + imp_n + 21, n):
        s = e - imp_n + 1
        if s <= last_e:
            continue
        b0 = s - base_m
        a = atr[b0 - 1]
        if not (a > 0):
            continue
        zh = h[b0]
        zl = l[b0]
        for j in range(b0, s):
            zh = max(zh, h[j])
            zl = min(zl, l[j])
        if zh - zl > base_atr * a:
            continue
        net = c[e] - c[s - 1]
        if abs(net) < imp_k * a:
            continue
        d = 1.0 if net > 0 else -1.0
        hi = h[s]
        lo = l[s]
        for j in range(s, e + 1):
            hi = max(hi, h[j])
            lo = min(lo, l[j])
        # impulse must leave the zone decisively
        if d > 0 and c[e] < zh + 0.5 * (imp_k * a):
            continue
        if d < 0 and c[e] > zl - 0.5 * (imp_k * a):
            continue
        out[k, 0] = e
        out[k, 1] = d
        out[k, 2] = zl if d > 0 else zh
        out[k, 3] = hi if d > 0 else lo
        out[k, 4] = zh
        out[k, 5] = zl
        out[k, 6] = a
        out[k, 7] = s
        out[k, 8] = e
        out[k, 9] = (hi - zl) if d > 0 else (zh - lo)
        k += 1
        last_e = e
    return out[:k]


# --------------------------------------------------------------------------------------------- simulator

@njit(cache=True)
def simulate(fo, fh, fl, fc, f_coarse, c_first, c_last, c_close, c_atr,
             act_c, exp_c, side, etype, entry, cancel_hi, cancel_lo, stop0, target, tstop, trail_k, be_r,
             slip, cost, eps):
    """Simulate independent order tickets on the fine path.
    etype: 0 market (open of first fine bar of act_c), 1 stop, 2 limit.
    Returns rows: filled, entry_f, entry_px, exit_f, exit_px, reason, R, mfe_R, mae_R, entry_c, exit_c
    reason: 1 stop, 2 target, 3 time, 4 end-of-data, 5 stop-on-entry-bar, -1 cancelled, -2 expired."""
    m = len(side)
    nf = len(fo)
    nc = len(c_first)
    res = np.full((m, 11), np.nan)
    for k in range(m):
        ac = act_c[k]
        if ac >= nc:
            res[k, 0] = 0.0
            res[k, 5] = -2.0
            continue
        ec = min(exp_c[k], nc - 1)
        i0 = c_first[ac]
        i1 = c_last[ec]
        sd = side[k]
        L = entry[k]
        filled = False
        px = 0.0
        i = i0
        reason = -2.0
        while i <= i1:
            o = fo[i]
            hh = fh[i]
            ll = fl[i]
            if etype[k] == 0:
                px = o + sd * slip
                filled = True
                break
            if etype[k] == 1:
                hit_e = (hh >= L) if sd > 0 else (ll <= L)
            else:
                hit_e = (ll <= L - eps) if sd > 0 else (hh >= L + eps)
            hit_c = (hh >= cancel_hi[k]) or (ll <= cancel_lo[k])
            if hit_c and hit_e:
                dc = min(abs(cancel_hi[k] - o), abs(o - cancel_lo[k]))
                de = abs(L - o)
                if dc < de:
                    reason = -1.0
                    break
            elif hit_c:
                reason = -1.0
                break
            if hit_e:
                if etype[k] == 1:
                    if sd > 0:
                        px = max(o, L) + slip
                    else:
                        px = min(o, L) - slip
                else:
                    if sd > 0:
                        px = min(o, L)
                    else:
                        px = max(o, L)
                filled = True
                break
            i += 1
        if not filled:
            res[k, 0] = 0.0
            res[k, 5] = reason
            continue
        e_i = i
        e_px = px
        st = stop0[k]
        tg = target[k]
        ref = L if etype[k] != 0 else e_px
        risk = abs(ref - st)
        if risk <= 0:
            res[k, 0] = 0.0
            res[k, 5] = -3.0
            continue
        e_c = f_coarse[e_i]
        t_exit_c = e_c + tstop[k] if tstop[k] > 0 else 1 << 60
        mfe = 0.0
        mae = 0.0
        x_px = 0.0
        x_i = -1
        why = 0.0
        # worst case on the entry bar: protective stop only
        if sd > 0 and fl[e_i] <= st:
            x_px = min(st, fc[e_i]) - slip
            x_i = e_i
            why = 5.0
        elif sd < 0 and fh[e_i] >= st:
            x_px = max(st, fc[e_i]) + slip
            x_i = e_i
            why = 5.0
        else:
            if sd > 0:
                mfe = max(mfe, fh[e_i] - e_px)
                mae = max(mae, e_px - fl[e_i])
            else:
                mfe = max(mfe, e_px - fl[e_i])
                mae = max(mae, fh[e_i] - e_px)
            # coarse bar end on the entry bar
            j = e_i
            if j == c_last[f_coarse[j]]:
                cidx = f_coarse[j]
                if cidx >= t_exit_c:
                    x_px = fc[j]
                    x_i = j
                    why = 3.0
                else:
                    if trail_k[k] > 0:
                        nv = c_close[cidx] - sd * trail_k[k] * c_atr[cidx]
                        st = max(st, nv) if sd > 0 else min(st, nv)
                    if be_r[k] > 0 and mfe >= be_r[k] * risk:
                        st = max(st, e_px) if sd > 0 else min(st, e_px)
            j = e_i + 1
            while x_i < 0 and j < nf:
                o = fo[j]
                hh = fh[j]
                ll = fl[j]
                if sd > 0:
                    if o <= st:
                        x_px = o - slip
                        x_i = j
                        why = 1.0
                        break
                    if ll <= st:
                        x_px = st - slip
                        x_i = j
                        why = 1.0
                        break
                    if tg == tg:
                        if o >= tg:
                            x_px = o
                            x_i = j
                            why = 2.0
                            break
                        if hh >= tg:
                            x_px = tg
                            x_i = j
                            why = 2.0
                            break
                    mfe = max(mfe, hh - e_px)
                    mae = max(mae, e_px - ll)
                else:
                    if o >= st:
                        x_px = o + slip
                        x_i = j
                        why = 1.0
                        break
                    if hh >= st:
                        x_px = st + slip
                        x_i = j
                        why = 1.0
                        break
                    if tg == tg:
                        if o <= tg:
                            x_px = o
                            x_i = j
                            why = 2.0
                            break
                        if ll <= tg:
                            x_px = tg
                            x_i = j
                            why = 2.0
                            break
                    mfe = max(mfe, e_px - ll)
                    mae = max(mae, hh - e_px)
                if j == c_last[f_coarse[j]]:
                    cidx = f_coarse[j]
                    if cidx >= t_exit_c:
                        x_px = fc[j]
                        x_i = j
                        why = 3.0
                        break
                    if trail_k[k] > 0:
                        nv = c_close[cidx] - sd * trail_k[k] * c_atr[cidx]
                        st = max(st, nv) if sd > 0 else min(st, nv)
                    if be_r[k] > 0 and mfe >= be_r[k] * risk:
                        st = max(st, e_px) if sd > 0 else min(st, e_px)
                j += 1
            if x_i < 0:
                x_i = nf - 1
                x_px = fc[nf - 1]
                why = 4.0
        pnl = sd * (x_px - e_px) - cost
        res[k, 0] = 1.0
        res[k, 1] = e_i
        res[k, 2] = e_px
        res[k, 3] = x_i
        res[k, 4] = x_px
        res[k, 5] = why
        res[k, 6] = pnl / risk
        res[k, 7] = mfe / risk
        res[k, 8] = mae / risk
        res[k, 9] = e_c
        res[k, 10] = f_coarse[x_i]
    return res


def tickets_frame(n):
    return dict(act_c=np.zeros(n, np.int64), exp_c=np.zeros(n, np.int64), side=np.zeros(n),
                etype=np.zeros(n, np.int64), entry=np.full(n, np.nan), cancel_hi=np.full(n, np.inf),
                cancel_lo=np.full(n, -np.inf), stop0=np.full(n, np.nan), target=np.full(n, np.nan),
                tstop=np.zeros(n, np.int64), trail_k=np.zeros(n), be_r=np.zeros(n), setup=np.arange(n))


def run_tickets(mk, tk, cost_mult=1.0):
    if len(tk['side']) == 0:
        return pd.DataFrame(columns=['filled', 'entry_f', 'entry_px', 'exit_f', 'exit_px', 'reason', 'R', 'mfe',
                                     'mae', 'entry_c', 'exit_c', 'side', 'setup'])
    r = simulate(mk.fo, mk.fh, mk.fl, mk.fc, mk.f_coarse, mk.c_first, mk.c_last, mk.c, mk.atr,
                 tk['act_c'].astype(np.int64), tk['exp_c'].astype(np.int64), tk['side'].astype(np.float64),
                 tk['etype'].astype(np.int64), tk['entry'].astype(np.float64), tk['cancel_hi'].astype(np.float64),
                 tk['cancel_lo'].astype(np.float64), tk['stop0'].astype(np.float64),
                 tk['target'].astype(np.float64), tk['tstop'].astype(np.int64), tk['trail_k'].astype(np.float64),
                 tk['be_r'].astype(np.float64), mk.slip * cost_mult, mk.cost * cost_mult, mk.eps)
    df = pd.DataFrame(r, columns=['filled', 'entry_f', 'entry_px', 'exit_f', 'exit_px', 'reason', 'R', 'mfe',
                                  'mae', 'entry_c', 'exit_c'])
    df['side'] = tk['side']
    df['setup'] = tk['setup']
    return df


def non_overlap(tr):
    """One position at a time: keep trades in entry order whose entry is after the previous kept exit."""
    tr = tr[tr.filled == 1].sort_values('entry_f')
    keep = []
    last_exit = -1
    for ef, xf in zip(tr.entry_f.values, tr.exit_f.values):
        if ef > last_exit:
            keep.append(True)
            last_exit = xf
        else:
            keep.append(False)
    return tr[np.array(keep, bool)] if len(tr) else tr


def stats(R, years=None):
    R = np.asarray(R, float)
    n = len(R)
    if n == 0:
        return dict(n=0, win=np.nan, avgR=np.nan, medR=np.nan, pf=np.nan, sumR=0.0, t=np.nan, maxdd=np.nan,
                    per_yr=np.nan)
    w = R[R > 0].sum()
    lsum = -R[R < 0].sum()
    eq = np.cumsum(R)
    dd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    sd = R.std(ddof=1) if n > 1 else np.nan
    return dict(n=n, win=(R > 0).mean(), avgR=R.mean(), medR=np.median(R), pf=(w / lsum) if lsum > 0 else np.inf,
                sumR=R.sum(), t=R.mean() / sd * np.sqrt(n) if sd and sd > 0 else np.nan, maxdd=dd,
                per_yr=n / years if years else np.nan)
