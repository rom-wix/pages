"""US energy-market trading calendar + calendar-effect flags (used by E04 seasonality and E08 ML).

Everything here is *known in advance* (exchange holiday schedules, report schedules and contract expiry
rules are published a year or more ahead), so flags for date t+1 may be used in a signal formed at close t.

Contents
  nymex_holidays()        rule-based NYMEX/CME energy holidays (+ special closures), 1986-2027
  us_trading_days()       weekdays minus holidays
  merge_holiday_rows(df)  fold returns on US-holiday rows into the next US trading day (the pysystemtrade
                          hourly data 2013-2020 contains Globex partial sessions on US holidays for WTI/NG,
                          and ICE Brent trades on most US holidays)
  calendar_flags(idx, sym) day-of-week, turn-of-month, EIA report day, pre/post holiday, expiry windows
  gap_free(ret)           mask of returns that span exactly one US trading day (EIA spot mirror has gaps)

Expiry rules (approximate but standard):
  WTI (CL)   LTD = 3 business days before the 25th calendar day of the month before delivery
             (if the 25th is not a business day: 3 business days before the business day preceding it)
  NG  (NG)   LTD = 3 business days before the first calendar day of the delivery month
  Brent(ICE) LTD = last business day of the 2nd month before delivery (contracts from Mar-2016);
             before: business day preceding the 15th calendar day before the first day of the delivery month
  Options:   WTI LO ~ 3 business days before futures LTD; NG LN/ON = 1 business day before futures LTD
  Index roll window: 5th-9th US business day of each month (S&P GSCI "Goldman roll").
EIA reports:
  WPSR (crude, gasoline, distillate stocks): Wednesday 10:30 ET; Thursday if Mon-Wed of that week had a holiday.
  Natural gas storage: Thursday 10:30 ET since 2002-05-09 (EIA); Wednesday if Thu/Fri is a holiday.
               1994-2002-05: AGA weekly survey, Wednesday afternoon (inside the NYMEX session).
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
from pandas.tseries.holiday import (AbstractHolidayCalendar, GoodFriday, Holiday, USLaborDay, USMemorialDay,
                                    USPresidentsDay, USThanksgivingDay, nearest_workday, sunday_to_monday)
from pandas.tseries.offsets import DateOffset
from dateutil.relativedelta import MO

SPECIAL_CLOSURES = pd.to_datetime([
    "1994-04-27",                              # Nixon funeral
    "2001-09-11", "2001-09-12", "2001-09-13",  # 9/11 (NYMEX reopened Fri 14th)
    "2004-06-11",                              # Reagan funeral
    "2007-01-02",                              # Ford funeral (WTI futures + spot missing)
    "2025-01-09",                              # Carter funeral (WTI spot missing)
])


class NYMEXCalendar(AbstractHolidayCalendar):
    rules = [
        Holiday("New Year", month=1, day=1, observance=sunday_to_monday),
        Holiday("MLK Day", month=1, day=1, offset=DateOffset(weekday=MO(3)), start_date="1998-01-01"),
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


@lru_cache(maxsize=None)
def nymex_holidays(start: str = "1985-01-01", end: str = "2027-12-31") -> pd.DatetimeIndex:
    h = NYMEXCalendar().holidays(start, end)
    h = h.union(SPECIAL_CLOSURES[(SPECIAL_CLOSURES >= start) & (SPECIAL_CLOSURES <= end)])
    return h[h.dayofweek < 5]


@lru_cache(maxsize=None)
def us_trading_days(start: str = "1985-01-01", end: str = "2027-12-31") -> pd.DatetimeIndex:
    wd = pd.bdate_range(start, end)
    return wd.difference(nymex_holidays(start, end))


def merge_holiday_rows(df: pd.DataFrame, ret_col: str = "ret") -> pd.DataFrame:
    """Drop rows dated on US holidays/closures, compounding their return into the next kept row.
    Price-like columns (tri, price, carry...) simply take the next kept row's value."""
    hol = nymex_holidays()
    is_h = df.index.isin(hol)
    if not is_h.any():
        return df.copy()
    grp = (~is_h)[::-1].cumsum()[::-1]  # rows up to and including the next non-holiday row share a group
    grp = pd.Series(grp, index=df.index)
    r = (1 + df[ret_col]).groupby(grp.values).prod() - 1
    out = df[~is_h].copy()
    keep_grp = grp[~is_h].values
    out[ret_col] = r.reindex(keep_grp).values
    return out


