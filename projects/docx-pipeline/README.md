# Docx Pipeline — Automated Template Refinement

## Overview
Claude Code runs unattended, iterating on Word reference templates until output visually matches a precedent document. Uses LibreOffice headless for rendering, ImageMagick/pdftoppm for PNG comparison, and Claude's vision to score each round.

## How It Works
1. Build a test document from markdown using Pandoc + postprocessing scripts
2. Render to PDF (LibreOffice headless) then PNG (pdftoppm, 300dpi)
3. Claude compares candidate PNGs against precedent PNGs
4. Scores against a checklist, logs results, makes ONE fix per round
5. Repeats up to 30 rounds or until all checklist items pass

## Directory Structure
```
docx-pipeline/
├── refinement/
│   ├── precedent/          # gold-standard: target PDF + pre-rendered PNGs
│   ├── candidates/         # round_001/, round_002/, ... with outputs + notes
│   ├── test_source.md      # markdown input (DO NOT MODIFY during runs)
│   ├── checklist.md        # what to evaluate each round
│   └── session_log.md      # running log of changes + scores
├── scripts/
│   ├── build_letter.sh     # pandoc + postprocessor pipeline
│   ├── fix_letter_header.py
│   └── render_and_compare.sh
├── templates/
│   └── reference_letter.docx
└── assets/
    ├── header.jpeg
    ├── footer.jpeg
    └── header_line.png
```

## Setup
1. Install system deps (see root `setup.sh`)
2. Copy from the claude repo:
   - `templates/reference_letter.docx` → `templates/`
   - `scripts/build_letter.sh`, `scripts/fix_letter_header.py` → `scripts/`
   - `assets/*` → `assets/`
3. Place precedent PDF in `refinement/precedent/` and pre-render:
   ```bash
   pdftoppm -png -r 300 refinement/precedent/precedent.pdf refinement/precedent/page
   ```
4. Place test markdown in `refinement/test_source.md`
5. Customize `refinement/checklist.md` for the template type

## Running
```bash
claude --dangerously-skip-permissions --print "$(cat refinement/claude_prompt.md)"
```

## Porting to Other Templates
Swap the precedent, test source, checklist, and template. The process is template-agnostic.
Same pipeline works for court letters, CDCA briefs, demand letters, etc.

## Limitations
- LibreOffice ≠ Word rendering. Final validation still needs Word on Mac/Windows.
- Very subtle spacing (1-2 twips) won't show in 300dpi PNGs.
