# Brief Merge Iteration Task — Hubbard Lien Motion v5

## Objective
Get the merged brief (caption + TOC + TOA + body) to look identical to the filed precedent (Dkt. 327). The output must be filing-ready with NO manual Word edits needed.

## Current State
The pipeline builds a brief and a TOC/TOA separately, then merges them. Current issues:
1. **Footers wrong**: TOC/TOA pages should have NO footer. Body pages should have "PLAINTIFFS' MOTION TO VACATE CHARGING LIEN" + "PAGE X" footer with a top border line. Currently no footers appear on any page after merge.
2. **TOA case wrapping**: Long case citations (Schneider, Sofidiya) wrap to a second line and the dot leader + page number floats on the wrapped line instead of connecting properly.
3. **Section breaks / page numbering**: Caption = page i (or no number), TOC = page ii, TOA = page iii, Body starts at page 1. Currently the section break may not be working correctly.
4. **PRELIMINARY STATEMENT must start on its own page** (first page of the body section).

## Files (in claude repo at ~/claude/)

**Scripts to modify:**
- `scripts/merge_brief.py` — merges brief + TOC/TOA, handles section breaks + footers
- `scripts/build_toc_toa.py` — generates standalone TOC/TOA docx
- `scripts/brief_postprocess.py` — post-processes the brief docx after pandoc

**Source:**
- `client_info/hubbard_goedinghaus_tvpa/motion_to_vacate_lien_v5.md` — brief markdown

**Reference (ground truth — do NOT modify):**
- `client_info/hubbard_goedinghaus_tvpa/docket/dkt_327_corrected_opp_to_intervention_2024-05-08.pdf` — filed WDTx brief with correct TOC, TOA, footer, page numbering
- `tone_references/MTC Opp.docx` — known-good WDTx brief (docx, has footer with title + page)

**Build commands:**
```bash
# Build the brief
bash scripts/build_brief.sh \
  client_info/hubbard_goedinghaus_tvpa/motion_to_vacate_lien_v5.md \
  client_info/hubbard_goedinghaus_tvpa/motion_to_vacate_lien_v5_draft.docx

# Build the TOC/TOA
python3 scripts/build_toc_toa.py ~/tmp/toc_toa_insert.docx

# Merge them
python3 scripts/merge_brief.py \
  ~/tmp/motion_to_vacate_lien_v5_draft.docx \
  ~/tmp/toc_toa_insert.docx \
  ~/tmp/lien_v5_merged.docx
```

## Process

### Step 1: Inspect the reference
Read Dkt. 327 PDF. Note:
- Page 1: caption + title (no page number, or "i")
- Page 2: TABLE OF CONTENTS (page "i" or "ii")
- Page 3: TABLE OF AUTHORITIES (page "ii" or "iii")
- Page 4+: Body starting at page 1
- Footer on body pages: document title left-aligned + "PAGE X" right-aligned, separated by a top border line
- Footer on TOC/TOA pages: check if present or suppressed

### Step 2: Fix merge_brief.py
The key issue is per-section footer handling:
- **Section 0** (caption + TOC/TOA): needs its OWN footer definition that is either blank or has roman numeral page numbers. Must NOT inherit from the body section's footer. In OOXML this means the section's sectPr must have its own footerReference pointing to a separate footer part.
- **Section 1** (body): keeps the existing footer (motion title + PAGE field). Page numbering restarts at 1.
- The section break between them must be type="nextPage" to force PRELIMINARY STATEMENT to a new page.

### Step 3: Fix TOA case wrapping
Long citations that wrap should NOT have dot leaders on the wrapped continuation line. Only the last line (with the page numbers) should have dots. Currently Schneider and Sofidiya wrap badly.

Options:
- Reduce font size slightly for TOA entries
- Use a hanging indent so continuation lines indent further
- Or accept wrapping but ensure the tab+dots only fire on the line with the page number (this should happen naturally with tab stops — debug why it's not)

### Step 4: Verify by reading the output
After each rebuild:
1. Generate PDF: `libreoffice --headless --convert-to pdf --outdir ~/tmp ~/tmp/lien_v5_merged.docx`
2. Read the PDF (you can read PDFs as images)
3. Compare page-by-page against Dkt. 327
4. Check: footers present/absent on correct pages, page numbers correct, TOC/TOA formatting, body starts at page 1, PRELIMINARY STATEMENT on its own page

### Step 5: Loop
Keep iterating until:
- Caption page: no footer (or roman numeral)
- TOC page: no footer (or roman numeral)
- TOA page: no footer (or roman numeral)
- Body pages: footer with motion title + PAGE X, starting at 1
- PRELIMINARY STATEMENT starts on its own page
- TOA entries don't have broken wrapping
- All spacing matches Dkt. 327

## Key Constraints
- Do NOT modify the brief markdown content (only formatting scripts)
- Do NOT modify reference/precedent files
- LibreOffice is at: `/usr/bin/libreoffice` (on Debian) or check `which libreoffice`
- Word is NOT available on Enlightenment — use LibreOffice for PDF generation
- Note that LibreOffice may not render table cell borders (the title row lines) — that's a known LibreOffice limitation, not a bug. Check those in Word on Mac later.
- Git push when done so Mac can pull the results

## Success Criteria
When you read the output PDF, it should look like a real filed WDTx brief: caption page → TOC → TOA → body starting at page 1 with proper footers. No manual Word edits needed.
