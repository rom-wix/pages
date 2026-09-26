"""Retail CFD / ECN cost assumptions (price units).

cost_rt   round-trip spread + commission (ECN raw spread + ~$7/lot for FX; typical CFD spread for indices)
slip      base slippage on every stop fill (stop entries and stop-losses); the engine adds 10% of the
          fill minute's range on top, so a stop filled in a 30-pip news candle pays ~3 pips.
fin       financing per night held (17:00 NY roll), conservative for both sides.
"""
from data import pip_size, INDICES

# round-trip, in pips (FX) or index points
_RT = {"EURUSD": 0.9, "GBPUSD": 1.3, "USDJPY": 1.0, "AUDUSD": 1.0, "USDCAD": 1.5, "USDCHF": 1.5,
       "EURJPY": 1.6, "EURGBP": 1.2,
       "US500": 0.6, "NAS100": 2.0, "US30": 3.0, "US2000": 0.6, "GER40": 1.5, "EUSTX50": 1.5,
       "JPN225": 10.0, "AUS200": 1.5}
_SLIP = {s: (0.1 if s not in INDICES else _RT[s] * 0.25) for s in _RT}


def cost_rt(sym: str, mult: float = 1.0) -> float:
    return _RT[sym] * pip_size(sym) * mult


def slip_base(sym: str, mult: float = 1.0) -> float:
    return _SLIP[sym] * pip_size(sym) * mult


def financing(sym: str, price: float) -> float:
    """per-night cost in price units: ~1.5 bp for index CFDs, ~0.4 bp for FX."""
    return price * (1.5e-4 if sym in INDICES else 0.4e-4)
