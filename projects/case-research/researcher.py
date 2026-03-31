#!/usr/bin/env python3
"""
Legal Research Agent — iterative, jurisdiction-aware case research.

Takes a legal question + jurisdiction, searches CourtListener iteratively,
follows citation chains, detects adverse authority, and produces structured
JSON output matching the schema in prompts/researcher.md.

Usage:
    # Topic research
    python researcher.py "charging lien vacatur standard" --jurisdiction ca2

    # Citation lookup
    python researcher.py --cite "250 F.3d 171"

    # Shepardize a list of citations
    python researcher.py --shepardize "250 F.3d 171" "997 F.2d 1028" "521 U.S. 203"

    # Save results to library
    python researcher.py "charging lien vacatur" --jurisdiction ca2 --save --category liens
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from cl_client import CourtListenerClient

try:
    import library as research_library
    LIBRARY_AVAILABLE = True
except ImportError:
    LIBRARY_AVAILABLE = False


# ── Court / Jurisdiction helpers ────────────────────────────────────

# Federal circuits and their district courts
CIRCUIT_COURTS = {
    "ca1": ["mad", "nhd", "rid", "med", "prd"],
    "ca2": ["nyd", "nysd", "nyed", "nywd", "nynd", "ctd", "vtd"],
    "ca3": ["pad", "paed", "pawd", "pamd", "njd", "ded", "vid"],
    "ca4": ["mdd", "vaed", "vawd", "wvsd", "wvnd", "nced", "ncwd", "ncmd", "scd"],
    "ca5": ["txsd", "txed", "txwd", "txnd", "laed", "lawd", "lamd", "mssd", "msnd"],
    "ca6": ["ohsd", "ohnd", "mied", "miwd", "kyed", "kywd", "tned", "tnwd", "tnmd"],
    "ca7": ["ilnd", "ilsd", "ilcd", "wied", "wiwd", "insd", "innd"],
    "ca8": ["mnd", "mod", "mowd", "moed", "ared", "arwd", "iand", "iasd", "ned", "ndd", "sdd"],
    "ca9": ["cand", "cacd", "casd", "caed", "ord", "wad", "wawd", "waed",
            "azd", "nvd", "idd", "mtd", "akd", "hid", "gud", "mpd"],
    "ca10": ["cod", "ksd", "nmd", "oknd", "oked", "okwd", "utd", "wyd"],
    "ca11": ["flsd", "flmd", "flnd", "gand", "gamd", "gasd", "alnd", "almd", "alsd"],
    "cadc": ["dcd"],
    "cafc": [],
}


def is_binding(court_id: str, target_jurisdiction: str) -> bool:
    """Determine if a court's opinions are binding for the target jurisdiction."""
    target = target_jurisdiction.lower()
    court = court_id.lower()

    # SCOTUS binds everyone
    if court in ("scotus", "supreme court"):
        return True

    # Same circuit is binding
    if court == target:
        return True

    # If target is a district court, check if the opinion is from its circuit
    for circuit, districts in CIRCUIT_COURTS.items():
        if target in districts and court == circuit:
            return True

    return False


def get_circuit_for_court(court_id: str) -> str:
    """Get the circuit a court belongs to."""
    court = court_id.lower()
    if court.startswith("ca") or court == "scotus":
        return court
    for circuit, districts in CIRCUIT_COURTS.items():
        if court in districts:
            return circuit
    return court


# ── Research functions ──────────────────────────────────────────────

