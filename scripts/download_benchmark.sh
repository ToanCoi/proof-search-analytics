#!/usr/bin/env bash
# Tải LeanDojo Benchmark 4 từ Zenodo vào data/raw/, ghi sha256 vào data/raw/MANIFEST.txt.
#   bash scripts/download_benchmark.sh                 # record mặc định
#   LB4_RECORD=<id> bash scripts/download_benchmark.sh # record/phiên bản khác
#   LB4_URL=<link file> bash scripts/download_benchmark.sh
# Kiểm tra phiên bản mới nhất trên https://zenodo.org (tìm "LeanDojo Benchmark 4") và ghi
# đúng phiên bản vào DV trong Makefile + data_version trong configs/.
set -euo pipefail
RECORD="${LB4_RECORD:-10114185}"
OUT=data/raw
mkdir -p "$OUT"

if [ -z "${LB4_URL:-}" ]; then
  LB4_URL=$(curl -sSfL "https://zenodo.org/api/records/${RECORD}" | python -c '
import json, sys
files = json.load(sys.stdin)["files"]
f = max(files, key=lambda f: f["size"])
print(f["links"]["self"])')
fi
NAME=$(basename "${LB4_URL%%\?*}")
[ "$NAME" = "content" ] && NAME=leandojo_benchmark_4.tar.gz

echo "Downloading $LB4_URL -> $OUT/$NAME"
wget -q --show-progress -O "$OUT/$NAME" "$LB4_URL"
SHA=$(sha256sum "$OUT/$NAME" | cut -d' ' -f1)
tar xzf "$OUT/$NAME" -C "$OUT"
{
  echo "source: zenodo record ${RECORD}"
  echo "url: ${LB4_URL}"
  echo "file: ${NAME}"
  echo "sha256: ${SHA}"
  echo "downloaded: $(date -Iseconds)"
} > "$OUT/MANIFEST.txt"
cat "$OUT/MANIFEST.txt"
ls "$OUT"
echo "Kiểm tra: ls $OUT/leandojo_benchmark_4/random  (train.json val.json test.json)"
