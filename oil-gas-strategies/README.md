# Oil & gas: trading the pause after a strong move

Research and backtests behind [`../oil-gas-trading-strategies.html`](../oil-gas-trading-strategies.html)
("Energy Impulse Playbook"). The question was what to do after a strong move in crude oil or natural gas: wait for a
consolidation, mark its support and resistance, then trade either a retracement or a continuation.

## Findings

- **Daily crude oil: trade the continuation.** After a 4–6 day impulse and a tight 4–6 day pause, the first break of the
  box goes with the impulse 53–57% of the time. Continuation trades were profitable after costs on all three oil datasets.
  Retracement trades were inconsistent.
- **Intraday (1h/4h): no edge after costs.** None of 13 approaches stayed positive in both 2005–2014 and 2015–2020.
- **Natural gas: no robust edge.** Every variant lost money in at least one decade.
- **Recommended: System 1, the oil flag breakout (version A+).**

  | Test | Trades | Avg per trade | Profit factor | Max drawdown |
  |---|---|---|---|---|
  | WTI, 1-minute fills, 2005–Apr 2020 | 34 | +0.66R | 2.30 | 5.1R |
  | WTI, daily closes, since 2005 | 68 | +1.45R | 2.60 | |
  | Brent, daily closes, since 2005 | 78 | +0.94R | 1.97 | |
  | WTI holdout, May 2020–Sep 2026 | | +1.64R | | |
  | Brent holdout, May 2020–Sep 2026 | | +0.57R | | |

  It did not work for WTI before 2005.

## System 1 rules (daily bars, WTI or Brent)

| Step | Rule |
|---|---|
| Impulse | Net move over 4, 5 or 6 days ≥ 1.5 × ATR(20). ATR is measured the day before the move. |
| Pause | The next 4, 5 or 6 bars form a box: height ≤ 50% of the impulse, retracement ≤ 61.8%. |
| Filter (A+) | ATR/price above its median of the previous 252 days. |
| Entry | Stop order at the box edge on the impulse side, valid 10 days. Cancel if the other edge breaks first. |
| Stop | Opposite box edge, at least 0.5 × ATR away. |
| Exits | Half at entry ± one impulse length (20-day time stop). Half trails 3.5 × ATR from the close (60-day time stop). |
| Sizing | 0.5–1% risk per trade, one position per market. |

## Reproduce

```bash
pip install pandas numpy numba pyarrow scipy
./fetch_data.sh                    # clones the public sources into ./sources and builds ./data
python3 test_engine.py             # simulator sanity tests
python3 sweep.py                   # stage 1: 13 families x 72 detectors x exits, 1h/4h/1d, WTI & NG
python3 sweep_daily_close.py       # closing-basis calibration + EIA 1986-2026 extension
python3 sweep_refine.py            # daily crude refinement grid
python3 validate.py                # System 1 validation -> results/report_data.json
python3 report_extract.py && python3 check_straddle.py   # page data (same-setup and two-sided comparisons)
python3 build_report.py            # writes ../oil-gas-trading-strategies.html
```

Scan your own data. The input is a daily OHLC CSV, e.g. your broker's back-adjusted CL/BZ history:

```bash
python3 scan.py --csv cl_daily.csv --costs futures --mult 100 --risk 500
```

It prints the backtest summary for versions A and A+, and any open position or pending entry order with its levels.

## Files

- Core
  - `ogslib.py`: engine. Bars, detectors, and a ticket simulator that walks the 1-minute path.
  - `strategies.py`: the 13 families.
  - `system.py`: System 1 rules.
  - `scan.py`: scanner and CSV backtest.
- Data
  - `data_build.py`, `fetch_data.sh`: sources to bars. Sessions run 18:00–17:00 New York.
- Sweeps
  - `sweep.py`, `sweep_daily_close.py`, `sweep_refine.py`, `trend_split.py`, `mtf_test.py`.
- Analysis trail
  - `event_study.py`, `analyze*.py`, `candidates.py`, `check_*.py`, `ng_explore.py`.
- Report
  - `validate.py`, `report_extract.py`, `build_report.py`, `report_template.html`.
- `results/`: sweep outputs (parquet/CSV) and the report data.

## Data and assumptions

The session's network policy blocked Yahoo, FRED, EIA and Stooq, so every series came from public GitHub repositories:

| Source | Coverage | Notes |
|---|---|---|
| [FutureSharks/financial-data](https://github.com/FutureSharks/financial-data) | OANDA WTICO_USD & NATGAS_USD 1-minute bars, 2005 to 15 Apr 2020 | Carry-adjusted CFD prices with no roll gaps (checked against EIA spot). |
| [datasets/oil-prices](https://github.com/datasets/oil-prices), [datasets/natural-gas](https://github.com/datasets/natural-gas) | EIA daily spot closes to 22 Sep 2026 | Close-only. ATR is rescaled ×1.95 to match true-range ATR. |
| [getdata-finance](https://github.com/getdata-finance) | USOIL/UKOIL samples, Mar–Sep 2026 | 1h and 1m bars. |

Costs used:

| | Round trip | Slippage per stop fill |
|---|---|---|
| Futures | 0.015 $/bbl (WTI) · 0.002 $/MMBtu (NG) | 1 tick |
| Retail CFD | 0.04 (WTI) · 0.01 (NG) | 1 tick |

Limitations:
- The realistic 1-minute test covers WTI only, to 2020.
- Post-2020 and Brent results use closing prices.
- EIA spot is not a traded price.

Validate on continuous futures data before trading real money. Research only, not investment advice.