def topic_research(client: CourtListenerClient, query: str,
                   jurisdiction: str, max_results: int = 15) -> dict:
    """
    Full topic research: search, filter, read opinions, follow citations,
    check for adverse authority.
    """
    search_log = []
    all_results = []
    seen_ids = set()

    # Phase 1: Initial search — binding authority
    print(f"Searching: '{query}' in {jurisdiction}...")
    binding_results = client.search_opinions(query, court=jurisdiction, limit=20)
    search_log.append(
        f"Initial search: '{query}' in {jurisdiction} -> {len(binding_results)} results"
    )
    print(f"  Found {len(binding_results)} results in {jurisdiction}")

    for r in binding_results:
        if r["id"] and r["id"] not in seen_ids:
            seen_ids.add(r["id"])
            r["_binding"] = True
            r["_source"] = "direct_search"
            all_results.append(r)

    # Also search SCOTUS if target isn't SCOTUS
    if jurisdiction != "scotus":
        scotus_results = client.search_opinions(query, court="scotus", limit=5)
        search_log.append(
            f"SCOTUS search: '{query}' -> {len(scotus_results)} results"
        )
        for r in scotus_results:
            if r["id"] and r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                r["_binding"] = True
                r["_source"] = "scotus_search"
                all_results.append(r)

    # Phase 2: Broader search for persuasive authority
    broad_results = client.search_opinions(query, limit=20)
    new_persuasive = 0
    for r in broad_results:
        if r["id"] and r["id"] not in seen_ids:
            seen_ids.add(r["id"])
            r["_binding"] = is_binding(r.get("court_id", ""), jurisdiction)
            r["_source"] = "broad_search"
            all_results.append(r)
            new_persuasive += 1
    search_log.append(
        f"Broad search (all courts): '{query}' -> {new_persuasive} additional results"
    )
    print(f"  +{new_persuasive} persuasive results from other courts")

    # Phase 3: Follow citation chains from top binding results
    binding_cases = [r for r in all_results if r.get("_binding")]
    chain_additions = 0
    for case in binding_cases[:3]:  # top 3 binding cases
        cluster_id = case.get("id")
        if not cluster_id:
            continue

        # Forward citations (who cites this case)
        try:
            citing = client.citing_opinions(cluster_id, limit=10)
            for c in citing:
                cid = c.get("id")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    c["_binding"] = is_binding(c.get("court", ""), jurisdiction)
                    c["_source"] = f"cited_by_{cluster_id}"
                    c["cite_count"] = 0
                    c["snippet"] = ""
                    all_results.append(c)
                    chain_additions += 1
        except Exception:
            pass

    if chain_additions:
        search_log.append(
            f"Citation chain following from top {min(3, len(binding_cases))} binding cases -> {chain_additions} additional"
        )
        print(f"  +{chain_additions} from citation chains")

    # Phase 4: Adverse authority search
    adverse_queries = _generate_adverse_queries(query)
    adverse_results = []
    for aq in adverse_queries:
        try:
            adv = client.search_opinions(aq, court=jurisdiction, limit=5)
            for r in adv:
                if r["id"] and r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    r["_binding"] = True
                    r["_source"] = "adverse_search"
                    r["_adverse_query"] = aq
                    all_results.append(r)
                    adverse_results.append(r)
        except Exception:
            pass
    if adverse_results:
        search_log.append(
            f"Adverse authority search: {len(adverse_queries)} queries -> {len(adverse_results)} potential adverse cases"
        )
        print(f"  {len(adverse_results)} potential adverse authority found")

    # Phase 5: Read opinion text for top results and build structured output
    # Sort: binding first, then by cite count
    all_results.sort(
        key=lambda r: (not r.get("_binding", False), -(r.get("cite_count", 0) or 0))
    )

    structured_results = []
    for r in all_results[:max_results]:
        opinion_text = ""
        opinion_id = r.get("opinion_id")
        if opinion_id:
            try:
                opinion_text = client.get_opinion_text(opinion_id)
            except Exception:
                pass

        holding, key_quotes = _extract_holding_and_quotes(opinion_text, query)

        structured_results.append({
            "case_name": r.get("case_name", ""),
            "citation": r.get("citation", ""),
            "court": r.get("court_id", r.get("court", "")),
            "date_filed": r.get("date_filed", ""),
            "binding": r.get("_binding", False),
            "holding": holding,
            "key_quotes": key_quotes,
            "relevance": "adverse" if r.get("_source") == "adverse_search" else "supports",
            "relevance_notes": f"Found via {r.get('_source', 'search')}",
            "negative_treatment": None,
            "cl_url": r.get("url", ""),
            "cl_id": r.get("id"),
            "cite_count": r.get("cite_count", 0),
        })

    # Separate adverse authority
    adverse_authority = [
        {
            "case_name": r["case_name"],
            "citation": r["citation"],
            "why_adverse": f"Found searching: '{r.get('_adverse_query', 'adverse terms')}'"
        }
        for r in adverse_results[:5]
    ]

    # Detect circuit splits (simple heuristic: same query, different outcomes in different circuits)
    circuit_splits = _detect_circuit_splits(all_results, jurisdiction)

    # Assess confidence
    binding_count = sum(1 for r in structured_results if r["binding"])
    confidence = "high" if binding_count >= 3 else "medium" if binding_count >= 1 else "low"
    confidence_notes = (
        f"{binding_count} binding authorities found. "
        f"{len(structured_results)} total results. "
    )
    if not binding_count:
        confidence_notes += "No binding authority — issue may be novel in this circuit."

    # Gaps
    gaps = []
    if not binding_count:
        gaps.append(f"No binding authority found in {jurisdiction} — check Westlaw/Lexis")
    if len(all_results) < 3:
        gaps.append("Very few results — CL coverage may be limited for this topic")

    return {
        "query": query,
        "jurisdiction": jurisdiction,
        "research_type": "topic",
        "results": structured_results,
        "adverse_authority": adverse_authority,
        "circuit_splits": circuit_splits,
        "search_log": search_log,
        "confidence": confidence,
        "confidence_notes": confidence_notes,
        "gaps": gaps,
        "meta": {
            "total_found": len(all_results),
            "returned": len(structured_results),
            "courts_searched": list(set(
                r.get("court_id", r.get("court", "")) for r in all_results
            )),
            "cl_queries_used": len(search_log),
            "timestamp": datetime.now().isoformat(),
        },
    }


