# Oil & gas CFD bot research (XTIUSD · XBRUSD · XNGUSD)

Backtests of candidate trading-bot strategies for WTI, Brent and US natural-gas CFDs, with retail CFD
costs (spread + slippage per side, 2.5%/yr financing markup) and roll yield.

The full write-up with charts is `report/oil-gas-bot-research.html` (built by `report/build.py`).

## Layout

| Path | What |
|---|---|
| `scripts/fetch_data.sh` | Clones the public datasets used (pysystemtrade futures, EIA spot via datahub, Oanda 1-min CFD candles) |
| `src/data.py` | Loaders: rolled futures (`futures_daily`), EIA spot (`spot_daily`), Oanda minutes/bars (`oanda_minutes`, `oanda_bars`) |
| `src/costs.py` | CFD cost assumptions |
| `src/backtest.py` | Vectorised daily engine, vol targeting, position buffer, metrics, bootstrap CI, deflated Sharpe |
| `src/signals.py` | Trend (EWMAC, breakout, TSMOM, Donchian), z-score, RSI |
| `src/evaluate.py` | Dataset × signal → positions → backtest → metric tables (IS 1990–2007 / OOS 2008–2024) |
| `experiments/e01_trend.py` | Trend-following families on futures and spot |
| `experiments/e02_carry.py` | Carry / term-structure signals |
| `experiments/e03_mean_reversion.py` | Daily mean reversion (reversal, z-fade, RSI(2), shocks, IBS) |
| `experiments/e04_seasonality.py` | Month-of-year, day-of-week, turn-of-month, EIA-day, holidays |
| `experiments/e05_relative_value.py` | Brent–WTI spread, oil/gas ratio, crack signal regression |
| `experiments/e06_intraday_*.py` | Intraday: opening-range breakout, intraday momentum, EIA reports, sessions, mean reversion |
| `experiments/e07_grid_martingale.py` | Grid / martingale / averaging-down risk simulation |
| `experiments/e08_ml.py` | Walk-forward logistic regression / LightGBM baseline |
| `experiments/e09_crack.py` | Crack-spread (refining margin) signal deep dive |
| `experiments/e10_portfolio.py` | Candidate bot (trend + crack), robustness grid, 2024–26 spot holdout |
| `experiments/e11_extras.py` | Volatility regimes, long/short legs, weekly rebalancing, rolling outcomes |
| `results/` | CSV/JSON outputs of every experiment and per-topic markdown summaries |

## Reproduce

```bash
pip install pandas numpy scipy statsmodels numba lightgbm scikit-learn matplotlib pyarrow
EXT=~/_ext ./scripts/fetch_data.sh          # public GitHub mirrors only
python3 experiments/e01_trend.py            # ... e02 ... e11
python3 experiments/build_report_data.py && python3 report/build.py
```

## Data caveats

* Futures data (pysystemtrade) ends 2024-03-28; WTI main series holds the December contract.
  Near-month WTI (`CRUDE_ICE`) and gas (`GAS-LAST`) series from 2006 are used as checks.
* EIA spot prices run to 2026-09-22 but contain no roll yield; Henry Hub spot is not what the XNGUSD CFD tracks.
* Intraday data: Oanda WTI and natural-gas CFDs only, 2005-01 to 2020-05 (no Brent).
* The sandbox blocked Yahoo, FRED, EIA API, Dukascopy, Stooq and CFTC, so COT, inventory-surprise and
  2024–26 futures tests are left for later.
