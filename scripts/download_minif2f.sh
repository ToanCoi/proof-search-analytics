#!/usr/bin/env bash
# Tải miniF2F (Lean 4, 488 bài: 244 valid + 244 test) bản của DeepSeek-Prover-V1.5 (MIT),
# pin commit cố định. Ghi sha256 vào data/raw/minif2f/MANIFEST.txt.
set -euo pipefail
COMMIT="${MINIF2F_COMMIT:-2c4ba9119eef74d0d611f494261b2c5bae98c69a}"
URL="https://raw.githubusercontent.com/deepseek-ai/DeepSeek-Prover-V1.5/${COMMIT}/datasets/minif2f.jsonl"
OUT=data/raw/minif2f
mkdir -p "$OUT"
curl -sSfL -o "$OUT/minif2f.jsonl" "$URL"
{
  echo "source: $URL"
  echo "commit: $COMMIT"
  echo "sha256: $(sha256sum "$OUT/minif2f.jsonl" | cut -d' ' -f1)"
  echo "rows: $(wc -l < "$OUT/minif2f.jsonl")"
  echo "downloaded: $(date -Iseconds)"
} > "$OUT/MANIFEST.txt"
cat "$OUT/MANIFEST.txt"