def gap_free(ret: pd.Series) -> pd.Series:
    """True where the previous observation is the previous US trading day (single-day return)."""
    td = us_trading_days()
    pos = td.get_indexer(ret.index)
    prev_pos = np.r_[-10, pos[:-1]]
    ok = (pos >= 0) & (prev_pos >= 0) & (pos - prev_pos == 1)
    return pd.Series(ok, index=ret.index)


# ----------------------------------------------------------------------------------------------
# Expiry dates
# ----------------------------------------------------------------------------------------------
def _prev_bd(td: pd.DatetimeIndex, d: pd.Timestamp, n: int = 1, strictly_before: bool = True) -> pd.Timestamp:
    """n-th US business day strictly before d (or on/before if not strictly)."""
    i = td.searchsorted(d, side="left" if strictly_before else "right")
    return td[i - n]


@lru_cache(maxsize=None)
def expiry_dates(product: str, start: int = 1986, end: int = 2027) -> pd.DatetimeIndex:
    """Last trading days of the monthly futures contracts for product in {'CL','NG','BRENT'}."""
    td = us_trading_days()
    out = []
    for y in range(start, end + 1):
        for m in range(1, 13):
            dm = pd.Timestamp(y, m, 1)  # delivery month
            if product == "CL":
                d25 = dm - pd.DateOffset(months=1) + pd.DateOffset(days=24)
                if d25 in td:
                    ltd = _prev_bd(td, d25, 3)
                else:
                    last_before = _prev_bd(td, d25, 1)
                    ltd = _prev_bd(td, last_before, 3)
            elif product == "NG":
                ltd = _prev_bd(td, dm, 3)
            elif product == "BRENT":
                if dm >= pd.Timestamp("2016-03-01"):
                    first_of_m1 = dm - pd.DateOffset(months=1)
                    ltd = _prev_bd(td, first_of_m1, 1)  # last business day of month M-2
                else:
                    d15 = dm - pd.DateOffset(days=15)
                    ltd = _prev_bd(td, d15, 1)
            else:
                raise ValueError(product)
            out.append(ltd)
    return pd.DatetimeIndex(sorted(set(out)))


PRODUCT = {"XTIUSD": "CL", "XBRUSD": "BRENT", "XNGUSD": "NG"}


# ----------------------------------------------------------------------------------------------
# Flags
# ----------------------------------------------------------------------------------------------
def _eia_days(kind: str) -> pd.DatetimeIndex:
    """EIA report dates on the US trading calendar. kind in {'crude','gas'}."""
    td = us_trading_days()
    hol = nymex_holidays()
    weeks = pd.date_range("1985-12-30", "2027-12-27", freq="W-MON")
    out = []
    for mon in weeks:
        days = [mon + pd.Timedelta(days=k) for k in range(5)]  # Mon..Fri
        is_h = [d in hol for d in days]
        if kind == "crude":
            d = days[3] if any(is_h[:3]) else days[2]
            if d in hol:
                d = days[4]
        else:
            if mon < pd.Timestamp("1994-01-01"):
                continue
            if mon < pd.Timestamp("2002-05-06"):
                d = days[2]  # AGA Wednesday
                if d in hol:
                    d = days[3]
            else:
                d = days[2] if (is_h[3] or is_h[4]) else days[3]
                if d in hol:
                    d = days[1]
        if d in td:
            out.append(d)
    return pd.DatetimeIndex(out)


@lru_cache(maxsize=None)
def _eia_cached(kind: str) -> pd.DatetimeIndex:
    return _eia_days(kind)


