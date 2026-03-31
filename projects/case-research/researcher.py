#!/usr/bin/env python3
"""
Legal Research Agent — iterative, jurisdiction-aware case research.

Takes a legal question + jurisdiction, searches CourtListener iteratively,
follows citation chains, detects adverse authority, and produces structured
JSON output.

Key feature: tiered query refinement using CL's Solr/Lucene syntax —
quoted phrases, proximity, boolean, field-specific searches. Starts tight,
broadens only if needed.

Usage:
    # Topic research
    python researcher.py "charging lien vacatur standard" --jurisdiction ca5

    # Citation lookup
    python researcher.py --cite "250 F.3d 171"

    # Shepardize a list of citations
    python researcher.py --shepardize "250 F.3d 171" "997 F.2d 1028"

    # Save results to library
    python researcher.py "charging lien vacatur" --jurisdiction ca5 --save --category liens
"""

import argparse
import json
import re
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
    if court in ("scotus", "supreme court"):
        return True
    if court == target:
        return True
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


# ── Query Refinement Engine ───────────────────────────────────────
#
# CL supports full Solr/Lucene syntax:
#   - Quoted phrases: "charging lien"
#   - Proximity: "charging lien"~5
#   - Boolean: AND, OR, NOT, -, ()
#   - Field-specific: caseName:, court_id:, citeCount:, dateFiled:
#   - Wildcards: immigra*, ?mmigra*
#   - Ranges: citeCount:[10 TO *], dateFiled:[2020-01-01 TO *]
#   - Fuzzy: immigrant~
#
# Strategy: decompose the natural language query into legal concepts,
# then generate tiered queries from tight to broad.

# Two-word legal phrases that courts actually use in opinions.
# Keep these SHORT (2 words) — they're the building blocks for Solr queries.
# Longer concepts are composed from these + proximity operators.
LEGAL_PHRASES = [
    # Liens
    "charging lien", "retaining lien", "attorney lien", "attorney's lien",
    "lien priority", "lien subordination", "lien enforcement",
    "lien modification", "lien vacatur", "equitable lien",
    # Fees
    "quantum meruit", "contingency fee", "fee agreement", "fee dispute",
    "fee shifting", "reasonable value", "attorneys' fees", "attorney's fees",
    "fee petition", "fee award",
    # Motions
    "motion to vacate", "motion to modify", "motion to compel",
    "motion to dismiss", "summary judgment", "motion for reconsideration",
    # Authority / Power
    "inherent authority", "inherent power", "docket management",
    "case management", "docket control", "supervisory authority",
    # Magistrate / Referral
    "magistrate judge", "pretrial matter", "non-dispositive",
    "dispositive motion", "de novo review",
    # Estoppel / Preclusion
    "judicial estoppel", "equitable estoppel", "collateral estoppel",
    "res judicata", "stare decisis",
    # Standards
    "abuse of discretion", "de novo", "clearly erroneous",
    "due process", "equal protection",
    # Attorney status
    "discharged attorney", "terminated attorney", "former attorney",
    "pro hac vice", "for cause", "good cause", "without cause",
    "substitution of counsel", "withdrawal of counsel",
    # Bankruptcy
    "bankruptcy estate", "automatic stay", "chapter 7",
    "bankruptcy trustee", "abandoned property",
    # Injunctions
    "preliminary injunction", "temporary restraining",
    # Jurisdiction
    "personal jurisdiction", "subject matter jurisdiction",
    "forum non conveniens",
    # Discovery
    "discovery dispute", "protective order", "work product",
    "attorney-client privilege",
    # Other
    "class action", "class certification",
    "statute of limitations",
    "sex trafficking", "trafficking victims",
    "litigation funding", "litigation funder",
]

STOPWORDS = {"the", "a", "an", "of", "in", "for", "to", "and", "or", "on",
             "by", "is", "are", "was", "were", "be", "been", "being",
             "with", "at", "from", "as", "into", "through", "during",
             "under", "between", "after", "before", "that", "this",
             "which", "what", "when", "where", "how", "can", "should",
             "may", "must", "whether", "not", "no", "but", "if",
             "its", "their", "also", "such", "upon", "any", "all"}


