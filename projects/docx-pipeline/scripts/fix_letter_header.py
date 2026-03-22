#!/usr/bin/env python3
"""
fix_letter_header.py — Inject Schmidt Law letterhead into pandoc-generated docx.

The invoice template stores the full letterhead in header2.xml (default header,
shown on pages 2+). For a letter we want it on page 1 only, with a plain
continuation header (date + page number) on pages 2+.

Usage:
    python3 fix_letter_header.py pandoc_output.docx reference_invoice.docx output.docx
"""

import sys
import os
import re
import shutil
import zipfile
from lxml import etree

W   = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R   = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
IMG_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image'
HDR_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/header'
FTR_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer'


def _extract_date_from_doc(doc_root):
    """Try to find the date line in the document (looks for a date pattern).
    Handles both a standalone date paragraph and a date inlined after a tab
    at the end of the address block (e.g. 'Brooklyn, NY\tMarch 24, 2026').
    """
    for p in doc_root.iter(f'{{{W}}}p'):
        text = ''.join(t.text or '' for t in p.iter(f'{{{W}}}t'))
        t = text.strip()
        # Standalone date paragraph
        if re.match(r'^[A-Z][a-z]+ \d{1,2}, \d{4}$', t):
            return t
        # Date after a tab (right-aligned inline in address block)
        m = re.search(r'\t([A-Z][a-z]+ \d{1,2}, \d{4})$', t)
        if m:
            return m.group(1)
    return None


def _build_continuation_header(date_text):
    """Build continuation header: two-column table matching Mannechez precedent.

    Left cell: date + page number (flush left, TNR 10pt).
    Right cell: navy blue horizontal rule (paragraph bottom border, #002a55).
    Table has invisible borders; blue rule sits at bottom of right cell.
    """
    RPR = ('<w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/>'
           '<w:sz w:val="24"/></w:rPr>')
    xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:tbl>
    <w:tblPr>
      <w:tblW w:w="9360" w:type="dxa"/>
      <w:tblBorders>
        <w:top w:val="none" w:sz="0" w:space="0" w:color="auto"/>
        <w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>
        <w:bottom w:val="none" w:sz="0" w:space="0" w:color="auto"/>
        <w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>
        <w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/>
        <w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>
      </w:tblBorders>
      <w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0"
                 w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/>
    </w:tblPr>
    <w:tblGrid>
      <w:gridCol w:w="3000"/>
      <w:gridCol w:w="6360"/>
    </w:tblGrid>
    <w:tr>
      <w:tc>
        <w:tcPr><w:tcW w:w="3000" w:type="dxa"/></w:tcPr>
        <w:p>
          <w:pPr>
            <w:spacing w:after="0" w:line="240" w:lineRule="auto"/>
            <w:ind w:left="0" w:firstLine="0"/>
            {RPR}
          </w:pPr>
          <w:r>{RPR}<w:t>{date_text or ""}</w:t></w:r>
        </w:p>
        <w:p>
          <w:pPr>
            <w:spacing w:after="0" w:line="240" w:lineRule="auto"/>
            <w:ind w:left="0" w:firstLine="0"/>
            {RPR}
          </w:pPr>
          <w:r>{RPR}<w:t xml:space="preserve">Page </w:t></w:r>
          <w:r>{RPR}<w:fldChar w:fldCharType="begin"/></w:r>
          <w:r>{RPR}<w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
          <w:r>{RPR}<w:fldChar w:fldCharType="separate"/></w:r>
          <w:r>{RPR}<w:t>2</w:t></w:r>
          <w:r>{RPR}<w:fldChar w:fldCharType="end"/></w:r>
        </w:p>
      </w:tc>
      <w:tc>
        <w:tcPr>
          <w:tcW w:w="6360" w:type="dxa"/>
          <w:vAlign w:val="bottom"/>
        </w:tcPr>
        <w:p>
          <w:pPr>
            <w:pBdr>
              <w:bottom w:val="single" w:sz="16" w:space="1" w:color="002A55"/>
            </w:pBdr>
            <w:spacing w:after="0" w:line="240" w:lineRule="auto"/>
          </w:pPr>
        </w:p>
      </w:tc>
    </w:tr>
  </w:tbl>
  <w:p>
    <w:pPr>
      <w:spacing w:after="0" w:line="240" w:lineRule="auto"/>
      <w:rPr><w:sz w:val="2"/></w:rPr>
    </w:pPr>
  </w:p>
