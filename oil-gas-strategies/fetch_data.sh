#!/usr/bin/env bash
# Clone the public source datasets into ./sources (about 350 MB; git-ignored), then build bars with data_build.py.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p sources/datasets sources/futuresharks sources/getdata-finance
clone() { [ -d "$2/.git" ] || GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 "$@"; }
clone https://github.com/datasets/oil-prices sources/datasets/oil-prices
clone https://github.com/datasets/natural-gas sources/datasets/natural-gas
if [ ! -d sources/futuresharks/financial-data/.git ]; then
  git clone --depth 1 --filter=blob:none --sparse https://github.com/FutureSharks/financial-data sources/futuresharks/financial-data
  git -C sources/futuresharks/financial-data sparse-checkout set \
    pyfinancialdata/data/currencies/oanda/WTICO_USD pyfinancialdata/data/currencies/oanda/NATGAS_USD
fi
for r in usoil-1h usoil-1m ukoil-1h; do
  clone "https://github.com/getdata-finance/${r}-ohlcv-commodities-historical-data" "sources/getdata-finance/${r}-ohlcv-commodities-historical-data"
done
python3 data_build.py
