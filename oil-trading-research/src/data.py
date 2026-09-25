"""Data layer for the oil/gas CFD research.

Sources (all public GitHub mirrors; see scripts/fetch_data.sh):
  * pysystemtrade  - back-adjusted continuous futures + "multiple prices" (held / nearer / further contract)
                     for WTI (CRUDE_W), Brent (BRENT_W), Henry Hub gas (GAS_US) ... 1989 -> 2024-03-28
  * datahub        - EIA daily spot prices: WTI Cushing, Brent FOB, Henry Hub      ... 1986 -> 2026-09-22
  * FutureSharks   - Oanda 1-minute mid candles, WTICO_USD and NATGAS_USD CFDs      ... 2005 -> 2020-05-14

Mapping to the broker symbols the bot will trade:
  XTIUSD  <- WTI     (CRUDE_W futures, EIA WTI spot, Oanda WTICO_USD)
  XBRUSD  <- Brent   (BRENT_W futures, EIA Brent spot)
  XNGUSD  <- NatGas  (GAS_US futures, EIA Henry Hub spot, Oanda NATGAS_USD)
"""
from __future__ import annotations

import glob
import os
from functools import lru_cache

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, "data")
os.makedirs(CACHE, exist_ok=True)


def _first_existing(*paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return paths[0]


EXT = os.environ.get("EXT", os.path.expanduser("~/_ext"))
PYSYS = _first_existing(os.path.join(EXT, "pysystemtrade"), "/home/user/robcarver17/pysystemtrade")
OILP = _first_existing(os.path.join(EXT, "oil-prices"), "/home/user/datasets/oil-prices")
NGAS = _first_existing(os.path.join(EXT, "natural-gas"), "/home/user/datasets/natural-gas")
OANDA = _first_existing(os.path.join(EXT, "financial-data"), "/home/user/futuresharks/financial-data")
OANDA = os.path.join(OANDA, "pyfinancialdata/data/currencies/oanda")

SYMBOLS = ["XTIUSD", "XBRUSD", "XNGUSD"]
FUT_CODE = {"XTIUSD": "CRUDE_W", "XBRUSD": "BRENT_W", "XNGUSD": "GAS_US"}
OANDA_CODE = {"XTIUSD": "WTICO_USD", "XNGUSD": "NATGAS_USD"}
NAMES = {"XTIUSD": "WTI crude", "XBRUSD": "Brent crude", "XNGUSD": "US natural gas"}


# ----------------------------------------------------------------------------------------------
# Futures (pysystemtrade)
# ----------------------------------------------------------------------------------------------
def _read_pysys(kind: str, code: str) -> pd.DataFrame:
    path = os.path.join(PYSYS, "data/futures", kind, f"{code}.csv")
    df = pd.read_csv(path, parse_dates=["DATETIME"]).set_index("DATETIME").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def _daily_close(s: pd.Series) -> pd.Series:
    s = s.dropna()
    day = s.index.normalize()
    last_any = s.groupby(day).last()
    early = s[s.index.hour <= 20]
    last_early = early.groupby(early.index.normalize()).last()
    return last_early.reindex(last_any.index).fillna(last_any)


def _contract_months_apart(a: pd.Series, b: pd.Series) -> pd.Series:
    """YYYYMM00 ints -> signed month distance b - a."""
    a = a.astype("Int64") // 100
    b = b.astype("Int64") // 100
    ya, ma = a // 100, a % 100
    yb, mb = b // 100, b % 100
    return ((yb - ya) * 12 + (mb - ma)).astype(float)


@lru_cache(maxsize=None)
def futures_daily(code: str) -> pd.DataFrame:
    """Daily (last print per calendar day) rolled futures for a pysystemtrade instrument.

    Columns
      adj     : back-adjusted (Panama) price, continuous across rolls
      price   : price of the contract actually held (unadjusted)
      contract: held contract (YYYYMM00)
      carry_px: price of the nearer contract used for carry
      ret     : daily % return of the rolled position  = d(adj) / price[t-1]
      tri     : total-return index built from ret (use for signals: no roll gaps)
      carry   : annualised roll yield ~ (carry_px - price)/price * 12/months_apart  (>0 = backwardation)
    """
    adj = _read_pysys("adjusted_prices_csv", code)["price"]
    mp = _read_pysys("multiple_prices_csv", code)
    # Daily close. Pre-2013 the files hold one settlement print per day stamped 23:00.  From ~2013 they
    # hold hourly (London-time) bars *plus* a 23:00 print that is stale/noisy (for Brent it lags by a day:
    # corr with EIA spot 0.27 vs 0.86 for the 20:00 bar).  Rule: use the last print at or before 20:00
    # London (~ the 19:30 settlement) when the day has intraday prints, else the day's only print.
    adj_d = _daily_close(adj)
    mp_d = pd.DataFrame({c: _daily_close(mp[c]) for c in mp.columns})
    df = pd.DataFrame({"adj": adj_d}).join(mp_d, how="left")
    df = df.rename(columns={"PRICE": "price", "PRICE_CONTRACT": "contract", "CARRY": "carry_px",
                            "CARRY_CONTRACT": "carry_contract", "FORWARD": "fwd_px",
                            "FORWARD_CONTRACT": "fwd_contract"})
    df["price"] = df["price"].ffill()
    df = df[df.index.dayofweek < 5]
    dadj = df["adj"].diff()
    df["ret"] = dadj / df["price"].shift(1)
    # guard against bad prints: returns beyond +/-40% in a day are data errors for deferred contracts
    df.loc[df["ret"].abs() > 0.4, "ret"] = np.nan
    df["ret"] = df["ret"].fillna(0.0)
    df["tri"] = (1 + df["ret"]).cumprod()
    months = _contract_months_apart(df["carry_contract"], df["contract"])  # >0 if carry contract is nearer
    raw = (df["carry_px"] - df["price"]) / df["price"]
    df["carry"] = (raw * 12.0 / months.replace(0, np.nan)).where(months.abs() >= 1)
    df["carry"] = df["carry"].ffill(limit=5)
    df.index.name = "date"
    return df.iloc[1:]


# ----------------------------------------------------------------------------------------------
# EIA spot (datahub mirrors)
# ----------------------------------------------------------------------------------------------
@lru_cache(maxsize=None)
def spot_daily() -> pd.DataFrame:
    def rd(p, name):
        s = pd.read_csv(p)
        s.columns = ["date", name]
        s["date"] = pd.to_datetime(s["date"])
        s[name] = pd.to_numeric(s[name], errors="coerce")
        return s.set_index("date")[name]

    w = rd(os.path.join(OILP, "data/wti-daily.csv"), "XTIUSD")
    b = rd(os.path.join(OILP, "data/brent-daily.csv"), "XBRUSD")
    g = rd(os.path.join(NGAS, "data/daily.csv"), "XNGUSD")
    df = pd.concat([w, b, g], axis=1).sort_index()
    df = df[df.index.dayofweek < 5]
    return df


def spot_returns(sym: str, start=None) -> pd.Series:
    """Simple daily returns of EIA spot. Non-positive prints (WTI 2020-04-20) are dropped."""
    s = spot_daily()[sym].dropna()
    s = s[s > 0]
    r = s.pct_change().dropna()
    if start is not None:
        r = r[r.index >= start]
    return r


# ----------------------------------------------------------------------------------------------
# Oanda 1-minute CFD candles (mid) -> cached parquet, UTC timestamps
# ----------------------------------------------------------------------------------------------
def oanda_minutes(sym: str) -> pd.DataFrame:
    code = OANDA_CODE[sym]
    cache = os.path.join(CACHE, f"oanda_{code}_M1.parquet")
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    files = sorted(glob.glob(os.path.join(OANDA, code, "*", "*.csv")))
    parts = [pd.read_csv(f, parse_dates=["time"]) for f in files]
    df = pd.concat(parts).set_index("time").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df = df[["open", "high", "low", "close", "volume"]].astype(
        {"open": "float64", "high": "float64", "low": "float64", "close": "float64", "volume": "float64"})
    df.index = df.index.tz_localize("UTC")
    df.to_parquet(cache)
    return df


def resample_ohlc(m1: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample minute candles; bars are labelled by their *start* time (closed='left')."""
    agg = m1.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return agg.dropna(subset=["close"])


def oanda_bars(sym: str, rule: str = "5min") -> pd.DataFrame:
    code = OANDA_CODE[sym]
    cache = os.path.join(CACHE, f"oanda_{code}_{rule}.parquet")
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    bars = resample_ohlc(oanda_minutes(sym), rule)
    bars.to_parquet(cache)
    return bars


def to_ny(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return idx.tz_convert("America/New_York")


def oanda_daily(sym: str, cut_hour_ny: int = 17) -> pd.DataFrame:
    """Daily bars cut at `cut_hour_ny` New York time (17:00 = CME/NYMEX session end).
    The trading date is the NY date of the session end."""
    m1 = oanda_minutes(sym)
    ny = to_ny(m1.index)
    # shift so that a session [cut prev day, cut today) maps to "today"
    session = (ny - pd.Timedelta(hours=cut_hour_ny)).normalize() + pd.Timedelta(days=1)
    session = session.tz_localize(None)
    g = m1.groupby(session)
    d = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                      "close": g["close"].last(), "volume": g["volume"].sum(), "n": g["close"].size()})
    d = d[d.index.dayofweek < 5]
    d = d[d["n"] > 60]  # drop stub sessions (holidays)
    d.index.name = "date"
    return d


# ----------------------------------------------------------------------------------------------
# Convenience panel
# ----------------------------------------------------------------------------------------------
@lru_cache(maxsize=None)
def futures_panel() -> dict:
    return {s: futures_daily(FUT_CODE[s]) for s in SYMBOLS}


def fut_returns(start=None, end=None) -> pd.DataFrame:
    p = futures_panel()
    r = pd.concat({s: p[s]["ret"] for s in SYMBOLS}, axis=1)
    if start is not None:
        r = r[r.index >= start]
    if end is not None:
        r = r[r.index <= end]
    return r


if __name__ == "__main__":
    for s in SYMBOLS:
        f = futures_daily(FUT_CODE[s])
        print(s, f.index[0].date(), f.index[-1].date(), len(f),
              "ann.vol=%.1f%%" % (f["ret"].std() * np.sqrt(252) * 100),
              "ann.mean=%.1f%%" % (f["ret"].mean() * 252 * 100),
              "carry mean=%.1f%%" % (f["carry"].mean() * 100))
    sp = spot_daily()
    print(sp.dropna(how="all").tail(3))
    for s in ["XTIUSD", "XNGUSD"]:
        m = oanda_minutes(s)
        print(s, "oanda M1", m.index[0], m.index[-1], len(m))
