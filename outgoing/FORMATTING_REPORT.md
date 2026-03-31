# Brief Formatting Report — Hubbard Lien Motion v4

## Files in outgoing/

| File | Description |
|---|---|
| `motion_to_vacate_lien_v4.md` | Updated markdown with attorney info block + judge line in caption |
| `brief_postprocess.py` | Rewritten postprocessor (replaces `scripts/brief_postprocess.py`) |
| `build_brief.sh` | Linux-adapted build script (original uses Mac LibreOffice path) |
| `motion_to_vacate_lien_v4_draft.docx` | Built output docx |
| `motion_to_vacate_lien_v4_draft.pdf` | PDF via LibreOffice headless |

## What Changed

### Caption (motion_to_vacate_lien_v4.md)
- Added attorney info block above caption table (name, firm, address, phone, email, PHV)
- Added `Judge: Hon. Fred Biery` line in right column of caption table
- Added explicit `w:spacing` on OpenXML paragraphs to prevent style inheritance issues
- Kept `§` separator format (correct for WDTx)

### Postprocessor (brief_postprocess.py)
Complete rewrite. Single-pass design. Key changes:

1. **Heading conversion**: All Heading 1/2/3/4 converted to Normal style with paragraph-level formatting:
   - H1 (motion title): Normal + bold + center + double-spaced + 12pt spacing before/after
   - H2 (section headings): Normal + bold + center + double-spaced + no indent
   - H3 (subheadings): Normal + bold + left + double-spaced + no indent
   - Auto-numbering suppressed on all converted headings

2. **Body paragraphs**: Double-spaced (2.0), 0.5" first-line indent (457200 EMU), TNR 12pt

3. **Caption/attorney area**: Single-spaced, no indent (detected as all paragraphs before first heading)

4. **Signature block**: Single-spaced, no indent (detected from "Dated:" or "Respectfully submitted")

5. **Table cells**: Explicitly single-spaced (caption table inherits from Normal otherwise)

6. **Style-level defaults**: Normal and Body Text styles set to double-spaced TNR 12pt (fixes LibreOffice rendering where paragraph-level overrides alone weren't sufficient)

## Verification Results

- **Styles**: All paragraphs are Normal or Body Text (zero Heading styles remain)
- **Body text**: line_spacing=2.0, rule=DOUBLE, first_line_indent=457200, TNR 12pt
- **Section headings**: CENTER, DOUBLE, fli=0, bold
- **Subheadings**: LEFT, DOUBLE, fli=0, bold
- **Caption area**: SINGLE, fli=0
- **Signature block**: SINGLE, fli=0
- **Certificate of service body**: DOUBLE, fli=457200 (resumes body formatting)

## Known Issues

1. **`__` placeholders render as bold** in the PDF (e.g., `(Dkt. __.)` becomes bold because pandoc interprets `__` as bold markers). Fix: replace `__` with actual values or escape as `\_\_` before building.

2. **LibreOffice vs Word**: Final sign-off should be done in Word. LibreOffice rendering can differ on spacing and page breaks.

3. **Cert of service signature** at the very end renders double-spaced (inherits body formatting). Minor — could add detection for the final signature if needed.

## To Use on Mac

Copy files back and replace originals:
```bash
# From Mac:
rsync -avz mws@enlightenment:~/sandbox/outgoing/brief_postprocess.py ~/src/claude/scripts/
rsync -avz mws@enlightenment:~/sandbox/outgoing/motion_to_vacate_lien_v4.md ~/src/claude/client_info/hubbard_goedinghaus_tvpa/

# Then build:
scripts/build_brief.sh client_info/hubbard_goedinghaus_tvpa/motion_to_vacate_lien_v4.md \
  client_info/hubbard_goedinghaus_tvpa/motion_to_vacate_lien_v4_draft.docx
```
