# FX & indices: short-term strategy search (Feb–Sep 2026)

Backtests of short-term strategies (15m–4H charts, 1–10 trades a week, holds of minutes to days) on 8 FX pairs and
8 stock indices, with 1-minute fills and retail costs. The write-up with charts is
[`../fx-indices-strategies.html`](../fx-indices-strategies.html).

## Findings

- **No strategy passed.** 19 families and 249 parameter sets, 231,780 simulated trades. None was profitable after costs
  in both Feb–May and Jun–Sep with a significant t-stat.
- **Luck-level results only.** Of 1,868 instrument-level tests with 30+ trades, 11 reached t ≥ 2. Pure chance would give
  about 43. 358 reached t ≤ −2: costs turn no-edge strategies into steady losers.
- **Why the usual strategies fail in 2026:**
  - Most instruments mean-revert intraday (variance ratio < 1), which hurts breakouts and ORB. USDJPY and EURJPY are the
    exceptions: they trend.
  - Round-trip costs are 0.02–0.17R per trade. Most families earned between −0.09R and +0.03R before costs.
  - Effects flip within months. For example, 1h continuation in European and Asian indices made +0.12R (t 2.4) in
    Feb–May and lost −0.10R (t −2.5) in Jun–Sep.
- **Watch list** (not recommended, re-test on 12+ months):
  - Tokyo pre-fix long on gotobi days, USDJPY and EURJPY, 08:00 → 09:55 JST: +0.13R, t 1.5, 80 trades.
  - End-of-day momentum after a ≥ 0.2 ATR second-last half hour in index cash sessions: +0.08 to +0.29R, 80 trades.
    This is an isolated spike: every broader version of the signal loses.
  - JPY 4h channel breakout: +0.25R, about 50 trades. The profit comes from a few sharp yen rallies.
  - Index dip-buy in an uptrend: +0.08R, t 0.9. Barely better than random long entries.

## Data and caveats

| Item | Detail |
|---|---|
| Source | [getdata-finance](https://github.com/getdata-finance) GitHub samples, 1-minute bars. Each repo keeps a rolling ~6-month window that is rewritten weekly; `scripts/fetch_getdata.sh` extracts every snapshot from the git history and `src/data.py` merges them (newest wins). |
| Window | **2026-02-01 → 2026-09-25 (34 weeks), not the full 12 months.** The session's network allows only GitHub: Yahoo, Dukascopy, Stooq, OANDA and FRED are blocked. |
| Instruments | EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF EURJPY EURGBP · US500 NAS100 US30 US2000 GER40 EUSTX50 JPN225 AUS200 (no UK100, NZDUSD, GBPJPY or gold). |
| Quotes are bids | Around the 17:00 New York rollover the bid sags for about an hour and snaps back at about 22:00 UTC. This showed up as a fake "edge" (buy JPY pairs at 07:00 Tokyo, t 4.1). The engine blocks entries, targets and time exits 16:40–18:10 NY. Stop-losses still trigger there. |
| FX level drift | Cross-rate triangles (e.g. EURJPY vs EURUSD×USDJPY) drift up to ~1.6% between days before late August (vendor stitching). Within a day they hold to about 1 bp, so intraday tests are fine; multi-day FX results carry a small level error. |
| Checks passed | Snapshots agree exactly where they overlap. NFP releases from Feb to Sep appear at the right minute on EURUSD, USDJPY and US500. Minute-by-minute co-movement looks realistic (EURUSD–GBPUSD 0.5–0.8, US500–NAS100 ~0.9). |

## Costs and fills

- Round trip (spread + commission), in pips or points:

  | EURUSD | USDJPY | AUDUSD | EURGBP | GBPUSD | USDCAD | USDCHF | EURJPY |
  |---|---|---|---|---|---|---|---|
  | 0.9 | 1.0 | 1.0 | 1.2 | 1.3 | 1.5 | 1.5 | 1.6 |

  | US500 | US2000 | GER40 | EUSTX50 | AUS200 | NAS100 | US30 | JPN225 |
  |---|---|---|---|---|---|---|---|
  | 0.6 | 0.6 | 1.5 | 1.5 | 1.5 | 2.0 | 3.0 | 10 |

- Stop fills (entries and stop-losses) pay 0.1 pip plus 10% of the fill minute's range. For indices the base is ¼ of the
  spread.
- Financing: 1.5 bp per night for indices and 0.4 bp for FX.
- Fill order: market orders fill at the next minute's open. If a stop and a target fall in the same minute, the stop wins.
  In the entry minute of a stop or limit order, only the stop is checked. A random-entry control loses −0.01R before costs
  from these rules alone.
- One position per strategy and instrument at a time. For OCO pairs, the first leg to fill is kept.

## Layout

| Path | What |
|---|---|
| `scripts/fetch_getdata.sh` | Blob-less clones of the 16 getdata repos; dumps every 1m CSV snapshot (≈ 0.5 GB, git-ignored) |
| `src/data.py` | Snapshot merge → `data/<SYM>_1m.parquet`; resampling (15m, 1h, 4h aligned to 17:00 NY); daily bars on the NY trading day. Drop-in override: `data/raw/<SYM>.csv` |
| `src/engine.py` | Numba order simulator on 1-minute bars (market/stop/limit, SL/TP/time exits, break-even, trailing, rollover blackout) |
| `src/test_engine.py` | Hand-built fill tests |
| `src/strategies.py` | All strategy families (round 1 `FAMILIES`, `ROUND2`, `ROUND3`) with their defaults and grids |
| `src/costs.py`, `src/metrics.py`, `src/runner.py` | Costs, trade metrics (R, t, halves, bootstrap), parallel runner |
| `experiments/e00_data_qa.py` | Coverage, snapshot agreement, cross-rates, activity by hour |
| `experiments/e01_run_all.py` | Round 1: 13 families × grids × universes → `results/trades_all.parquet` (git-ignored, ~90 s), `stage1_summary.csv` |
| `experiments/e02_diagnostics.py` | Variance ratios, big-move follow-through, session hand-offs, by half |
| `experiments/e03`–`e07` | Round-2 design (Feb–May only) and tests; USD fix clock; end-of-day momentum surface |
| `experiments/e08_round3.py` | 4h channel breakout, index dip-buy, random-long benchmark |
| `experiments/e09_report_data.py`, `report/` | Report data and HTML build |

## Reproduce

```bash
pip install pandas numpy numba pyarrow scipy
./scripts/fetch_getdata.sh
cd src && python3 data.py && python3 test_engine.py && cd ..
python3 experiments/e00_data_qa.py
python3 experiments/e01_run_all.py
python3 experiments/e02_diagnostics.py
python3 experiments/e05_round2_test.py
python3 experiments/e08_round3.py
python3 experiments/e09_report_data.py && python3 report/build_report.py
```

## Adding the missing months

1. Either allow `datafeed.dukascopy.com` in the environment's network settings, or export 1-minute bars from MT4/MT5.
2. Save one CSV per symbol as `data/raw/<SYMBOL>.csv`, with columns `datetime,open,high,low,close[,volume]` and
   timestamps in UTC. Use the symbol names above.
3. Delete `data/*_1m.parquet` and rerun from `python3 src/data.py`.

`metrics.SPLIT` (2026-06-01) and every strategy rule stay fixed, so the added months are a clean out-of-sample test.

Research only, not investment advice.
