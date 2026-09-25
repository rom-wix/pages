#!/usr/bin/env bash
# Fetches the public datasets used by this research into ../_ext (outside the repo).
# All sources are public GitHub repositories (the sandbox blocked Yahoo/FRED/EIA/Dukascopy).
set -euo pipefail
EXT="${EXT:-$HOME/_ext}"
mkdir -p "$EXT"
cd "$EXT"

# 1) Back-adjusted futures + term-structure ("multiple prices") from pysystemtrade (1989-2024-03)
if [ ! -d pysystemtrade ]; then
  GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 --filter=blob:none --sparse https://github.com/robcarver17/pysystemtrade
  (cd pysystemtrade && git sparse-checkout set data/futures/adjusted_prices_csv data/futures/multiple_prices_csv data/futures/csvconfig)
fi

# 2) EIA daily spot prices (WTI Cushing, Brent FOB, Henry Hub) via datahub mirrors (1986-today)
[ -d oil-prices ]  || git clone --depth 1 https://github.com/datasets/oil-prices
[ -d natural-gas ] || git clone --depth 1 https://github.com/datasets/natural-gas

# 3) Oanda 1-minute mid-price CFD candles (WTICO_USD, NATGAS_USD, 2005-2020-05)
if [ ! -d financial-data ]; then
  GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 --filter=blob:none --no-checkout https://github.com/FutureSharks/financial-data
  (cd financial-data && git sparse-checkout init --no-cone && \
   git sparse-checkout set --no-cone "pyfinancialdata/data/currencies/oanda/WTICO_USD/*" "pyfinancialdata/data/currencies/oanda/NATGAS_USD/*" && \
   git checkout)
fi
echo "done -> $EXT"