def calendar_flags(idx: pd.DatetimeIndex, sym: str) -> pd.DataFrame:
    """Flags describing each *return date* t (return from close t-1 to close t) on the US calendar.

    dow        0=Mon .. 4=Fri
    tom        last trading day of month or first 3 trading days of next month
    tdm        trading day of month (1..), tdm_rev (1 = last trading day)
    eia        EIA weekly report day (crude WPSR for oil, storage for gas)
    pre_hol    last trading day before a weekday US holiday/closure
    post_hol   first trading day after a weekday US holiday/closure
    ltd        front-month futures last trading day
    exp_week   the 5 trading days ending on (and including) the front-month LTD
    opt_exp    front-month options expiry day (approx.)
    roll_win   5th-9th business day of the month (index roll window)
    """
    td = us_trading_days()
    hol = nymex_holidays()
    tds = pd.Series(td, index=td)
    ym = td.year * 12 + td.month
    tdm = pd.Series(1, index=td).groupby(ym).cumsum()
    tdm_rev = pd.Series(1, index=td)[::-1].groupby(ym[::-1]).cumsum()[::-1]
    prev_wd = td - pd.offsets.BDay(1)
    next_wd = td + pd.offsets.BDay(1)
    f = pd.DataFrame(index=td)
    f["dow"] = td.dayofweek
    f["tdm"] = tdm.values
    f["tdm_rev"] = tdm_rev.values
    f["tom"] = ((f["tdm"] <= 3) | (f["tdm_rev"] == 1)).astype(int)
    f["pre_hol"] = next_wd.isin(hol).astype(int)
    f["post_hol"] = prev_wd.isin(hol).astype(int)
    f["roll_win"] = ((f["tdm"] >= 5) & (f["tdm"] <= 9)).astype(int)
    kind = "gas" if sym == "XNGUSD" else "crude"
    f["eia"] = td.isin(_eia_cached(kind)).astype(int)
    ltd = expiry_dates(PRODUCT[sym])
    f["ltd"] = td.isin(ltd).astype(int)
    pos = td.get_indexer(ltd[(ltd >= td[0]) & (ltd <= td[-1])])
    ew = np.zeros(len(td), dtype=int)
    oe = np.zeros(len(td), dtype=int)
    k_opt = 1 if sym == "XNGUSD" else 3
    for p in pos[pos >= 0]:
        ew[max(p - 4, 0): p + 1] = 1
        if p - k_opt >= 0:
            oe[p - k_opt] = 1
    f["exp_week"] = ew
    f["opt_exp"] = oe
    # map onto the requested index (dates not in the US calendar, e.g. Brent on US holidays, get NaN)
    return f.reindex(idx)


def next_row_flags(idx: pd.DatetimeIndex, sym: str) -> pd.DataFrame:
    """Flags of the *next* row's date, aligned to row t (what a signal formed at close t can use,
    because the trading calendar is known in advance)."""
    f = calendar_flags(idx, sym)
    nxt = f.shift(-1)
    # last row: next US trading day
    td = us_trading_days()
    last = idx[-1]
    j = td.searchsorted(last, side="right")
    if j < len(td):
        nxt.iloc[-1] = calendar_flags(pd.DatetimeIndex([td[j]]), sym).iloc[0].values
    return nxt


if __name__ == "__main__":
    h = nymex_holidays("2023-01-01", "2023-12-31")
    print("2023 holidays:", [d.date() for d in h])
    for p in ["CL", "NG", "BRENT"]:
        e = expiry_dates(p)
        print(p, [d.date() for d in e[(e >= "2023-01-01") & (e <= "2023-12-31")]])
    f = calendar_flags(pd.bdate_range("2023-11-15", "2023-12-10"), "XTIUSD")
    print(f)
    print("EIA crude 2023-11/12:", [d.date() for d in _eia_cached("crude") if "2023-11-01" <= str(d.date()) <= "2023-12-31"])
    print("EIA gas 2023-11/12:", [d.date() for d in _eia_cached("gas") if "2023-11-01" <= str(d.date()) <= "2023-12-31"])
