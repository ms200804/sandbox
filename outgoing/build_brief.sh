#!/usr/bin/env bash
# build_brief.sh — Build a WDTx brief: pandoc → post-process → PDF
#
# Usage:
#   build_brief.sh input.md output.docx [reference.docx]
#
# Adapted for Linux (Debian). LibreOffice via system package.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

INPUT_MD="${1:?Usage: build_brief.sh input.md output.docx [reference.docx]}"
OUTPUT_DOCX="${2:?Usage: build_brief.sh input.md output.docx [reference.docx]}"
REFERENCE_DOC="${3:-$HOME/claude/templates/wdtx_reference.docx}"

# Activate venv if available
if [ -f "$HOME/sandbox/.venv/bin/activate" ]; then
    source "$HOME/sandbox/.venv/bin/activate"
fi

echo "→ pandoc: $INPUT_MD → $OUTPUT_DOCX"
pandoc "$INPUT_MD" \
  -f markdown \
  -o "$OUTPUT_DOCX" \
  --reference-doc="$REFERENCE_DOC"

echo "→ post-processing: heading conversion, body formatting"
python3 "$SCRIPT_DIR/brief_postprocess.py" "$OUTPUT_DOCX"

BASENAME="$(basename "${OUTPUT_DOCX%.docx}")"
OUTDIR="$(dirname "$OUTPUT_DOCX")"

# Convert to PDF via LibreOffice headless
echo "→ converting to PDF via LibreOffice"
libreoffice --headless --convert-to pdf --outdir "$OUTDIR" "$OUTPUT_DOCX" 2>/dev/null
echo "✓ $OUTPUT_DOCX"
echo "✓ ${OUTDIR}/${BASENAME}.pdf"
