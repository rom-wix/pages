"""Data layer: 1-minute bars (UTC) -> parquet cache -> resampled bars.

Source: getdata-finance GitHub samples (see scripts/fetch_getdata.sh). Each repo keeps a rolling ~6-month
1-minute window that is rewritten weekly; the union of every snapshot in the git history gives
2026-02-01 -> 2026-09-25. Newer snapshots win where windows overlap.

Other sources (broker MT4/MT5 exports, Dukascopy) can be dropped into data/raw/<SYMBOL>.csv with columns
datetime(UTC),open,high,low,close[,volume] and are picked up by `load_minutes` in preference to getdata.
"""
from __future__ import annotations

import glob
import gzip
import os
import subprocess
from functools import lru_cache

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "sources", "getdata")
CACHE = os.path.join(ROOT, "data")
RAW = os.path.join(CACHE, "raw")
os.makedirs(CACHE, exist_ok=True)

# broker-style symbol -> getdata folder
GETDATA = {
    "EURUSD": "eurusd", "GBPUSD": "gbpusd", "USDJPY": "usdjpy", "AUDUSD": "audusd",
    "USDCAD": "usdcad", "USDCHF": "usdchf", "EURJPY": "eurjpy", "EURGBP": "eurgbp",
    "US500": "spx500", "NAS100": "nas100", "US30": "us30", "US2000": "us2000",
    "GER40": "ger30", "EUSTX50": "eustx50", "JPN225": "jpn225", "AUS200": "aus200",
}
FX = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "EURJPY", "EURGBP"]
INDICES = ["US500", "NAS100", "US30", "US2000", "GER40", "EUSTX50", "JPN225", "AUS200"]
ALL = FX + INDICES

# Local cash-session open (exchange time zone) for indices; FX uses the 17:00 New York roll.
CASH_SESSION = {
    "US500": ("America/New_York", "09:30", "16:00"),
    "NAS100": ("America/New_York", "09:30", "16:00"),
    "US30": ("America/New_York", "09:30", "16:00"),
    "US2000": ("America/New_York", "09:30", "16:00"),
    "GER40": ("Europe/Berlin", "09:00", "17:30"),
    "EUSTX50": ("Europe/Berlin", "09:00", "17:30"),
    "JPN225": ("Asia/Tokyo", "09:00", "15:30"),   # TSE closes 15:30 since Nov 2024
    "AUS200": ("Australia/Sydney", "10:00", "16:00"),
}


def pip_size(sym: str) -> float:
    if sym in INDICES:
        return 1.0
    return 0.01 if sym.endswith("JPY") else 0.0001


def _read_snapshot(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, compression="gzip")
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"time": "datetime", "date": "datetime", "timestamp": "datetime"})
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.set_index("datetime")[["open", "high", "low", "close", "volume"]].astype(float)
    return df


def _snapshot_order(folder: str) -> list[str]:
    """Snapshot files ordered oldest -> newest commit."""
    repo = os.path.join(SRC, folder)
    snaps = {os.path.basename(p).split(".")[0]: p for p in glob.glob(os.path.join(repo, "snap", "*.csv.gz"))}
    log = subprocess.run(["git", "-C", repo, "log", "origin/HEAD", "--format=%h"], capture_output=True, text=True).stdout.split()
    ordered = [snaps[h] for h in reversed(log) if h in snaps]
    return ordered


def build_symbol(sym: str) -> pd.DataFrame:
    raw_csv = os.path.join(RAW, f"{sym}.csv")
    if os.path.exists(raw_csv):
        df = pd.read_csv(raw_csv)
        df.columns = [c.lower() for c in df.columns]
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
        df = df.set_index("datetime").sort_index()
        if "volume" not in df:
            df["volume"] = np.nan
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
    else:
        parts = [_read_snapshot(p) for p in _snapshot_order(GETDATA[sym])]
        if not parts:
            raise FileNotFoundError(f"no snapshots for {sym}; run scripts/fetch_getdata.sh")
        df = pd.concat(parts)
        df = df[~df.index.duplicated(keep="last")].sort_index()   # newest snapshot wins
    # float noise from the vendor (1.184389999999999) -> round to 1/10 pip
    dec = 6 if sym not in INDICES else 2
    if sym.endswith("JPY"):
        dec = 4
    df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].round(dec)
    bad = (df["high"] < df[["open", "close"]].max(axis=1)) | (df["low"] > df[["open", "close"]].min(axis=1))
    df.loc[bad, "high"] = df.loc[bad, ["open", "high", "close"]].max(axis=1)
    df.loc[bad, "low"] = df.loc[bad, ["open", "low", "close"]].min(axis=1)
    return df


def build_all() -> None:
    for sym in ALL:
        df = build_symbol(sym)
        df.to_parquet(os.path.join(CACHE, f"{sym}_1m.parquet"))
        print(f"{sym:8s} {len(df):8d} rows  {df.index[0]} -> {df.index[-1]}")


@lru_cache(maxsize=None)
def load_minutes(sym: str) -> pd.DataFrame:
    path = os.path.join(CACHE, f"{sym}_1m.parquet")
    if not os.path.exists(path):
        build_symbol(sym).to_parquet(path)
    return pd.read_parquet(path)


def resample(df: pd.DataFrame, rule: str, offset: str | None = None) -> pd.DataFrame:
    """OHLC resample of a UTC minute frame. Bars are labelled by their open time (left)."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = df.resample(rule, label="left", closed="left", offset=offset).agg(agg)
    return out.dropna(subset=["open"])


@lru_cache(maxsize=None)
def load_bars(sym: str, rule: str) -> pd.DataFrame:
    """15min/1h bars on UTC clock; 4h bars aligned to the 17:00 New York FX roll (i.e. 21/22 UTC)."""
    m = load_minutes(sym)
    if rule.lower() in ("4h", "240min"):
        ny = m.tz_convert("America/New_York")
        # shift so that 17:00 NY becomes 00:00, resample, shift back -> DST-aware 4h grid
        shifted = ny.copy()
        shifted.index = (ny.index.tz_localize(None) - pd.Timedelta(hours=17))
        b = resample(shifted, "4h")
        b.index = (b.index + pd.Timedelta(hours=17)).tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").tz_convert("UTC")
        return b[b.index.notna()]
    return resample(m, rule)


def trading_day_ny(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """FX trading date: the day that starts at 17:00 New York."""
    ny = idx.tz_convert("America/New_York")
    return (ny + pd.Timedelta(hours=7)).tz_localize(None).normalize()


@lru_cache(maxsize=None)
def daily_bars(sym: str) -> pd.DataFrame:
    m = load_minutes(sym)
    d = trading_day_ny(m.index)
    g = m.groupby(d)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "n": g["close"].size()})
    return out[out["n"] > 120]   # drop Sunday stubs / holiday fragments


if __name__ == "__main__":
    build_all()