def decompose_query(query: str) -> dict:
    """
    Decompose a natural language legal query into structured components.
    Prefers short (2-word) phrases that actually appear in court opinions.
    """
    query_lower = query.lower().strip()

    # Find legal phrases present in the query (prefer shorter/more fundamental)
    found_phrases = []
    remaining = query_lower
    # Sort by length ascending so we match the fundamental 2-word phrases first,
    # not compound phrases that won't appear verbatim in opinions
    for phrase in sorted(LEGAL_PHRASES, key=len):
        if phrase in remaining:
            found_phrases.append(phrase)
            # Only remove the phrase from remaining if it's fully contained
            # (avoid removing substrings that break other phrase detection)
            remaining = remaining.replace(phrase, " ", 1)

    # Deduplicate phrases (a longer phrase might contain a shorter one)
    # Keep both — the tiered queries will use them at different levels
    found_phrases = list(dict.fromkeys(found_phrases))

    # Extract remaining meaningful terms
    remaining_words = [w.strip(".,;:!?()[]{}\"'") for w in remaining.split()]
    key_terms = [w for w in remaining_words if w and len(w) > 2 and w not in STOPWORDS]

    return {
        "original": query,
        "phrases": found_phrases,
        "key_terms": key_terms,
    }


def generate_tiered_queries(decomposed: dict) -> list[dict]:
    """
    Generate queries from tightest to broadest.

    Tiers:
      1. All phrases quoted + ANDed (tightest)
      2. All phrases quoted + ANDed (no extra terms — in case terms add noise)
      3. Primary phrase only (if multiple phrases, try just the most specific one)
      4. Phrases with proximity (~50) between them
      5. Primary phrase + key terms ANDed
      6. Broad OR (last resort, but still uses quoted phrases)
    """
    phrases = decomposed["phrases"]
    terms = decomposed["key_terms"]
    queries = []

    # Tier 1: All phrases ANDed with extra terms
    if phrases and terms:
        q = " AND ".join(f'"{p}"' for p in phrases) + " AND " + " AND ".join(terms)
        queries.append({
            "query": q,
            "tier": "phrases_and_terms",
            "description": f"All phrases + terms ANDed",
        })

    # Tier 2: Just phrases ANDed (drop extra terms that might add noise)
    if len(phrases) >= 2:
        q = " AND ".join(f'"{p}"' for p in phrases)
        queries.append({
            "query": q,
            "tier": "phrases_only",
            "description": f"Phrases only: {', '.join(phrases)}",
        })

    # Tier 3: Primary phrase alone (most specific phrase, not just longest)
    # Heuristic: prefer the FIRST phrase found (user put it first = most important),
    # not the longest (which may be generic like "inherent power")
    if phrases:
        primary = phrases[0]  # first phrase = user's primary concept
        q = f'"{primary}"'
        queries.append({
            "query": q,
            "tier": "primary_phrase",
            "description": f"Primary phrase: \"{primary}\"",
        })

    # Tier 4: If we have 2+ phrases, try them as a proximity search
    # "charging lien" AND "inherent power" within same opinion but relaxed
    if len(phrases) >= 2:
        # Use status:published to filter noise
        q = " AND ".join(f'"{p}"' for p in phrases) + ' AND status:published'
        queries.append({
            "query": q,
            "tier": "phrases_published",
            "description": "Phrases in published opinions only",
        })

    # Tier 5: Primary phrase + terms (more flexible than Tier 1)
    if phrases and terms:
        primary = phrases[0]
        term_str = " OR ".join(terms)
        q = f'"{primary}" AND ({term_str})'
        queries.append({
            "query": q,
            "tier": "primary_plus_terms",
            "description": f"\"{primary}\" + flexible terms",
        })

    # Tier 6: Each phrase independently (gather results from each)
    # This is handled in the search loop, not as a single query

    # Tier 7: Broad OR — quoted phrases keep it from being total noise
    if phrases:
        all_parts = [f'"{p}"' for p in phrases]
        q = " OR ".join(all_parts)
        queries.append({
            "query": q,
            "tier": "broad",
            "description": "Any phrase matches (OR)",
        })

    # If no phrases were found at all, try quoting 2-word chunks from the query
    if not phrases:
        words = decomposed["original"].split()
        if len(words) >= 2:
            # Try the full query as a phrase
            queries.insert(0, {
                "query": f'"{decomposed["original"]}"',
                "tier": "exact_raw",
                "description": f"Exact phrase: \"{decomposed['original']}\"",
            })
            # Try pairs of adjacent words
            pairs = [f'"{words[i]} {words[i+1]}"' for i in range(len(words)-1)]
            q = " AND ".join(pairs[:3])
            queries.append({
                "query": q,
                "tier": "word_pairs",
                "description": "Adjacent word pairs ANDed",
            })
        # Raw fallback
        queries.append({
            "query": decomposed["original"],
            "tier": "raw",
            "description": "Raw query (unmodified)",
        })

    return queries