def citation_lookup(client: CourtListenerClient, citation: str,
                    jurisdiction: str = "") -> dict:
    """Look up a single citation: full text, forward/backward citations, treatment."""
    print(f"Looking up: {citation}...")

    opinion = client.citation_lookup(citation)
    if not opinion:
        return {
            "query": citation,
            "research_type": "citation_lookup",
            "results": [],
            "confidence": "low",
            "gaps": [f"Citation '{citation}' not found in CourtListener"],
        }

    # Forward citations
    print(f"  Found: {opinion.case_name}")
    forward = []
    try:
        forward = client.citing_opinions(opinion.id, limit=20)
        print(f"  {len(forward)} forward citations")
    except Exception:
        pass

    # Check for negative treatment in forward citations
    negative_treatment = None
    for fwd in forward:
        name_lower = fwd.get("case_name", "").lower()
        if any(term in name_lower for term in ["overrul", "revers", "abrogat"]):
            negative_treatment = {
                "type": "potential_negative",
                "case": fwd.get("case_name"),
                "citation": fwd.get("citation"),
                "note": "Name suggests negative treatment — verify on Westlaw/Lexis",
            }
            break

    holding, key_quotes = _extract_holding_and_quotes(opinion.text, citation)

    result = {
        "case_name": opinion.case_name,
        "citation": opinion.citation or citation,
        "court": opinion.court,
        "date_filed": opinion.date_filed,
        "binding": is_binding(opinion.court, jurisdiction) if jurisdiction else None,
        "holding": holding,
        "key_quotes": key_quotes,
        "full_text_available": bool(opinion.text),
        "text_length": len(opinion.text),
        "negative_treatment": negative_treatment,
        "forward_citations": len(forward),
        "forward_citation_sample": [
            {"case_name": f.get("case_name"), "citation": f.get("citation")}
            for f in forward[:5]
        ],
        "cl_url": opinion.url,
        "cl_id": opinion.id,
    }

    return {
        "query": citation,
        "jurisdiction": jurisdiction,
        "research_type": "citation_lookup",
        "results": [result],
        "confidence": "high" if opinion.text else "medium",
        "confidence_notes": (
            "Full text available" if opinion.text
            else "Citation found but full text not available in CL"
        ),
        "gaps": [] if opinion.text else ["Full opinion text not in CL — pull from Westlaw/Lexis"],
        "meta": {
            "timestamp": datetime.now().isoformat(),
        },
    }


def shepardize(client: CourtListenerClient, citations: list[str]) -> dict:
    """Check treatment status for a list of citations."""
    print(f"Shepardizing {len(citations)} citations...")
    results = []

    for cite in citations:
        print(f"  Checking: {cite}...")
        opinion = client.citation_lookup(cite)

        if not opinion:
            results.append({
                "citation": cite,
                "status": "not_found",
                "note": "Not found in CourtListener",
            })
            continue

        # Check forward citations for treatment signals
        forward = []
        try:
            forward = client.citing_opinions(opinion.id, limit=30)
        except Exception:
            pass

        # Simple treatment heuristic based on forward citation count and recency
        status = "good_law"
        notes = []

        if not forward:
            status = "caution"
            notes.append("No forward citations found — may be very recent or limited CL coverage")

        # Check if any forward cites are from higher courts (possible reversal)
        for fwd in forward:
            court = fwd.get("court", "").lower()
            if court == "scotus" and opinion.court.lower() != "scotus":
                notes.append(f"Cited by SCOTUS: {fwd.get('case_name', '')}")

        results.append({
            "citation": cite,
            "case_name": opinion.case_name,
            "court": opinion.court,
            "date_filed": opinion.date_filed,
            "status": status,
            "forward_citations": len(forward),
            "notes": notes,
            "cl_url": opinion.url,
            "cl_id": opinion.id,
        })

    return {
        "query": f"Shepardize: {', '.join(citations)}",
        "research_type": "shepardize",
        "results": results,
        "confidence": "medium",
        "confidence_notes": (
            "CL forward citation analysis only. Does NOT replace Shepard's/KeyCite "
            "for definitive treatment status. Always verify on Westlaw/Lexis for "
            "anything going into a brief."
        ),
        "gaps": [
            "CL cannot detect: overruled, distinguished, limited, or abrogated treatment",
            "CL coverage of unpublished opinions is incomplete",
        ],
        "meta": {
            "citations_checked": len(citations),
            "timestamp": datetime.now().isoformat(),
        },
    }


