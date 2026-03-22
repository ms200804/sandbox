#!/usr/bin/env python3
"""
Process incoming briefs — extract citations and save to research library.

Scans the incoming/ folder for documents, extracts citations from each,
resolves against CourtListener, saves to the library, and moves processed
files to incoming/processed/.

Usage:
    python process_incoming.py
    python process_incoming.py --dry-run    # show what would be processed
"""

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Add project paths
SANDBOX_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from citation_extractor import extract_citations, auto_categorize, save_to_library

INCOMING_DIR = SANDBOX_ROOT / "incoming"
PROCESSED_DIR = INCOMING_DIR / "processed"

SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf", ".docx"}


def extract_text(file_path: Path) -> str:
    """Extract plain text from a supported file format."""
    ext = file_path.suffix.lower()

    if ext in (".md", ".txt"):
        return file_path.read_text(errors='replace')

    if ext == ".pdf":
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", str(file_path), "-"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                return result.stdout
            print(f"  pdftotext failed: {result.stderr}")
        except FileNotFoundError:
            print("  pdftotext not found — install poppler-utils")
        except subprocess.TimeoutExpired:
            print("  pdftotext timed out")
        return ""

    if ext == ".docx":
        try:
            from docx import Document
            doc = Document(str(file_path))
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            print("  python-docx not installed — run: uv pip install python-docx")
        except Exception as e:
            print(f"  docx extraction failed: {e}")
        return ""

    return ""


def process_file(file_path: Path, dry_run: bool = False) -> dict:
    """Process a single file. Returns summary dict."""
    print(f"\n{'─' * 50}")
    print(f"Processing: {file_path.name}")

    text = extract_text(file_path)
    if not text.strip():
        print("  No text extracted, skipping.")
        return {"file": file_path.name, "status": "no_text", "citations": 0}

    citations = extract_citations(text)
    if not citations:
        print("  No citations found.")
        return {"file": file_path.name, "status": "no_citations", "citations": 0}

    categories = auto_categorize(citations, text)
    category = categories[0]

    print(f"  Found {len(citations)} citations")
    print(f"  Auto-category: {category}")
    for cit in citations[:5]:
        name = cit.case_name or "(name not found)"
        print(f"    • {cit.standard_cite} — {name}")
    if len(citations) > 5:
        print(f"    ... +{len(citations) - 5} more")

    if dry_run:
        print("  (dry run — not saving)")
        return {
            "file": file_path.name, "status": "dry_run",
            "citations": len(citations), "category": category,
        }

    # Save to library
    topic = file_path.stem
    result = save_to_library(
        citations, category=category, topic=topic,
        source_file=file_path.name,
    )
    print(f"  {result}")

    # Move to processed
    PROCESSED_DIR.mkdir(exist_ok=True)
    dest = PROCESSED_DIR / file_path.name
    if dest.exists():
        # Add timestamp to avoid overwrite
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = PROCESSED_DIR / f"{file_path.stem}_{ts}{file_path.suffix}"
    shutil.move(str(file_path), str(dest))
    print(f"  Moved to processed/")

    return {
        "file": file_path.name, "status": "processed",
        "citations": len(citations), "category": category,
    }


def main(dry_run: bool = False):
    """Process all files in the incoming directory."""
    if not INCOMING_DIR.exists():
        print(f"Incoming directory not found: {INCOMING_DIR}")
        return

    files = [
        f for f in INCOMING_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    if not files:
        print("No files to process in incoming/")
        return

    print(f"Found {len(files)} file(s) to process")
    if dry_run:
        print("(DRY RUN — no changes will be made)\n")

    results = []
    for f in sorted(files):
        results.append(process_file(f, dry_run=dry_run))

    # Summary
    print(f"\n{'═' * 50}")
    print("SUMMARY")
    processed = sum(1 for r in results if r["status"] == "processed")
    total_cites = sum(r["citations"] for r in results)
    print(f"  Files processed: {processed}/{len(files)}")
    print(f"  Total citations extracted: {total_cites}")

    categories_seen = set(r.get("category", "") for r in results if r.get("category"))
    if categories_seen:
        print(f"  Categories: {', '.join(sorted(categories_seen))}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process incoming briefs")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be processed without making changes")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