# ── Deduplication ─────────────────────────────────────────────────

def _normalize_citation(cite: str) -> str:
    """Normalize a citation string for dedup comparison."""
    # Strip whitespace, lowercase, collapse spaces
    c = re.sub(r'\s+', ' ', cite.strip().lower())
    # Remove common variations
    c = c.replace(".", "").replace(",", "")
    return c


def _dedup_key(result: dict) -> str:
    """Generate a dedup key from a result. Prefer citation, fall back to case name + court."""
    cite = result.get("citation", "")
    if cite:
        return _normalize_citation(cite)
    # No citation — use case name + court as fallback
    name = result.get("case_name", "").lower().strip()
    court = result.get("court_id", result.get("court", "")).lower().strip()
    return f"{name}|{court}"


def deduplicate_results(results: list[dict]) -> list[dict]:
    """Remove duplicate results (same case appearing under different CL entries)."""
    seen = {}
    deduped = []
    for r in results:
        key = _dedup_key(r)
        if key and key not in seen:
            seen[key] = True
            deduped.append(r)
    return deduped


# ── Relevance Scoring ─────────────────────────────────────────────

def score_relevance(result: dict, phrases: list[str], terms: list[str]) -> float:
    """
    Score a search result for relevance before fetching full text.
    Uses case name, snippet, and cite count. Returns 0.0 - 1.0.

    Weighting:
      - Phrase match in snippet/name: 3 pts each (strongest signal)
      - Term match in snippet/name: 1 pt each
      - Cite count: up to 4 pts (a 140-cite case is almost certainly more
        useful than a 0-cite case — this was too low before)
    """
    text = (
        (result.get("case_name", "") + " " + result.get("snippet", ""))
        .lower()
    )

    score = 0.0
    max_score = 0.0

    # Phrase matches in snippet/name are worth the most
    for phrase in phrases:
        max_score += 3.0
        if phrase.lower() in text:
            score += 3.0

    # Individual term matches
    for term in terms:
        max_score += 1.0
        if term.lower() in text:
            score += 1.0

    # Cite count — weighted heavily. A well-cited opinion is almost always
    # more authoritative and useful than an uncited one.
    cite_count = result.get("cite_count", 0) or 0
    max_score += 4.0
    if cite_count >= 100:
        score += 4.0
    elif cite_count >= 50:
        score += 3.0
    elif cite_count >= 20:
        score += 2.0
    elif cite_count >= 5:
        score += 1.0
    # 0-4 cites = 0 points

    if max_score == 0:
        return 0.0
    return min(score / max_score, 1.0)


# ── Research functions ──────────────────────────────────────────────

