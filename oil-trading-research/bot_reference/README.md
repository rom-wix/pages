# Reference signal engine

`signal_engine.py` is the exact logic behind the recommended daily bot (trend + crack tilt,
vol-targeted). `verify_against_backtest.py` proves it reproduces the research positions (max difference 0).
It is a starting point for a bot, not a bot: it has no broker connection, order handling or persistence.

## Daily loop (once per day, ~14:15–14:28 New York time; or weekly on Wednesday)

1. **Prices.** Pull daily closes for XTIUSD, XBRUSD, XNGUSD from the broker (or CL/BZ/NG futures
   settlements). Remove roll gaps: on each roll date subtract the gap between the old and new
   reference contract from all earlier prices, or build returns that skip the roll jump.
   Signals must be computed on roll-adjusted data.
2. **Crack inputs.** Daily RBOB (RB) and ULSD/heating oil (HO) settlements plus WTI. Yesterday's
   settlement is fine: the signal still works when traded 5–10 days late.
3. **Targets.** `target_positions(rets, crack_px, vol_overlay=True)` gives each market's target as a
   fraction of equity. Use the last row.
4. **Orders.** `orders_for_today(...)` converts targets to lot changes using the broker's contract size
   (check it: e.g. 100 or 1,000 barrels per lot for XTIUSD, 10,000 MMBtu for XNGUSD) and lot step.
5. **Checks before sending.** Stale data (last bar older than 1 trading day) → do nothing and alert.
   A target change bigger than 1× equity in one day → hold and alert. Spread wider than 3× normal → wait
   15 minutes and retry. Keep 50%+ free margin.
6. **Log.** Signals, targets, fills, slippage against the model, and daily swap charged; compare the
   realised swap with the futures curve every month.

## Questions for the broker (answer these first)

* How is each "spot" CFD priced (front futures, interpolated between two contracts)? When and how
  are rolls applied: a price adjustment with a cash credit/debit, or a swap?
* Long and short swap for each symbol, and how they are computed (from the futures curve, or a
  benchmark rate plus markup)? The backtest assumes roll yield passes through, plus a 2.5%/yr markup.
* What happened to client positions in April 2020 when WTI futures went negative?
