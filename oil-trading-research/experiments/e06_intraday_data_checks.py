"""E06-0  Data-quality checks on the Oanda 1-minute CFD mids (XTIUSD = WTICO_USD, XNGUSD = NATGAS_USD).

Per year and instrument:
  * sessions in the trading calendar, share of 1-minute bars present 09:00-14:30 NY
  * lag-1 autocorrelation of 1-minute returns 09:00-14:30 (microstructure noise / stale quotes)
  * median absolute price change per bar (quote granularity)
  * share of sessions with no data 09:30-10:00 and 14:30-15:00 (pre-Globex NYMEX ACCESS hours)
  * pit-open location: mean |1-min return| at 09:00 and 10:00 relative to 11:00-12:00
  * EIA timing: modal minute (offset from 10:30) of the largest 1-minute move 10:15-10:50 on
    Wednesdays (crude) and Thursdays (gas)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from src import intraday as ix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results")


def main():
    rows = []
    for sym in ["XTIUSD", "XNGUSD"]:
        S = ix.session_matrix(sym)
        a, b = ix.col("09:00"), ix.col("14:30")
        pres = ~np.isnan(S.C)
        lr = np.diff(np.log(S.C), axis=1)  # consecutive-minute returns (NaN across gaps)
        years = S.dates.year
        absr = np.abs(lr)
        mid_ref = np.nanmean(absr[:, ix.col("11:00") - 1:ix.col("12:00") - 1], axis=1)
        for y in sorted(set(years)):
            m = (years == y) & S.valid
            x = lr[m, a:b - 1]
            x0, x1 = x[:, 1:].ravel(), x[:, :-1].ravel()
            ok = np.isfinite(x0) & np.isfinite(x1)
            dp = np.abs(np.diff(S.C[m, a:b], axis=1)).ravel()
            dp = dp[np.isfinite(dp) & (dp > 0)]
            wed = m & (S.dates.dayofweek == 2)
            thu = m & (S.dates.dayofweek == 3)

            def spike_offset(mask):
                w = absr[mask, ix.col("10:15") - 1:ix.col("10:50") - 1]
                if len(w) == 0:
                    return np.nan
                am = np.nanargmax(np.nan_to_num(w, nan=-1), axis=1) + ix.col("10:15") - ix.col("10:30")
                mx = np.nanmax(np.nan_to_num(w, nan=0), axis=1)
                am = am[mx > 0.002]
                return float(pd.Series(am).mode().iloc[0]) if len(am) else np.nan

            h2 = pd.Series(np.nanmean(absr[m][:, :], axis=0))
            rows.append({
                "sym": sym, "year": y, "sessions": int(m.sum()),
                "bar_coverage_0900_1430": float(pres[m, a:b].mean()),
                "ac1_1min_0900_1430": float(np.corrcoef(x0[ok], x1[ok])[0, 1]),
                "median_abs_dprice": float(np.median(dp)) if len(dp) else np.nan,
                "median_price": float(np.nanmedian(S.C[m, a:b])),
                "share_no_data_0930_1000": float((~pres[m, ix.col("09:30"):ix.col("10:00")].any(axis=1)).mean()),
                "share_no_data_1430_1500": float((~pres[m, ix.col("14:30"):ix.col("15:00")].any(axis=1)).mean()),
                "abs_r_0900_vs_midday": float(np.nanmean(absr[m, ix.col("09:00") - 1]) / np.nanmean(mid_ref[m])),
                "abs_r_1000_vs_midday": float(np.nanmean(absr[m, ix.col("10:00") - 1]) / np.nanmean(mid_ref[m])),
                "eia_spike_offset_min_wed": spike_offset(wed),
                "eia_spike_offset_min_thu": spike_offset(thu),
            })
    D = pd.DataFrame(rows)
    D.to_csv(os.path.join(OUT, "e06_data_checks.csv"), index=False)
    # monthly EIA offset in 2008 (the 10:35 anomaly)
    mrows = []
    for sym, dow in [("XTIUSD", 2), ("XNGUSD", 3)]:
        S = ix.session_matrix(sym)
        absr = np.abs(np.diff(np.log(S.C), axis=1))
        for mo in range(1, 13):
            m = S.valid & (S.dates.year == 2008) & (S.dates.month == mo) & (S.dates.dayofweek == dow)
            prof = np.nanmean(absr[m, ix.col("10:25") - 1:ix.col("10:40") - 1], axis=0)
            mrows.append({"sym": sym, "month": f"2008-{mo:02d}", "abs_r_1030_bps": prof[5] * 1e4, "abs_r_1035_bps": prof[10] * 1e4})
    pd.DataFrame(mrows).to_csv(os.path.join(OUT, "e06_data_checks_eia2008.csv"), index=False)
    pd.set_option("display.width", 250)
    print(D.round(3).to_string(index=False))
    print(pd.DataFrame(mrows).round(1).to_string(index=False))


if __name__ == "__main__":
    main()
