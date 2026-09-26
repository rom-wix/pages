#!/usr/bin/env bash
# Rebuild the longest 1-minute history the getdata-finance GitHub samples allow.
# Each repo keeps a rolling ~6-month window that is rewritten weekly, so the git history
# holds older windows. We extract the CSV from every commit (blob-less clone, blobs fetched on demand)
# and let data_build.py union them.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=${SRC:-sources/getdata}
mkdir -p "$SRC"
FX="eurusd gbpusd usdjpy audusd usdcad usdchf eurjpy eurgbp"
IDX="spx500 nas100 us30 us2000 ger30 eustx50 jpn225 aus200"
fetch() {  # $1 symbol  $2 kind
  local repo="$1-1m-ohlcv-$2-historical-data" dir="$SRC/$1"
  [ -d "$dir/.git" ] || git clone -q --filter=blob:none --no-checkout "https://github.com/getdata-finance/$repo" "$dir"
  git -C "$dir" fetch -q origin
  mkdir -p "$dir/snap"
  local f
  f=$(git -C "$dir" ls-tree --name-only origin/HEAD | grep -i '_1m.csv$' | head -1)
  for c in $(git -C "$dir" log origin/HEAD --format=%h -- "$f"); do
    [ -s "$dir/snap/$c.csv.gz" ] || git -C "$dir" show "$c:$f" | gzip -1 > "$dir/snap/$c.csv.gz"
  done
  echo "$1: $(ls "$dir/snap" | wc -l) snapshots"
}
for s in $FX; do fetch "$s" forex; done
for s in $IDX; do fetch "$s" index; done
