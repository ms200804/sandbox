#!/usr/bin/env python3
"""
Citation Extractor — parse case citations from briefs and legal documents.

Takes a document (markdown, plain text, or extracted PDF text), finds all
case citations, resolves them against CourtListener, pulls full text,
and optionally saves to the research library.

Supported citation formats:
    - Full reporter: 546 U.S. 440, 68 F.3d 554, 123 S. Ct. 456
    - Federal supplement: 345 F. Supp. 2d 678, 123 F. Supp. 3d 456
    - Federal appendix: 456 F. App'x 789
    - State reporters: basic pattern matching
    - Slip opinions: --- F.4th ---  (flagged but not resolvable)

Usage:
    # Extract citations from a file
    python citation_extractor.py path/to/brief.md

    # Extract and save to library under a category
    python citation_extractor.py path/to/brief.md --save --category tvpa

    # Extract from multiple files (seed the library)
    python citation_extractor.py briefs/*.md --save --auto-categorize

    # Just list citations without pulling full text
    python citation_extractor.py path/to/brief.md --list-only
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Import the CL client and library when available
try:
    from cl_client import CourtListenerClient
    CL_AVAILABLE = True
except (ImportError, ValueError):
    CL_AVAILABLE = False

try:
    import library as research_library
    LIBRARY_AVAILABLE = True
except ImportError:
    LIBRARY_AVAILABLE = False


@dataclass
class Citation:
    """A parsed case citation."""
    raw: str                    # Original text as found in the document
    volume: str = ""            # e.g., "546"
    reporter: str = ""          # e.g., "U.S.", "F.3d", "F. Supp. 2d"
    page: str = ""              # e.g., "440"
    case_name: str = ""         # e.g., "Buckeye Check Cashing v. Cardegna"
    year: str = ""              # e.g., "2006"
    pinpoint: str = ""          # e.g., "at 445"
    context: str = ""           # Surrounding text from the document
    resolved: bool = False      # Whether CL lookup succeeded
    cl_data: dict = field(default_factory=dict)  # Full CL response

    @property
    def standard_cite(self) -> str:
        """Normalized citation string."""
        if self.volume and self.reporter and self.page:
            return f"{self.volume} {self.reporter} {self.page}"
        return self.raw

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "standard_cite": self.standard_cite,
            "case_name": self.case_name,
            "year": self.year,
            "volume": self.volume,
            "reporter": self.reporter,
            "page": self.page,
            "pinpoint": self.pinpoint,
            "context": self.context,
            "resolved": self.resolved,
        }


# ── Citation Parsing ────────────────────────────────────────────────

# Reporter patterns (ordered by specificity — longer patterns first)
REPORTERS = [
    # Federal
    r"F\.\s*Supp\.\s*3d",
    r"F\.\s*Supp\.\s*2d",
    r"F\.\s*Supp\.",
    r"F\.\s*App'x",
    r"F\.4th",
    r"F\.3d",
    r"F\.2d",
    r"F\.",
    r"U\.S\.",
    r"S\.\s*Ct\.",
    r"L\.\s*Ed\.\s*2d",
    r"L\.\s*Ed\.",
    # Bankruptcy
    r"B\.R\.",
    # Regional state reporters
    r"A\.3d",
    r"A\.2d",
    r"N\.E\.3d",
    r"N\.E\.2d",
    r"N\.W\.2d",
    r"N\.Y\.S\.3d",
    r"N\.Y\.S\.2d",
    r"P\.3d",
    r"P\.2d",
    r"S\.E\.2d",
    r"S\.W\.3d",
    r"S\.W\.2d",
    r"So\.\s*3d",
    r"So\.\s*2d",
    # New York
    r"N\.Y\.3d",
    r"N\.Y\.2d",
    r"N\.Y\.",
    r"A\.D\.3d",
    r"A\.D\.2d",
    r"Misc\.\s*3d",
    r"Misc\.\s*2d",
    # California
    r"Cal\.\s*App\.\s*5th",
    r"Cal\.\s*App\.\s*4th",
    r"Cal\.\s*5th",
    r"Cal\.\s*4th",
    r"Cal\.\s*Rptr\.\s*3d",
    r"Cal\.\s*Rptr\.\s*2d",
    # Texas
    r"S\.W\.3d",
    r"S\.W\.2d",
    r"Tex\.\s*App\.",
]

# Build the master regex
_reporter_alternation = "|".join(REPORTERS)
CITATION_PATTERN = re.compile(
    rf'(\d+)\s+({_reporter_alternation})\s+(\d+)'
    rf'(?:\s*,\s*(\d+))?'  # optional pinpoint
    rf'(?:\s*\(([^)]*\d{{4}}[^)]*)\))?',  # optional parenthetical with year
    re.IGNORECASE
)

# Pattern to find case names preceding citations
# Looks for "Name v. Name," or "*Name v. Name*," before a citation
CASE_NAME_PATTERN = re.compile(
    r'(?:\*?([A-Z][^*\n]{3,60}?(?:\s+v\.?\s+)[^*\n]{3,60}?)\*?'
    r'[,\s]+)?'
    r'(\d+\s+(?:' + _reporter_alternation + r')\s+\d+)',
    re.IGNORECASE
)


def extract_citations(text: str) -> list[Citation]:
    """
    Extract all case citations from text.
    Returns deduplicated list of Citation objects.
    """
    citations = []
    seen = set()

    for match in CITATION_PATTERN.finditer(text):
        volume = match.group(1)
        reporter = match.group(2)
        page = match.group(3)
        pinpoint = match.group(4) or ""
        paren = match.group(5) or ""

        # Normalize reporter spacing
        reporter_norm = re.sub(r'\s+', ' ', reporter).strip()

        # Extract year from parenthetical
        year = ""
        year_match = re.search(r'(\d{4})', paren)
        if year_match:
            year = year_match.group(1)

        cite_key = f"{volume} {reporter_norm} {page}"
        if cite_key in seen:
            continue
        seen.add(cite_key)

        # Get surrounding context (±100 chars)
        start = max(0, match.start() - 100)
        end = min(len(text), match.end() + 100)
        context = text[start:end].strip()

        citation = Citation(
            raw=match.group(0).strip(),
            volume=volume,
            reporter=reporter_norm,
            page=page,
            pinpoint=pinpoint,
            year=year,
            context=context,
        )
        citations.append(citation)

    # Try to find case names
    for name_match in CASE_NAME_PATTERN.finditer(text):
        case_name = name_match.group(1)
        cite_text = name_match.group(2)

        if not case_name:
            continue

        # Clean up case name
        case_name = case_name.strip().strip('*').strip(',').strip()
        # Remove "See", "see", "See also", etc.
        case_name = re.sub(r'^(?:See also|See|Cf\.|accord)\s+', '', case_name, flags=re.IGNORECASE)

        # Match to an existing citation
        for cit in citations:
            if cite_text.strip().startswith(f"{cit.volume} {cit.reporter}"):
                if not cit.case_name:
                    cit.case_name = case_name
                break

    return citations


def extract_from_file(file_path: str) -> list[Citation]:
    """Extract citations from a file."""
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    text = path.read_text(errors='replace')
    return extract_citations(text)


def resolve_citations(citations: list[Citation], client=None) -> list[Citation]:
    """
    Resolve citations against CourtListener — pull full opinion text
    and metadata for each citation.
    """
    if not CL_AVAILABLE or client is None:
        print("  CourtListener client not available. Skipping resolution.")
        return citations

    for cit in citations:
        try:
            result = client.citation_lookup(cit.standard_cite)
            if result:
                cit.resolved = True
                cit.cl_data = {
                    "case_name": result.case_name,
                    "citation": result.citation,
                    "court": result.court,
                    "date_filed": result.date_filed,
                    "text": result.text[:500] + "..." if len(result.text) > 500 else result.text,
                    "url": result.url,
                    "cl_id": result.id,
                }
                if not cit.case_name:
                    cit.case_name = result.case_name
                print(f"  ✓ {cit.standard_cite} → {result.case_name}")
            else:
                print(f"  ✗ {cit.standard_cite} — not found in CL")
        except Exception as e:
            print(f"  ✗ {cit.standard_cite} — error: {e}")

    return citations


def save_to_library(citations: list[Citation], category: str,
                    topic: str = "extracted_cases",
                    source_file: str = "") -> str:
    """Save extracted citations to the research library."""
    if not LIBRARY_AVAILABLE:
        return "Library not available."

    results = {
        "source": source_file,
        "extraction_type": "brief_citation_extraction",
        "results": [
            {
                "case_name": cit.case_name or "Unknown",
                "citation": cit.standard_cite,
                "year": cit.year,
                "resolved": cit.resolved,
                "context_in_brief": cit.context,
                **({"cl_data": cit.cl_data} if cit.resolved else {}),
            }
            for cit in citations
        ],
    }

    path = research_library.save_research(
        category=category,
        topic=topic,
        results=results,
        query=f"Extracted from {source_file}",
    )
    return f"Saved {len(citations)} citations to {category}/{topic}"


def auto_categorize(citations: list[Citation], text: str) -> list[str]:
    """
    Suggest categories based on citation context and document content.
    Returns list of suggested category names.

    This is a simple keyword-based heuristic. The Slack bot's Claude
    layer will do better categorization when available.
    """
    text_lower = text.lower()
    suggestions = []

    keyword_categories = {
        "tvpa": ["trafficking victims", "tvpa", "18 u.s.c. § 1589",
                 "18 u.s.c. § 1590", "forced labor", "sex trafficking"],
        "arbitration": ["arbitration", "faa", "federal arbitration act",
                        "compel arbitration", "arbitration clause", "jams"],
        "securities": ["securities", "sec ", "10b-5", "insider trading",
                       "securities exchange act", "whistleblower"],
        "fiduciary_duty": ["fiduciary", "fiduciary duty", "breach of fiduciary",
                           "duty of loyalty", "duty of care"],
        "employment": ["employment", "feha", "title vii", "wrongful termination",
                       "discrimination", "harassment", "retaliation", "wage"],
        "civil_rights": ["civil rights", "42 u.s.c. § 1983", "section 1983",
                         "qualified immunity", "deliberate indifference"],
        "antitrust": ["antitrust", "sherman act", "clayton act",
                      "price fixing", "monopol"],
        "rico": ["rico", "racketeer", "18 u.s.c. § 1962"],
        "corporate": ["derivative", "shareholder", "corporate governance",
                       "business judgment", "books and records"],
        "negligence": ["negligence", "negligent supervision", "duty of care",
                        "proximate cause", "reasonable care"],
    }

    for category, keywords in keyword_categories.items():
        if any(kw in text_lower for kw in keywords):
            suggestions.append(category)

    return suggestions or ["general"]


# ── CLI ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract case citations from legal documents"
    )
    parser.add_argument("files", nargs="+", help="Files to extract citations from")
    parser.add_argument("--list-only", action="store_true",
                        help="Just list citations, don't resolve against CL")
    parser.add_argument("--save", action="store_true",
                        help="Save results to the research library")
    parser.add_argument("--category", default="",
                        help="Library category (auto-detected if not specified)")
    parser.add_argument("--topic", default="",
                        help="Library topic name (defaults to source filename)")
    parser.add_argument("--auto-categorize", action="store_true",
                        help="Auto-detect categories from document content")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    all_citations = []
    all_text = ""

    for file_path in args.files:
        print(f"\n{'═' * 60}")
        print(f"Extracting from: {file_path}")
        print(f"{'═' * 60}")

        try:
            text = Path(file_path).read_text(errors='replace')
            all_text += text
            citations = extract_citations(text)
            print(f"Found {len(citations)} unique citations\n")

            if not args.list_only and CL_AVAILABLE:
                try:
                    client = CourtListenerClient()
                    citations = resolve_citations(citations, client)
                except ValueError:
                    print("  (CL token not set, skipping resolution)")

            for cit in citations:
                status = "✓" if cit.resolved else "○"
                name = cit.case_name or "(name not found)"
                year = f" ({cit.year})" if cit.year else ""
                print(f"  {status} {cit.standard_cite} — {name}{year}")

            all_citations.extend(citations)

        except FileNotFoundError:
            print(f"  File not found: {file_path}")
            continue

    # Output
    if args.json:
        output = [c.to_dict() for c in all_citations]
        print(json.dumps(output, indent=2))

    # Save to library
    if args.save and LIBRARY_AVAILABLE:
        if args.auto_categorize or not args.category:
            categories = auto_categorize(all_citations, all_text)
            print(f"\nSuggested categories: {categories}")
            category = categories[0]
        else:
            category = args.category

        topic = args.topic or Path(args.files[0]).stem
        result = save_to_library(all_citations, category, topic,
                                 source_file=", ".join(args.files))
        print(f"\n{result}")

    # Summary
    print(f"\n{'─' * 40}")
    resolved = sum(1 for c in all_citations if c.resolved)
    print(f"Total: {len(all_citations)} citations, {resolved} resolved via CL")
