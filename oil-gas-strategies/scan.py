"""System 1 scanner + backtest for any daily OHLC CSV (e.g. your broker's continuous CL / BZ history).

  python3 scan.py --csv cl_daily.csv                      # backtest A and A+, list live setups
  python3 scan.py --csv cl_daily.csv --tick 0.01 --cost 0.02 --slip 0.01 --mult 1000
  python3 scan.py --market WTI_eia                         # built-in datasets: WTI_ohlc, WTI_eia, BRENT_eia

CSV: a date column (date / datetime / time) and open, high, low, close columns (any case). Daily bars.
If the file has only a close column, the scan runs on a closing basis (entries and exits at the close).

Output: backtest summary for version A (all setups) and A+ (volatility filter), then every setup whose
entry order is still live today or whose position is still open, with the exact levels to use.
"""
import argparse
import numpy as np, pandas as pd
from ogslib import Market, set_costs, run_tickets
import strategies as S
from system import PARAMS, EXITS, setups, filter_vol, run_system, perf, vol_percentile


def load_csv(path):
    df = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}
    dcol = next((cols[k] for k in ['date', 'datetime', 'time', 'timestamp'] if k in cols), df.columns[0])
    idx = pd.to_datetime(df[dcol], utc=True, errors='coerce').dt.tz_localize(None).dt.normalize()
    get = lambda k: pd.to_numeric(df[cols[k]], errors='coerce') if k in cols else None
    c = get('close') if get('close') is not None else get('price')
    if c is None:
        raise SystemExit('no close/price column found')
    o, h, l = get('open'), get('high'), get('low')
    close_only = o is None or h is None or l is None
    out = pd.DataFrame({'open': (c if close_only else o).values, 'high': (c if close_only else h).values,
                        'low': (c if close_only else l).values, 'close': c.values, 'volume': 0.0}, index=idx)
    out = out[~out.index.isna()].dropna(subset=['close']).sort_index()
    out = out[~out.index.duplicated(keep='last')]
    return out, close_only


