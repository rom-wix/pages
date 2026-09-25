"""Build clean OHLC bar sets for the oil & gas study.

Sources (all public GitHub repos; the session's network policy blocks Yahoo/FRED/EIA/Stooq):
  1. FutureSharks/financial-data  -> OANDA CFD 1-minute bars, WTICO_USD & NATGAS_USD, 2005-01 .. 2020-05 (UTC)
     OANDA commodity CFDs are carry-adjusted "cash" prices: no futures-roll gaps (verified vs EIA spot).
  2. getdata-finance/{usoil,ukoil}-1h-ohlcv-commodities-historical-data -> CFD 1-hour bars 2026-03-23 .. 2026-09-23 (UTC)
  3. datasets/oil-prices, datasets/natural-gas -> EIA daily spot closes (WTI 1986-, Brent 1987-, Henry Hub 1997-) to 2026-09-22

Session convention: CME energy trading day = 18:00 (prev day) .. 17:00 America/New_York.
Daily bar date = session end date. 4H bars start 18:00, 22:00, 02:00, 06:00, 10:00, 14:00 NY time.
"""
import glob, os
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
# cloned source repos (see fetch_data.sh) and the processed-bar cache; both are git-ignored
HOME = os.environ.get('OGS_SRC', os.path.join(HERE, 'sources'))
OUT = os.environ.get('OGS_DATA', os.path.join(HERE, 'data'))
os.makedirs(OUT, exist_ok=True)
AGG = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}


def load_oanda_1m(inst):
    p = f'{OUT}/{inst}_1m.parquet'
    if os.path.exists(p):
        return pd.read_parquet(p)
    base = f'{HOME}/futuresharks/financial-data/pyfinancialdata/data/currencies/oanda/{inst}'
    df = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(f'{base}/*/*.csv'))], ignore_index=True)
    df['time'] = pd.to_datetime(df['time'])
    df = df.drop_duplicates('time').sort_values('time').set_index('time')[['open', 'high', 'low', 'close', 'volume']]
    df.to_parquet(p)
    return df


def to_session_time(df):
    """UTC index -> 'session clock': NY local time shifted +6h so each trading day starts at 00:00."""
    ny = df.index.tz_localize('UTC').tz_convert('America/New_York').tz_localize(None)
    out = df.copy()
    out.index = ny + pd.Timedelta(hours=6)
    return out


def resample_bars(df_utc, rule):
    s = to_session_time(df_utc)
    if rule == '1D':
        g = s.groupby(s.index.normalize())
        bars = g.agg(AGG)
        bars['n'] = g.size()
    else:
        r = s.resample(rule, label='left', closed='left')
        bars = r.agg(AGG)
        bars['n'] = r.size()
    bars = bars.dropna(subset=['open'])
    # drop Saturday-session artefacts (a handful of stray prints)
    bars = bars[bars.index.dayofweek < 5] if rule == '1D' else bars
    # map session-clock label back to NY local start time for intraday bars
    if rule != '1D':
        bars.index = bars.index - pd.Timedelta(hours=6)
    return bars


def build_oanda():
    for inst, name in [('WTICO_USD', 'WTI'), ('NATGAS_USD', 'NG')]:
        m = load_oanda_1m(inst)
        # cut the April-May 2020 negative-price / super-contango dislocation tail
        m = m.loc[:'2020-04-15']
        h1 = m.resample('1h', label='left', closed='left').agg(AGG).dropna(subset=['open'])
        h1.index = h1.index.tz_localize('UTC').tz_convert('America/New_York').tz_localize(None)
        h4 = resample_bars(m, '4h')
        d1 = resample_bars(m, '1D')
        for tf, b in [('1h', h1), ('4h', h4), ('1d', d1)]:
            b.to_parquet(f'{OUT}/{name}_oanda_{tf}.parquet')
            print(name, tf, len(b), b.index.min(), b.index.max())


def build_getdata():
    for sym, name in [('usoil', 'WTI'), ('ukoil', 'BRENT')]:
        f = glob.glob(f'{HOME}/getdata-finance/{sym}-1h-ohlcv-commodities-historical-data/*.csv')[0]
        h = pd.read_csv(f)
        h['datetime'] = pd.to_datetime(h['datetime'], utc=True).dt.tz_localize(None)
        h = h.set_index('datetime')[['open', 'high', 'low', 'close', 'volume']].sort_index()
        h1 = h.copy()
        h1.index = h1.index.tz_localize('UTC').tz_convert('America/New_York').tz_localize(None)
        h4 = resample_bars(h, '4h')
        d1 = resample_bars(h, '1D')
        for tf, b in [('1h', h1), ('4h', h4), ('1d', d1)]:
            b.to_parquet(f'{OUT}/{name}_2026_{tf}.parquet')
            print(name, '2026', tf, len(b), b.index.min(), b.index.max())


def build_eia():
    src = {'WTI': f'{HOME}/datasets/oil-prices/data/wti-daily.csv',
           'BRENT': f'{HOME}/datasets/oil-prices/data/brent-daily.csv',
           'HH': f'{HOME}/datasets/natural-gas/data/daily.csv'}
    for name, f in src.items():
        s = pd.read_csv(f, parse_dates=['Date']).set_index('Date')['Price'].sort_index()
        s = s[~s.index.duplicated()].dropna()
        pd.DataFrame({'close': s}).to_parquet(f'{OUT}/{name}_eia_1d.parquet')
        print(name, 'eia', len(s), s.index.min(), s.index.max())


if __name__ == '__main__':
    build_oanda()
    build_getdata()
    build_eia()