</w:hdr>'''
    return xml.encode('utf-8')


def fix(pandoc_path, invoice_path, out_path):
    shutil.copy2(pandoc_path, out_path)

    with zipfile.ZipFile(invoice_path, 'r') as inv:
        inv_names = inv.namelist()

        # --- Header: use invoice header2.xml (full letterhead) ---
        hdr_xml   = inv.read('word/header2.xml')
        hdr_rels  = inv.read('word/_rels/header2.xml.rels')

        # Parse header rels to find the image file
        rels_root = etree.fromstring(hdr_rels)
        hdr_images = {}  # rId -> 'media/imageX.jpeg'
        for rel in rels_root.findall(f'{{{REL}}}Relationship'):
            if 'image' in rel.get('Type', ''):
                hdr_images[rel.get('Id')] = rel.get('Target')

        # --- Footer: use invoice footer1.xml ---
        ftr_xml  = inv.read('word/footer1.xml')
        ftr_rels = inv.read('word/_rels/footer1.xml.rels') if 'word/_rels/footer1.xml.rels' in inv_names else None
        ftr_images = {}
        if ftr_rels:
            fr = etree.fromstring(ftr_rels)
            for rel in fr.findall(f'{{{REL}}}Relationship'):
                if 'image' in rel.get('Type', ''):
                    ftr_images[rel.get('Id')] = rel.get('Target')

        # Read image bytes from invoice zip
        image_bytes = {}
        for target in list(hdr_images.values()) + list(ftr_images.values()):
            path = f'word/{target}'
            if path in inv_names:
                image_bytes[target] = inv.read(path)
                print(f"  image: {path} ({len(image_bytes[target])} bytes)")

    # Inject everything into a rebuilt output zip
    replacements = {}

    # Write image files with unique names (prefix lh_)
    target_remap = {}  # old target -> new target
    for old_target, data in image_bytes.items():
        ext = os.path.splitext(old_target)[1]
        new_name = f'media/lh_{os.path.basename(old_target)}'
        replacements[f'word/{new_name}'] = data
        target_remap[old_target] = new_name

    # --- First page header (letterhead) → header1.xml ---
    # Pad the first-page header to push body text below the letterhead image.
    # Image is page-anchored at ~0.054" from top, 1.62" tall → ends at ~1.67".
    # HDR_DISTANCE=0 so header starts at page top. Need padding to push body to ~1.7".
    # Required header content height: 1.7" × 1440 = 2448 twips.
    # One paragraph: line height (~240 twips) + space_after fills the rest.
    hdr_root = etree.fromstring(hdr_xml)
    pad_p = etree.SubElement(hdr_root, f'{{{W}}}p')
    pad_pPr = etree.SubElement(pad_p, f'{{{W}}}pPr')
    pad_sp = etree.SubElement(pad_pPr, f'{{{W}}}spacing')
    pad_sp.set(f'{{{W}}}before', '0')
    pad_sp.set(f'{{{W}}}after', '1488')  # (2448 - HDR_DISTANCE=720) - 240 (line height) = 1488
    pad_sp.set(f'{{{W}}}line', '240')
    pad_sp.set(f'{{{W}}}lineRule', 'auto')
    pad_rPr = etree.SubElement(pad_pPr, f'{{{W}}}rPr')
    pad_sz = etree.SubElement(pad_rPr, f'{{{W}}}sz')
    pad_sz.set(f'{{{W}}}val', '2')  # 1pt font — minimal line height
    hdr_xml = etree.tostring(hdr_root, xml_declaration=True, encoding='UTF-8', standalone=True)

    hdr_rels_xml = _build_rels(hdr_images, target_remap)
    replacements['word/header1.xml']       = hdr_xml
    replacements['word/_rels/header1.xml.rels'] = hdr_rels_xml.encode()

    # --- Continuation header (date + page) → header2.xml ---
    with zipfile.ZipFile(out_path, 'r') as zin:
        doc_xml = zin.read('word/document.xml')
        doc_rels_xml = zin.read('word/_rels/document.xml.rels')

    doc_root  = etree.fromstring(doc_xml)
    date_text = _extract_date_from_doc(doc_root)
    if date_text:
        print(f"  continuation header date: {date_text}")
    replacements['word/header2.xml'] = _build_continuation_header(date_text)
    # header2 has no images, so empty rels
    replacements['word/_rels/header2.xml.rels'] = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        f'<Relationships xmlns="{REL}"/>'
    ).encode()

    # Build new footer rels
    if ftr_images:
        ftr_rels_xml = _build_rels(ftr_images, target_remap)
        replacements['word/footer1.xml']            = ftr_xml
        replacements['word/_rels/footer1.xml.rels'] = ftr_rels_xml.encode()

    # Patch document.xml: wire headers/footer into sectPr with titlePg
    rels_root = etree.fromstring(doc_rels_xml)

    # Remove any existing header/footer rels pandoc added, then add ours
    for rel in rels_root.findall(f'{{{REL}}}Relationship'):
        if rel.get('Type') in (HDR_REL, FTR_REL):
            rels_root.remove(rel)

    used_ids = {r.get('Id') for r in rels_root.findall(f'{{{REL}}}Relationship')}
    first_hdr_rId = _next_rId(used_ids); used_ids.add(first_hdr_rId)   # header1 (letterhead, first page)
    default_hdr_rId = _next_rId(used_ids); used_ids.add(default_hdr_rId)  # header2 (continuation)
    ftr_rId = _next_rId(used_ids); used_ids.add(ftr_rId)

    rels_root.append(_rel_el(first_hdr_rId, HDR_REL, 'header1.xml'))
    rels_root.append(_rel_el(default_hdr_rId, HDR_REL, 'header2.xml'))
    if ftr_images:
        rels_root.append(_rel_el(ftr_rId, FTR_REL, 'footer1.xml'))

    # Margins: letterhead image is absolutely positioned (page-relative) at ~0.054" from top.
    # Page 1: HDR_DISTANCE=0 for letterhead; pad_after=1488 pushes body to ~1.7" (2448 twips).
    # Cont. pages: HDR_DISTANCE=720 (0.5") — header starts close to top.
    #   Cont. header = date line (240 twips) + after=0 + page line (240 twips) + after=200 = ~680 twips
    #   Header content ends at ~720+680=1400 twips. TOP_MARGIN=1600 → body at 1600 (gap ≈ 200 twips).
    TWIP = 1440
    TOP_MARGIN    = 1600               # ~1.11" — body sits just below continuation header
    BOTTOM_MARGIN = int(1.0  * TWIP)   # 1440 twips
    HDR_DISTANCE  = 720                # 0.5" — continuation header near top of page

    sectPr = doc_root.find(f'.//{{{W}}}sectPr')
    if sectPr is not None:
        # Remove existing header/footer references and titlePg
        for tag in [f'{{{W}}}headerReference', f'{{{W}}}footerReference', f'{{{W}}}titlePg']:
            for el in sectPr.findall(tag):
                sectPr.remove(el)

        # OOXML requires sectPr children in a specific order:
        # headerReference, footerReference, endnotePr, type, pgSz, pgMar, ...
        insert_pos = 0

        # First page header (letterhead)
        h_ref = etree.Element(f'{{{W}}}headerReference')
        h_ref.set(f'{{{W}}}type', 'first')
        h_ref.set(f'{{{R}}}id', first_hdr_rId)
        sectPr.insert(insert_pos, h_ref)
        insert_pos += 1

        # Default header (continuation: date + page number)
        h_ref2 = etree.Element(f'{{{W}}}headerReference')
        h_ref2.set(f'{{{W}}}type', 'default')
        h_ref2.set(f'{{{R}}}id', default_hdr_rId)
        sectPr.insert(insert_pos, h_ref2)
        insert_pos += 1

        if ftr_images:
            f_ref = etree.Element(f'{{{W}}}footerReference')
            f_ref.set(f'{{{W}}}type', 'default')
            f_ref.set(f'{{{R}}}id', ftr_rId)
            sectPr.insert(insert_pos, f_ref)
            insert_pos += 1

            # Also set footer for first page
            f_ref_first = etree.Element(f'{{{W}}}footerReference')
            f_ref_first.set(f'{{{W}}}type', 'first')
            f_ref_first.set(f'{{{R}}}id', ftr_rId)
            sectPr.insert(insert_pos, f_ref_first)
            insert_pos += 1

        # Enable "different first page" so letterhead only appears on page 1
        title_pg = etree.Element(f'{{{W}}}titlePg')
        # Insert titlePg after cols or pgMar
        cols = sectPr.find(f'{{{W}}}cols')
        if cols is not None:
            cols_idx = list(sectPr).index(cols)
            sectPr.insert(cols_idx + 1, title_pg)
        else:
            sectPr.append(title_pg)

        # Set margins
        for tag, attrs in [
            ('pgMar', {f'{{{W}}}top':    str(TOP_MARGIN),
                       f'{{{W}}}bottom': str(BOTTOM_MARGIN),
                       f'{{{W}}}header': str(HDR_DISTANCE),
                       f'{{{W}}}left':   '1440',
                       f'{{{W}}}right':  '1440',
                       f'{{{W}}}gutter': '0'}),
        ]:
            existing = sectPr.find(f'{{{W}}}{tag}')
            if existing is not None:
                sectPr.remove(existing)
            pgSz = sectPr.find(f'{{{W}}}pgSz')
            new_el = etree.Element(f'{{{W}}}{tag}')
            for k, v in attrs.items():
                new_el.set(k, v)
            if pgSz is not None:
                pgSz_idx = list(sectPr).index(pgSz)
                sectPr.insert(pgSz_idx + 1, new_el)
            else:
                sectPr.append(new_el)

    replacements['word/document.xml']      = etree.tostring(doc_root,  xml_declaration=True, encoding='UTF-8', standalone=True)
    replacements['word/_rels/document.xml.rels'] = etree.tostring(rels_root, xml_declaration=True, encoding='UTF-8', standalone=True)

    # Patch [Content_Types].xml to register all header/footer parts.
    CT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'
    HDR_CT = 'application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml'
    FTR_CT = 'application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml'
    with zipfile.ZipFile(out_path, 'r') as zin:
        ct_xml = zin.read('[Content_Types].xml')
    ct_root = etree.fromstring(ct_xml)
    existing_parts = {el.get('PartName') for el in ct_root.findall(f'{{{CT_NS}}}Override')}

    for hdr_part in ['/word/header1.xml', '/word/header2.xml']:
        if hdr_part not in existing_parts:
            el = etree.SubElement(ct_root, f'{{{CT_NS}}}Override')
            el.set('PartName', hdr_part)
            el.set('ContentType', HDR_CT)
    if ftr_images and '/word/footer1.xml' not in existing_parts:
        el = etree.SubElement(ct_root, f'{{{CT_NS}}}Override')
        el.set('PartName', '/word/footer1.xml')
        el.set('ContentType', FTR_CT)

    # Register letterhead image parts — Word rejects unregistered parts as "unreadable content"
    IMG_CTYPES = {'.jpeg': 'image/jpeg', '.jpg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif'}
    for new_target in target_remap.values():
        part_name = f'/word/{new_target}'
        if part_name not in existing_parts:
            ext = os.path.splitext(new_target)[1].lower()
            ct = IMG_CTYPES.get(ext)
            if ct:
                el = etree.SubElement(ct_root, f'{{{CT_NS}}}Override')
                el.set('PartName', part_name)
                el.set('ContentType', ct)

    replacements['[Content_Types].xml'] = etree.tostring(ct_root, xml_declaration=True, encoding='UTF-8', standalone=True)

    _rebuild_zip(out_path, replacements)
    print(f"  saved: {out_path}")


def _build_rels(image_map, target_remap):
    lines = ["<?xml version='1.0' encoding='UTF-8' standalone='yes'?>",
             f'<Relationships xmlns="{REL}">']
    for rId, old_target in image_map.items():
        new_target = target_remap.get(old_target, old_target)
        lines.append(f'<Relationship Id="{rId}" Type="{IMG_REL}" Target="{new_target}"/>')
    lines.append('</Relationships>')
    return '\n'.join(lines)


def _next_rId(used):
    i = 1
    while f'rId{i}' in used:
        i += 1
    return f'rId{i}'


def _rel_el(rId, rel_type, target):
    el = etree.Element('Relationship')
    el.set('Id', rId)
    el.set('Type', rel_type)
    el.set('Target', target)
    return el


def _rebuild_zip(zip_path, replacements):
    tmp = zip_path + '.tmp'
    with zipfile.ZipFile(zip_path, 'r') as zin:
        with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename in replacements:
                    zout.writestr(item.filename, replacements.pop(item.filename))
                else:
                    zout.writestr(item, zin.read(item.filename))
            for fname, data in replacements.items():  # new files
                zout.writestr(fname, data)
    os.replace(tmp, zip_path)


if __name__ == '__main__':
    fix(sys.argv[1], sys.argv[2], sys.argv[3])