def live_setups(mk, vf):
    """Current state under the one-position rule: the open position (if any), else live entry orders."""
    n = len(mk.c)
    rows = []
    tr = run_system(mk, 'HYB', vf)
    if len(tr):
        last = tr.iloc[-1]
        if int(last.exit_c) >= n - 1 and (last.why_mm == 4 or last.why_tr == 4):
            trail = mk.c[-1] - last.dir * EXITS['TR']['trail'] * mk.atr[-1]
            rows.append(dict(status='OPEN', side='LONG' if last.dir > 0 else 'SHORT', entered=str(last.entry_t.date()),
                             entry=round(float(last.entry_px), 4), protective_stop=round(float(last.stop_px), 4),
                             half1_target=round(float(last.target_px), 4) if last.why_mm == 4 else 'done',
                             half2_trail_now=round(float(trail), 4), risk_per_unit=round(abs(float(last.entry_px - last.stop_px)), 4)))
            return rows
    st = setups(mk)
    if vf:
        st = filter_vol(mk, st)
    recent = st[st[:, 0] >= n - 1 - PARAMS['E']] if len(st) else st
    seen = set()
    for k in range(len(recent)):
        s = recent[k:k + 1]
        a = run_tickets(mk, S.cont_breakout(s, E=PARAMS['E'], **EXITS['MM1'])).iloc[0]
        t_arm = int(s[0, 0]); d = s[0, 1]; R, Sx, atr, I = s[0, 4], s[0, 5], s[0, 6], s[0, 9]
        exp_c = t_arm + PARAMS['E']
        if a.filled == 1 or a.reason != -2 or exp_c <= n - 1:
            continue  # already triggered, cancelled or expired
        entry = R if d > 0 else Sx
        stop = min(Sx, entry - 0.5 * atr) if d > 0 else max(R, entry + 0.5 * atr)
        key = (d, round(entry, 6), round(stop, 6))
        if key in seen:
            continue
        seen.add(key)
        rows.append(dict(status='PENDING', side='LONG' if d > 0 else 'SHORT', box_from=str(mk.t[int(s[0, 8]) + 1].date()),
                         box_to=str(mk.t[t_arm].date()), entry_stop_order=round(entry, 4), cancel_if_trades=round(Sx if d > 0 else R, 4),
                         protective_stop=round(stop, 4), half1_target=round(entry + d * I, 4),
                         half2_trail=f'{EXITS["TR"]["trail"]} x ATR behind the close',
                         valid_for_bars=exp_c - (n - 1), risk_per_unit=round(abs(entry - stop), 4)))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--csv'); ap.add_argument('--market', choices=['WTI_ohlc', 'WTI_eia', 'BRENT_eia'])
    ap.add_argument('--name', default='WTI', help='cost template: WTI, BRENT, NG (default WTI)')
    ap.add_argument('--costs', default='futures', choices=['futures', 'cfd', 'zero'])
    ap.add_argument('--cost', type=float, help='custom round-trip cost per unit (overrides --costs)')
    ap.add_argument('--slip', type=float, default=None, help='custom slippage per stop fill')
    ap.add_argument('--mult', type=float, default=1000, help='units per contract for the dollar-risk line (CL/BZ 1000, MCL 100)')
    ap.add_argument('--risk', type=float, default=1000, help='account risk per trade in dollars for the sizing line')
    a = ap.parse_args()
    if a.market:
        name, src = {'WTI_ohlc': ('WTI', 'oanda'), 'WTI_eia': ('WTI', 'eia'), 'BRENT_eia': ('BRENT', 'eia')}[a.market]
        mk = Market(name, '1d', source=src)
    elif a.csv:
        bars, close_only = load_csv(a.csv)
        mk = Market(a.name, '1d', source='frame', fine=bars, close_only=close_only)
        print(f'loaded {len(bars)} daily bars {bars.index[0].date()} .. {bars.index[-1].date()}'
              + (' (close only: closing-basis execution)' if close_only else ''))
    else:
        raise SystemExit('give --csv FILE or --market NAME')
    regime = dict(cost=a.cost, slip=a.slip if a.slip is not None else 0.0) if a.cost is not None else a.costs
    print('\nBacktest, System 1 (HYB exits):')
    for vf in [False, True]:
        mk2 = set_costs(mk, regime)
        tr = run_system(mk2, 'HYB', vf, regime=regime)
        p = perf(tr)
        if p['n'] == 0:
            print(f'  {"A+" if vf else "A "}: no trades'); continue
        print(f'  {"A+" if vf else "A "}: {p["n"]} trades, {p["per_yr"]:.1f}/yr, win {p["win"]:.0%}, avg {p["avgR"]:+.2f}R, '
              f'PF {p["pf"]:.2f}, total {p["sumR"]:+.1f}R, max DD {p["maxddR"]:.1f}R')
    vp = vol_percentile(mk)
    print(f'\nToday ({mk.t[-1].date()}): close {mk.c[-1]:.4g}, ATR(20) {mk.atr[-1]:.4g}, '
          f'ATR/price percentile {vp[-1]:.0%} -> filter {"ON (A+ setups allowed)" if vp[-1] >= 0.5 else "OFF (A+ would skip new setups)"}')
    for vf in [True, False]:
        rows = live_setups(mk, vf)
        print(f'\nLive {"A+" if vf else "A"} setups: {len(rows) if rows else "none"}')
        for r in rows:
            print('  ' + ', '.join(f'{k}={v}' for k, v in r.items()))
            print(f'    sizing: ${a.risk:,.0f} risk / ({r["risk_per_unit"]} x {a.mult:g} units) = '
                  f'{a.risk / (r["risk_per_unit"] * a.mult):.2f} contracts')


if __name__ == '__main__':
    main()
