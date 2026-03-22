#!/usr/bin/env bash
# build_letter.sh — Convert markdown letter to .docx with Schmidt Law letterhead
#
# Usage:
#   scripts/build_letter.sh input.md output.docx
#
# Cross-platform: works on macOS and Linux (headless Debian)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

INPUT_MD="${1:?Usage: build_letter.sh input.md output.docx}"
OUTPUT_DOCX="${2:?Usage: build_letter.sh input.md output.docx}"
REFERENCE="$REPO_ROOT/templates/reference_letter.docx"
INVOICE_REF="$REPO_ROOT/templates/reference_invoice.docx"

PANDOC_TMP="$(mktemp /tmp/letter_XXXXXX.docx)"
trap 'rm -f "$PANDOC_TMP"' EXIT

echo "→ pandoc: $INPUT_MD"
pandoc "$INPUT_MD" -f markdown -o "$PANDOC_TMP" --reference-doc="$REFERENCE"

echo "→ injecting letterhead"
python3 "$SCRIPT_DIR/fix_letter_header.py" "$PANDOC_TMP" "$INVOICE_REF" "$OUTPUT_DOCX"

BASENAME="$(basename "${OUTPUT_DOCX%.docx}")"
mkdir -p "$HOME/tmp"
cp "$OUTPUT_DOCX" "$HOME/tmp/${BASENAME}.docx"

# Remove macOS quarantine if on macOS
if command -v xattr &>/dev/null; then
    xattr -d com.apple.quarantine "$HOME/tmp/${BASENAME}.docx" 2>/dev/null || true
fi

echo "✓ $OUTPUT_DOCX"
echo "✓ ~/tmp/${BASENAME}.docx"

# Convert to PDF via LibreOffice (headless)
echo "→ converting to PDF via LibreOffice"
if [ -d "/Applications/LibreOffice.app" ]; then
    # macOS
    /Applications/LibreOffice.app/Contents/MacOS/soffice --headless --convert-to pdf --outdir "$HOME/tmp" "$HOME/tmp/${BASENAME}.docx"
else
    # Linux
    soffice --headless --convert-to pdf --outdir "$HOME/tmp" "$HOME/tmp/${BASENAME}.docx"
fi
echo "✓ ~/tmp/${BASENAME}.pdf (LibreOffice preview)"

# Convert to PDF via Word (macOS only, if available)
if [ -d "/Applications/Microsoft Word.app" ]; then
    echo "→ converting to PDF via Word"
    WORD_PDF="$HOME/tmp/${BASENAME}_word.pdf"
    osascript <<APPLESCRIPT
tell application "Microsoft Word"
    open POSIX file "$HOME/tmp/${BASENAME}.docx"
    delay 5
    save as document 1 file name "$WORD_PDF" file format format PDF
    delay 3
    close document 1 saving no
end tell
APPLESCRIPT
    if [ -f "$WORD_PDF" ] && [ "$(stat -f%z "$WORD_PDF" 2>/dev/null || stat -c%s "$WORD_PDF")" -gt 10000 ]; then
        echo "✓ ~/tmp/${BASENAME}_word.pdf (Word render)"
    else
        echo "⚠ Word PDF failed or too small — use LibreOffice preview"
    fi
fi