# ── Internal helpers ────────────────────────────────────────────────

def _generate_adverse_queries(query: str) -> list[str]:
    """Generate search queries that might find contrary authority."""
    # Simple keyword inversion — look for opposite outcomes
    adverse_terms = []

    words = query.lower().split()
    negation_pairs = {
        "grant": "deny",
        "granted": "denied",
        "allow": "deny",
        "enforce": "unenforceable",
        "valid": "invalid",
        "vacate": "uphold",
        "vacatur": "enforce",
        "liable": "not liable",
        "affirm": "reverse",
    }

    for word in words:
        if word in negation_pairs:
            modified = query.lower().replace(word, negation_pairs[word])
            adverse_terms.append(modified)

    # Also try adding "denied" / "rejected" to the original query
    if not adverse_terms:
        adverse_terms.append(f"{query} denied")
        adverse_terms.append(f"{query} rejected")

    return adverse_terms[:3]


def _extract_holding_and_quotes(text: str, query: str) -> tuple[str, list[dict]]:
    """
    Extract a holding statement and key quotes from opinion text.

    This is a best-effort extraction — looks for common holding patterns
    and sentences containing query-relevant terms.
    """
    if not text:
        return "Full text not available in CourtListener", []

    # Truncate very long opinions for processing
    text_sample = text[:15000]
    sentences = [s.strip() for s in text_sample.replace('\n', ' ').split('.') if s.strip()]

    # Look for holding-like sentences
    holding_signals = ["we hold", "we conclude", "the court holds", "we therefore hold",
                       "it is ordered", "we find that", "we affirm", "we reverse",
                       "the court finds", "we grant", "we deny"]
    holding = ""
    for sent in sentences:
        sent_lower = sent.lower()
        if any(signal in sent_lower for signal in holding_signals):
            holding = sent.strip() + "."
            break

    if not holding and sentences:
        holding = "(Holding not auto-extracted — review full text)"

    # Find query-relevant quotes
    query_terms = [t.lower() for t in query.split() if len(t) > 3]
    key_quotes = []
    for sent in sentences:
        sent_lower = sent.lower()
        relevance = sum(1 for term in query_terms if term in sent_lower)
        if relevance >= 2 and len(sent) > 40:
            key_quotes.append({
                "text": sent.strip() + ".",
                "pinpoint": "",
                "context": f"Contains {relevance} query terms",
            })
        if len(key_quotes) >= 3:
            break

    return holding, key_quotes


def _detect_circuit_splits(results: list[dict], target_jurisdiction: str) -> list[dict]:
    """
    Simple circuit split detection: check if results from different circuits
    show up in both the main and adverse searches.
    """
    main_circuits = set()
    adverse_circuits = set()

    for r in results:
        circuit = get_circuit_for_court(r.get("court_id", r.get("court", "")))
        if r.get("_source") == "adverse_search":
            adverse_circuits.add(circuit)
        else:
            main_circuits.add(circuit)

    # If we have results from different circuits in both pools, flag it
    if main_circuits and adverse_circuits:
        overlap = main_circuits & adverse_circuits
        split_circuits = adverse_circuits - main_circuits
        if split_circuits:
            return [{
                "issue": "Potential circuit split detected — some circuits appear only in adverse results",
                "circuits_for": sorted(main_circuits - adverse_circuits),
                "circuits_against": sorted(split_circuits),
                "scotus_status": "Unknown — verify manually",
            }]

    return []


# ── Main / CLI ──────────────────────────────────────────────────────

