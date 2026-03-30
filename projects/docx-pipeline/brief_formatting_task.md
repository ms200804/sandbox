# Brief Formatting Task — Hubbard Lien Motion v4

## Objective
Make `motion_to_vacate_lien_v4_draft.docx` match the formatting of Matt's filed WDTx briefs. The output must be pixel-perfect before filing.

## The Problem
The current pipeline (pandoc + `brief_postprocess.py`) produces a docx with Heading 1/2/3 styles. Matt's actual filed WDTx briefs use **all Normal style** with paragraph-level formatting. This mismatch is the root cause of persistent spacing and formatting issues.

## Reference Files (ground truth — do NOT modify these)

### Known-good WDTx briefs (inspect for target formatting values):
- `/Users/mws/src/claude/tone_references/MTC Opp.docx` — motion to compel opposition (draft but formatting is representative)
- `/Users/mws/src/claude/tone_references/Opp to Miller Motion to Compel v2 (1).docx` — discovery opposition
- `/Users/mws/src/claude/tone_references/Lodge MTD Opp.docx` — MTD opposition
- `/Users/mws/src/claude/tone_references/Jnt Advisory to the Ct Re Crow's Supp Mtn - Pls Portion.docx` — joint advisory

### Filed brief PDF (visual reference for caption + layout):
- `/Users/mws/src/claude/client_info/hubbard_goedinghaus_tvpa/docket/dkt_327_corrected_opp_to_intervention_2024-05-08.pdf`
  - Has attorney info block at top
  - "Judge: Hon. Fred Biery" and "Date Action Filed: May 8, 2023 (transferred)"
  - Uses `)` separators in caption (though our brief uses `§` which is also standard WDTx — keep `§`)

### Source files to modify:
- `/Users/mws/src/claude/scripts/brief_postprocess.py` — the postprocessor (primary target)
- `/Users/mws/src/claude/scripts/build_brief.sh` — the build script
- `/Users/mws/src/claude/client_info/hubbard_goedinghaus_tvpa/motion_to_vacate_lien_v4.md` — the brief markdown (caption OpenXML block may need updates)
- `/Users/mws/src/claude/templates/wdtx_reference.docx` — the pandoc reference template

### Current output (what needs fixing):
- `/Users/mws/src/claude/client_info/hubbard_goedinghaus_tvpa/motion_to_vacate_lien_v4_draft.docx`

## Process

### Step 1: Establish target values
Inspect ALL known-good WDTx docx files with python-docx. For each paragraph, extract:
- `style.name`
- `paragraph_format.line_spacing_rule` and `line_spacing`
- `paragraph_format.space_before` and `space_after`
- `paragraph_format.first_line_indent`
- `paragraph_format.alignment`
- Font name, size, bold, italic from runs
- Any `w:jc`, `w:spacing`, `w:ind` XML attributes

Build a formatting spec from the consensus across files. Key questions:
- What style are body paragraphs? (Expected: Normal)
- What style are section headings? (Expected: Normal with center alignment + bold)
- What style are subheadings? (Expected: Normal with bold, left-aligned)
- What is the line spacing? (Expected: DOUBLE, line=2.0)
- What is the first-line indent? (Expected: 457200 EMU = 0.5")
- What is space_before/after on body vs heading paragraphs?
- What font/size? (Expected: Times New Roman 12pt)

### Step 2: Inspect current output
Run the same inspection on `motion_to_vacate_lien_v4_draft.docx`. Document every difference from the target values.

### Step 3: Fix the postprocessor
Modify `brief_postprocess.py` to:

1. **Convert ALL Heading 1/2/3 paragraphs to Normal style** with paragraph-level formatting:
   - Heading 1 (motion title): Normal + bold + ALL CAPS + center aligned + appropriate spacing
   - Heading 2 (section headings like PRELIMINARY STATEMENT): Normal + bold + ALL CAPS + center aligned + spacing before/after
   - Heading 3 (subheadings like A. The Lien Is Blocking...): Normal + bold + left aligned + spacing before/after
   - Remove any auto-numbering artifacts

2. **Ensure all body paragraphs** have:
   - Normal style
   - DOUBLE line spacing (rule=DOUBLE, line=2.0)
   - 0.5" first-line indent (457200 EMU)
   - space_before=None, space_after=None (inherit from style, not explicit 0)
   - Times New Roman 12pt

3. **Caption area** (the raw OpenXML block): should remain single-spaced, centered, no indent. The current center-detection logic should continue to work.

4. **Signature block**: single-spaced, no indent, left-aligned.

5. **Certificate of service**: body text should be double-spaced (resume after signature block).

### Step 4: Fix the caption
The current caption in `motion_to_vacate_lien_v4.md` is missing:
- Attorney info block above the caption table (Matt's name, firm, address, phone, email, PHV notation)
- Judge line in the right column ("Judge: Hon. Fred Biery")

Compare against Dkt. 327 page 1 and update the raw OpenXML block. Keep the `§` separator format (that's correct for WDTx).

### Step 5: Rebuild and verify
```bash
scripts/build_brief.sh \
  client_info/hubbard_goedinghaus_tvpa/motion_to_vacate_lien_v4.md \
  client_info/hubbard_goedinghaus_tvpa/motion_to_vacate_lien_v4_draft.docx
```

Then re-inspect the output docx. Compare paragraph-by-paragraph against the target values from Step 1. If any paragraph doesn't match, fix and rebuild. Loop until clean.

### Step 6: PDF comparison
Generate PDF via LibreOffice:
```bash
/Applications/LibreOffice.app/Contents/MacOS/soffice --headless --convert-to pdf --outdir ~/tmp ~/tmp/motion_to_vacate_lien_v4_draft.docx
```

Use `pdftotext -layout` on both the output PDF and Dkt. 327 PDF. Compare:
- Line spacing (should see blank lines between body text lines = double-spaced)
- Heading spacing (appropriate gaps before/after section headings)
- First-line indentation (body paragraphs indented, headings not)
- Caption layout
- Signature block layout

## Key Constraints
- Do NOT modify the tone_references files or docket files — those are ground truth
- Do NOT change the substantive content of the brief markdown (only the OpenXML caption block and formatting)
- The pipeline must remain generic enough for future WDTx briefs, not hardcoded to this one motion
- LibreOffice is available for PDF generation: `/Applications/LibreOffice.app/Contents/MacOS/soffice`
- Word may also be available on this Mac if needed for testing
- The footnote `[^mag]` in the markdown must render correctly in the output

## Success Criteria
When you inspect the output docx with python-docx, every body paragraph should have the same style/spacing/indent values as the known-good WDTx briefs. When you compare pdftotext output against Dkt. 327, the layout (spacing, indentation, heading treatment) should be visually indistinguishable.
