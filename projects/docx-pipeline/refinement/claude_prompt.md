# Task: Automated Template Refinement

You are refining a Word template (`templates/reference_letter.docx`) and
build scripts so that the output of `scripts/build_letter.sh` matches the
precedent document in `refinement/precedent/`.

## Process

For each round (start at round 1):

1. **Build and render**: Run `bash scripts/render_and_compare.sh refinement/test_source.md refinement/candidates <round>`
2. **Compare visually**: Read each `page-*.png` from the round output AND the corresponding `precedent/page*.png`. Compare them side by side.
3. **Score against checklist**: Go through `refinement/checklist.md` item by item. For each item, mark pass/fail and note the specific discrepancy.
4. **Log results**: Write a summary to `refinement/candidates/round_NNN/notes.md` with: what matched, what didn't, planned fix.
5. **Fix**: Modify the template (styles.xml via Python/lxml) or build scripts. Make ONE category of fix per round (e.g., "fix all spacing" or "fix header layout") — not everything at once.
6. **Repeat** until all checklist items pass or you've done 30 rounds.

## Rules

- NEVER modify the test source markdown — only the template and scripts.
- After each round, append a one-line summary to `refinement/session_log.md`:
  `Round NNN: [score X/Y] [what changed] [what's still wrong]`
- If a fix makes something WORSE, revert it before the next round.
  Use `git stash` or copy the template before each change.
- When comparing images, focus on: vertical spacing between elements,
  horizontal alignment, font sizes, line weights, colors.
- The precedent is the VISUAL target. Match its appearance even if the
  underlying OOXML structure is different.
- After 30 rounds or full checklist pass, write a final summary to
  `refinement/session_log.md` and stop.

## Available tools

- `scripts/build_letter.sh` — pandoc + fix_letter_header.py pipeline
- `scripts/render_and_compare.sh` — build + PDF + PNG
- Python with lxml — for modifying styles.xml in the template
- Read tool — for viewing PNG renderings of each page
- ImageMagick `compare` — for pixel-diff between candidate and precedent PNGs

## Files you may modify

- `templates/reference_letter.docx` (via Python zipfile/lxml)
- `scripts/fix_letter_header.py`
- `scripts/build_letter.sh` (if needed)

## Files you may NOT modify

- `refinement/test_source.md`
- `refinement/precedent/*`
- `assets/*`