def run_research(query: str = "", jurisdiction: str = "",
                 cite: str = "", shepardize_cites: list[str] | None = None,
                 save: bool = False, category: str = "", topic: str = "",
                 max_results: int = 15) -> dict:
    """Main entry point — dispatches to the right research mode."""
    client = CourtListenerClient()

    if shepardize_cites:
        result = shepardize(client, shepardize_cites)
    elif cite:
        result = citation_lookup(client, cite, jurisdiction)
    elif query:
        result = topic_research(client, query, jurisdiction, max_results)
    else:
        return {"error": "Provide a query, --cite, or --shepardize"}

    # Save to library if requested
    if save and LIBRARY_AVAILABLE:
        cat = category or "general"
        top = topic or query[:50].replace(" ", "_").lower()
        path = research_library.save_research(
            category=cat,
            topic=top,
            results=result,
            query=query or cite or str(shepardize_cites),
            jurisdiction=jurisdiction,
        )
        print(f"\nSaved to library: {path}")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Legal research agent")
    parser.add_argument("query", nargs="?", default="",
                        help="Research question or topic")
    parser.add_argument("--jurisdiction", "-j", default="",
                        help="Target jurisdiction (e.g., ca2, ca9, scotus)")
    parser.add_argument("--cite", default="",
                        help="Look up a specific citation")
    parser.add_argument("--shepardize", nargs="+", default=None,
                        help="Shepardize a list of citations")
    parser.add_argument("--max-results", type=int, default=15,
                        help="Max results to return (default: 15)")
    parser.add_argument("--save", action="store_true",
                        help="Save results to the research library")
    parser.add_argument("--category", default="",
                        help="Library category for --save")
    parser.add_argument("--topic", default="",
                        help="Library topic for --save")
    parser.add_argument("--json", action="store_true",
                        help="Output raw JSON (default: formatted summary)")
    args = parser.parse_args()

    result = run_research(
        query=args.query,
        jurisdiction=args.jurisdiction,
        cite=args.cite,
        shepardize_cites=args.shepardize,
        save=args.save,
        category=args.category,
        topic=args.topic,
        max_results=args.max_results,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        # Formatted summary
        print(f"\n{'=' * 60}")
        print(f"Research: {result.get('query', '')}")
        print(f"Type: {result.get('research_type', '')}")
        if result.get("jurisdiction"):
            print(f"Jurisdiction: {result['jurisdiction']}")
        print(f"Confidence: {result.get('confidence', 'unknown')}")
        print(f"{'=' * 60}")

        for i, r in enumerate(result.get("results", []), 1):
            binding_tag = " [BINDING]" if r.get("binding") else ""
            status_tag = f" [{r['status'].upper()}]" if r.get("status") else ""
            print(f"\n{i}. {r.get('case_name', 'Unknown')}{binding_tag}{status_tag}")
            print(f"   {r.get('citation', '(no cite)')}")
            if r.get("court"):
                print(f"   Court: {r['court']}  Filed: {r.get('date_filed', '?')}")
            if r.get("holding"):
                hold = r["holding"][:200]
                print(f"   Holding: {hold}{'...' if len(r.get('holding', '')) > 200 else ''}")
            if r.get("forward_citations"):
                print(f"   Forward citations: {r['forward_citations']}")

        if result.get("adverse_authority"):
            print(f"\n{'─' * 40}")
            print("ADVERSE AUTHORITY:")
            for a in result["adverse_authority"]:
                print(f"  - {a['case_name']} ({a['citation']})")
                print(f"    {a['why_adverse']}")

        if result.get("circuit_splits"):
            print(f"\n{'─' * 40}")
            print("CIRCUIT SPLITS:")
            for s in result["circuit_splits"]:
                print(f"  Issue: {s['issue']}")
                print(f"  For: {', '.join(s['circuits_for'])}")
                print(f"  Against: {', '.join(s['circuits_against'])}")

        if result.get("gaps"):
            print(f"\n{'─' * 40}")
            print("GAPS (check Westlaw/Lexis):")
            for g in result["gaps"]:
                print(f"  - {g}")

        if result.get("search_log"):
            print(f"\n{'─' * 40}")
            print("SEARCH LOG:")
            for entry in result["search_log"]:
                print(f"  {entry}")

        meta = result.get("meta", {})
        if meta:
            print(f"\n{'─' * 40}")
            print(f"Total found: {meta.get('total_found', '?')} | "
                  f"Returned: {meta.get('returned', '?')} | "
                  f"Queries: {meta.get('cl_queries_used', '?')}")
