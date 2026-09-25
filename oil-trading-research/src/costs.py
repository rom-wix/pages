"""CFD cost assumptions (retail ECN/STP-style broker, e.g. IC Markets / Pepperstone / FP Markets class).

All figures are *fractions of price* per side (one buy OR one sell), so a round trip costs 2x.
They are deliberately a bit worse than the brokers' advertised "typical" spreads, because a bot
trades at the times it has to (rolls, news, Sunday opens), not only at the tightest moments.

  XTIUSD : typical spread ~3c on $75  (~4 bp)  -> half-spread 2 bp + 1 bp slippage       = 3 bp/side
  XBRUSD : typical spread ~4c on $80  (~5 bp)  -> half-spread 2.5 bp + 1 bp slippage     = 3.5 bp/side
  XNGUSD : typical spread ~0.5c on $3 (~15 bp) -> half-spread 7.5 bp + 2.5 bp slippage   = 10 bp/side

Overnight financing ("swap"): the futures-based return series already contains the roll yield
(contango cost / backwardation gain), which is what a broker's swap for a futures-referenced
"spot" CFD passes through.  On top of that, brokers charge a markup; we charge FIN_MARKUP per year
on |notional| for both longs and shorts, accrued per calendar day.

Stress settings (COST_MULT=2, FIN_MARKUP=0.05) are used in the robustness section.
"""

COST_PER_SIDE = {"XTIUSD": 3e-4, "XBRUSD": 3.5e-4, "XNGUSD": 10e-4}
FIN_MARKUP = 0.025  # 2.5% p.a. on notional, both directions

# Intraday strategies (flat before the 17:00 NY daily rollover => no swap).  Breakout/stop entries
# suffer extra slippage, so they get an extra per-side charge.
STOP_SLIPPAGE = {"XTIUSD": 1e-4, "XBRUSD": 1e-4, "XNGUSD": 3e-4}


def per_side(sym: str, mult: float = 1.0) -> float:
    return COST_PER_SIDE[sym] * mult
