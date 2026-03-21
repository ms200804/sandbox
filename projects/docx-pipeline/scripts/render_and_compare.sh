#!/bin/bash
# Build document, render to PDF (LibreOffice), convert pages to PNG for visual review.
# Usage: render_and_compare.sh <input.md> <output_dir> [round_number]

set -e
INPUT="$1"
OUTDIR="$2"
ROUND="${3:-1}"

ROUND_DIR="$OUTDIR/round_$(printf '%03d' $ROUND)"
mkdir -p "$ROUND_DIR"

# 1. Build docx
bash scripts/build_letter.sh "$INPUT" "$ROUND_DIR/candidate.docx"

# 2. Convert to PDF via LibreOffice headless
soffice --headless --convert-to pdf --outdir "$ROUND_DIR" "$ROUND_DIR/candidate.docx"

# 3. Convert each PDF page to 300dpi PNG
pdftoppm -png -r 300 "$ROUND_DIR/candidate.pdf" "$ROUND_DIR/page"

echo "Round $ROUND rendered to $ROUND_DIR"
echo "  Pages: $(ls $ROUND_DIR/page-*.png 2>/dev/null | wc -l)"
