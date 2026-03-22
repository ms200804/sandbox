# Docx Pipeline — Claude Context

## What This Is
Automated template refinement for Schmidt Law Corporation's legal document pipeline. The goal is to produce Word documents (via Pandoc + Python postprocessing) that match a visual precedent — typically a previously filed court letter or brief.

## How the Pipeline Works
1. **Pandoc** converts markdown → .docx using `templates/reference_letter.docx` as the style reference
2. **fix_letter_header.py** injects letterhead (from `templates/reference_invoice.docx` which stores the header/footer images) and builds continuation headers
3. **LibreOffice headless** renders to PDF for visual comparison

Pandoc maps `{custom-style="StyleName"}` divs in the markdown to Word paragraph styles defined in the reference template's `styles.xml`.

## OOXML Primer (What You Need to Know)

### Spacing units
- **Twips**: 1 inch = 1440 twips. All `w:spacing` and `w:ind` values are in twips
- **EMU**: 1 inch = 914400 EMU. Used for image dimensions (`wp:extent`)
- **Half-points**: `w:sz` values are in half-points. `sz=24` = 12pt, `sz=20` = 10pt
- **Eighth-points**: `w:pBdr` border `w:sz` is in 1/8 point. `sz=16` = 2pt line

### Style inheritance
- `basedOn` determines which style properties are inherited
- `docDefaults` → `Normal` → named style → paragraph-level override → run-level override
- A paragraph with no `w:pStyle` inherits from Normal
- **Our Normal style has `firstLine=720`** — header paragraphs and other non-indented elements MUST override with `firstLine=0`

### Key OOXML ordering
- `w:pBdr` must come BEFORE `w:spacing` in `w:pPr` children
- `sectPr` children must follow: headerReference, footerReference, endnotePr, type, pgSz, pgMar, cols, titlePg

### Page layout
- `w:pgMar w:header` (HDR_DISTANCE) = vertical distance from page top to header start
- `w:pgMar w:top` (TOP_MARGIN) = distance from page top to body text start
- Body position on a page = max(TOP_MARGIN, HDR_DISTANCE + header_content_height)
- First page vs continuation: `w:titlePg` element enables different first-page header

## Current Template State (reference_letter.docx)

### Styles and their spacing (all in twips)
| Style | after | before | line | indent | notes |
|---|---|---|---|---|---|
| Normal | 200 | 0 | 278 | firstLine=720 | Base style; firstLine inherited by all unstyled paragraphs |
| BodyText | 200 | 0 | 278 | (from Normal) | Main body text |
| NoIndent | 0 | 0 | 278 | firstLine=0 | Address block, cc line; has right-tab at 9360 |
| DateLine | 200 | 0 | 278 | — | jc=right |
| LetterRe | 200 | 0 | 278 | left=456, hanging=456 | RE block with hanging indent |
| LetterHeading | 120 | 0 | 278 | firstLine=0 | Section headings; underline |
| Salutation | 200 | 0 | 278 | firstLine=0 | "Dear Judge X:" — basedOn NoIndent |
| SignatureBlock | 200 | 0 | 278 | left=5760, firstLine=0 | jc=left, keepNext=true |
| FootnoteText | 0 | 0 | 240 | left=360, hanging=360 | 10pt TNR |
| FootnoteReference | — | — | — | — | Character style; superscript |

### Page margins
- TOP_MARGIN = 1600 twips (~1.11")
- BOTTOM_MARGIN = 1440 twips (1")
- LEFT/RIGHT = 1440 twips (1")
- HDR_DISTANCE = 720 twips (0.5")

### Continuation header structure
Two-column table (invisible borders):
- Left cell (3000 twips): date + page number, TNR 12pt, flush left
- Right cell (6360 twips): navy blue rule (`#002A55`, 2pt, bottom border)
- Trailing empty paragraph (sz=2) after table

### Letterhead
- First page: header image from reference_invoice.docx (absolutely positioned)
- Footer: firm contact bar on all pages
- Brand navy color: `#002A55` (header line), `#002B56` (footer bar)

## Modifying the Template

Always use Python with zipfile + lxml. Never hand-edit XML:

```python
import zipfile, shutil
from lxml import etree

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
tmpl = 'templates/reference_letter.docx'
tmp = '/tmp/template_patch.docx'

with zipfile.ZipFile(tmpl, 'r') as z:
    styles_xml = z.read('word/styles.xml')

root = etree.fromstring(styles_xml)

# Find and modify a style
for s in root.findall(f'{{{W}}}style'):
    if s.get(f'{{{W}}}styleId') == 'BodyText':
        pPr = s.find(f'{{{W}}}pPr')
        sp = pPr.find(f'{{{W}}}spacing')
        sp.set(f'{{{W}}}after', '200')  # example change

# Write back
with zipfile.ZipFile(tmpl, 'r') as zin:
    with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            if name == 'word/styles.xml':
                zout.writestr(name, etree.tostring(root, xml_declaration=True,
                              encoding='UTF-8', standalone=True))
            else:
                zout.writestr(name, zin.read(name))
shutil.copy2(tmp, tmpl)
```

## Common Pitfalls (Learned the Hard Way)

1. **Normal.firstLine=720** bleeds into headers, footnotes, and any paragraph without explicit `firstLine=0`. Always override.
2. **`w:pBdr` ordering** — must come before `w:spacing` in pPr or Word silently ignores the border.
3. **`keepLines` on SignatureBlock** can create excessive blank space on the preceding page. Removed from style; rely on natural page flow + keepNext instead.
4. **Pandoc `^[...]` footnotes** require FootnoteText and FootnoteReference styles in the template — without them, footnotes render at body text size with no superscript.
5. **`---` in markdown** after content is parsed as YAML by pandoc. Strip trailing notes sections before building.
6. **Header table cells** inherit from Normal unless you set pStyle or explicit ind/spacing. Always set `firstLine=0` and `after=0` explicitly in header paragraphs.
7. **LibreOffice vs Word rendering**: spacing, line breaks, and page breaks can differ. LibreOffice is good enough for iteration; Word is needed for final sign-off.
8. **docDefaults after=200** in our template means any paragraph without explicit after-spacing gets 200 twips. This can cause unexpected gaps.

## Refinement Workflow

See `refinement/claude_prompt.md` for the full automated process. Summary:
- Build → render to PNG → visually compare to precedent → score checklist → fix → repeat
- ONE category of fix per round
- Git stash before each change for easy rollback
- 30-round cap
- Log every round to `refinement/session_log.md`