def topic_research(client: CourtListenerClient, query: str,
                   jurisdiction: str, max_results: int = 15) -> dict:
    """
    Full topic research with tiered query refinement.

    Strategy:
      1. Decompose query into phrases + terms
      2. Run tiered queries from tight to broad, stopping when we have enough
      3. Search binding jurisdiction, SCOTUS, then broad
      4. Follow citation chains from top binding results
      5. Adverse authority search
      6. Deduplicate, score, and rank
    """
    search_log = []
    all_results = []
    seen_ids = set()

    # Decompose the query
    decomposed = decompose_query(query)
    tiered_queries = generate_tiered_queries(decomposed)
    search_log.append(
        f"Decomposed: phrases={decomposed['phrases']}, terms={decomposed['key_terms']}"
    )
    print(f"Query decomposition:")
    print(f"  Phrases: {decomposed['phrases']}")
    print(f"  Terms: {decomposed['key_terms']}")
    print(f"  Generated {len(tiered_queries)} tiered queries")

    def _add_results(results, binding, source):
        added = 0
        for r in results:
            rid = r.get("id")
            if rid and rid not in seen_ids:
                seen_ids.add(rid)
                r["_binding"] = binding if isinstance(binding, bool) else is_binding(
                    r.get("court_id", ""), jurisdiction)
                r["_source"] = source
                all_results.append(r)
                added += 1
        return added

    # Phase 1: Tiered search in binding jurisdiction
    # Run queries from tight to broad, accumulating results.
    # Stop escalating tiers once we have >= 5 binding results.
    binding_target = 5

    for tq in tiered_queries:
        q = tq["query"]
        tier = tq["tier"]

        # Search binding jurisdiction
        results = client.search_opinions(q, court=jurisdiction, limit=20)
        added = _add_results(results, True, f"tier_{tier}")
        search_log.append(f"[{tier}] '{q}' in {jurisdiction} -> {len(results)} hits, {added} new")
        print(f"  [{tier}] {jurisdiction}: {len(results)} hits, {added} new")

        # Also search SCOTUS
        if jurisdiction != "scotus":
            scotus = client.search_opinions(q, court="scotus", limit=5)
            s_added = _add_results(scotus, True, f"tier_{tier}_scotus")
            if s_added:
                search_log.append(f"[{tier}] SCOTUS -> {s_added} new")
                print(f"  [{tier}] SCOTUS: {s_added} new")

        binding_count = sum(1 for r in all_results if r.get("_binding"))
        if binding_count >= binding_target and tier not in ("broad", "raw"):
            print(f"  -> {binding_count} binding results, skipping broader tiers")
            search_log.append(f"Stopped at tier '{tier}' with {binding_count} binding results")
            break

    # Phase 2: Broader search for persuasive authority (use best tier that worked)
    best_tier = next((tq for tq in tiered_queries if tq["tier"] not in ("broad", "raw")), tiered_queries[0])
    broad_results = client.search_opinions(best_tier["query"], limit=20)
    new_persuasive = _add_results(broad_results, "auto", f"broad_{best_tier['tier']}")
    search_log.append(f"Broad (all courts, {best_tier['tier']}): +{new_persuasive} persuasive")
    print(f"  Broad search: +{new_persuasive} persuasive results")

    # Phase 3: Follow citation chains from top binding results
    binding_cases = [r for r in all_results if r.get("_binding")]
    chain_additions = 0
    for case in binding_cases[:3]:
        cluster_id = case.get("id")
        if not cluster_id:
            continue
        try:
            citing = client.citing_opinions(cluster_id, limit=10)
            chain_additions += _add_results(citing, "auto", f"chain_{cluster_id}")
        except Exception:
            pass

    if chain_additions:
        search_log.append(f"Citation chains from top 3 binding -> +{chain_additions}")
        print(f"  Citation chains: +{chain_additions}")

    # Phase 4: Adverse authority search
    adverse_queries = _generate_adverse_queries(decomposed)
    adverse_results = []
    for aq in adverse_queries:
        try:
            adv = client.search_opinions(aq, court=jurisdiction, limit=5)
            for r in adv:
                rid = r.get("id")
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    r["_binding"] = True
                    r["_source"] = "adverse_search"
                    r["_adverse_query"] = aq
                    all_results.append(r)
                    adverse_results.append(r)
        except Exception:
            pass
    if adverse_results:
        search_log.append(f"Adverse search: {len(adverse_queries)} queries -> {len(adverse_results)} results")
        print(f"  Adverse authority: {len(adverse_results)} potential")

    # Phase 5: Deduplicate, score, and rank
    all_results = deduplicate_results(all_results)
    dedup_count = len(seen_ids) - len(all_results)
    if dedup_count > 0:
        search_log.append(f"Deduplication removed {dedup_count} duplicates")

    # Score each result
    for r in all_results:
        r["_relevance_score"] = score_relevance(r, decomposed["phrases"], decomposed["key_terms"])

    # Sort: binding first, then by relevance score, then cite count
    all_results.sort(key=lambda r: (
        not r.get("_binding", False),
        -r.get("_relevance_score", 0),
        -(r.get("cite_count", 0) or 0),
    ))

    # Phase 6: Read opinion text for top results
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
            "relevance_score": round(r.get("_relevance_score", 0), 2),
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

    circuit_splits = _detect_circuit_splits(all_results, jurisdiction)

    binding_count = sum(1 for r in structured_results if r["binding"])
    confidence = "high" if binding_count >= 3 else "medium" if binding_count >= 1 else "low"
    confidence_notes = (
        f"{binding_count} binding authorities found. "
        f"{len(structured_results)} total results. "
    )
    if not binding_count:
        confidence_notes += "No binding authority — issue may be novel in this circuit."

    gaps = []
    if not binding_count:
        gaps.append(f"No binding authority found in {jurisdiction} — check Westlaw/Lexis")
    if len(all_results) < 3:
        gaps.append("Very few results — CL coverage may be limited for this topic")

    return {
        "query": query,
        "jurisdiction": jurisdiction,
        "research_type": "topic",
        "query_decomposition": decomposed,
        "tiers_used": [tq["tier"] for tq in tiered_queries],
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

    print(f"  Found: {opinion.case_name}")
    forward = []
    try:
        forward = client.citing_opinions(opinion.id, limit=20)
        print(f"  {len(forward)} forward citations")
    except Exception:
        pass

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
        "meta": {"timestamp": datetime.now().isoformat()},
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

        forward = []
        try:
            forward = client.citing_opinions(opinion.id, limit=30)
        except Exception:
            pass

        status = "good_law"
        notes = []

        if not forward:
            status = "caution"
            notes.append("No forward citations found — may be very recent or limited CL coverage")

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

def _generate_adverse_queries(decomposed: dict) -> list[str]:
    """Generate search queries that might find contrary authority using Solr syntax."""
    phrases = decomposed["phrases"]
    queries = []

    negation_pairs = {
        "grant": "denied",
        "granted": "denied",
        "allow": "denied",
        "enforce": "unenforceable",
        "valid": "invalid",
        "vacate": "uphold",
        "vacatur": "enforce",
        "liable": "not liable",
        "affirm": "reversed",
        "subordination": "priority",
    }

    # For each phrase, try pairing with negation terms
    for phrase in phrases:
        words = phrase.split()
        for word in words:
            if word in negation_pairs:
                opposite = negation_pairs[word]
                modified = phrase.replace(word, opposite)
                queries.append(f'"{modified}"')

    # If we have core phrases, search for them with denial language
    if phrases:
        core = phrases[0]  # most specific phrase
        queries.append(f'"{core}" AND (denied OR rejected OR unenforceable)')
        queries.append(f'"{core}" AND (upheld OR enforced OR valid)')

    # Fallback: use original terms with negation
    if not queries:
        original = decomposed["original"]
        queries.append(f'{original} AND denied')
        queries.append(f'{original} AND rejected')

    return queries[:4]  # cap at 4 adverse queries


def _extract_holding_and_quotes(text: str, query: str) -> tuple[str, list[dict]]:
    """
    Extract a holding statement and key quotes from opinion text.

    Scans up to 50k chars (expanded from 15k) because holdings often appear
    deep in the opinion (after facts, procedural history, analysis).
    """
    if not text:
        return "Full text not available in CourtListener", []

    # Scan more text — holdings often appear in the back half of the opinion
    text_sample = text[:50000]
    sentences = [s.strip() for s in text_sample.replace('\n', ' ').split('.') if s.strip()]

    holding_signals = [
        "we hold", "we conclude", "the court holds", "we therefore hold",
        "it is ordered", "we find that", "we affirm", "we reverse",
        "the court finds", "we grant", "we deny",
        "we vacate", "we remand", "judgment is",
    ]

    # First pass: look for strong holding language
    holding = ""
    for sent in sentences:
        sent_lower = sent.lower()
        if any(signal in sent_lower for signal in holding_signals):
            # Prefer holdings that are substantive (>60 chars), not just "We affirm"
            if len(sent.strip()) > 60:
                holding = sent.strip() + "."
                break
            elif not holding:
                holding = sent.strip() + "."
                # Don't break — keep looking for a meatier holding

    if not holding and sentences:
        holding = "(Holding not auto-extracted — review full text)"

    # Key quotes: find sentences with high query-term density
    query_terms = [t.lower() for t in query.split() if len(t) > 3]
    key_quotes = []
    scored_sents = []
    for sent in sentences:
        sent_lower = sent.lower()
        relevance = sum(1 for term in query_terms if term in sent_lower)
        if relevance >= 2 and len(sent) > 40:
            scored_sents.append((relevance, sent))

    # Sort by relevance and take top 3
    scored_sents.sort(key=lambda x: -x[0])
    for relevance, sent in scored_sents[:3]:
        key_quotes.append({
            "text": sent.strip()[:300] + ".",
            "pinpoint": "",
            "context": f"Contains {relevance} query terms",
        })

    return holding, key_quotes


def _detect_circuit_splits(results: list[dict], target_jurisdiction: str) -> list[dict]:
    """Simple circuit split detection."""
    main_circuits = set()
    adverse_circuits = set()

    for r in results:
        circuit = get_circuit_for_court(r.get("court_id", r.get("court", "")))
        if r.get("_source") == "adverse_search":
            adverse_circuits.add(circuit)
        else:
            main_circuits.add(circuit)

    if main_circuits and adverse_circuits:
        split_circuits = adverse_circuits - main_circuits
        if split_circuits:
            return [{
                "issue": "Potential circuit split — some circuits appear only in adverse results",
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
    """Main entry point."""
    client = CourtListenerClient()

    if shepardize_cites:
        result = shepardize(client, shepardize_cites)
    elif cite:
        result = citation_lookup(client, cite, jurisdiction)
    elif query:
        result = topic_research(client, query, jurisdiction, max_results)
    else:
        return {"error": "Provide a query, --cite, or --shepardize"}

    if save and LIBRARY_AVAILABLE:
        cat = category or "general"
        top = topic or query[:50].replace(" ", "_").lower()
        path = research_library.save_research(
            category=cat, topic=top, results=result,
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
                        help="Target jurisdiction (e.g., ca2, ca5, scotus)")
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
        print(f"\n{'=' * 60}")
        print(f"Research: {result.get('query', '')}")
        print(f"Type: {result.get('research_type', '')}")
        if result.get("jurisdiction"):
            print(f"Jurisdiction: {result['jurisdiction']}")
        print(f"Confidence: {result.get('confidence', 'unknown')}")
        if result.get("query_decomposition"):
            d = result["query_decomposition"]
            print(f"Phrases: {d.get('phrases', [])}")
            print(f"Terms: {d.get('key_terms', [])}")
        print(f"{'=' * 60}")

        for i, r in enumerate(result.get("results", []), 1):
            binding_tag = " [BINDING]" if r.get("binding") else ""
            status_tag = f" [{r['status'].upper()}]" if r.get("status") else ""
            score_tag = f" (rel={r['relevance_score']})" if r.get("relevance_score") is not None else ""
            print(f"\n{i}. {r.get('case_name', 'Unknown')}{binding_tag}{status_tag}{score_tag}")
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
