# Case Research Agent

## Overview
An agent that queries public legal databases — primarily CourtListener — to do preliminary case research. Given a legal question, case citation, or topic, it iteratively searches for relevant opinions, summarizes holdings, pulls key quotes, and produces structured JSON output.

Built to handle the bulk of what a first-year associate would do with Westlaw — getting the main cases, especially appellate decisions, and organizing them by relevance and jurisdiction.

## Capabilities

### Research Modes

| Mode | Input | Output |
|---|---|---|
| **Topic Research** | Legal question + jurisdiction | Ranked cases with holdings, key quotes, adverse authority, circuit splits |
| **Citation Lookup** | Case citation (e.g., "546 U.S. 440") | Full opinion text, metadata, forward/backward citations |
| **Shepardize** | List of citations | Treatment status for each (good law / caution / bad law) |
| **Docket Monitor** | Case number + court | New filings since last check, significant entries flagged |

### Key Features
- **Iterative search refinement:** First query too broad → narrows automatically; too narrow → broadens
- **Citation chain following:** Finds a good case → checks what it cites and what cites it
- **Jurisdiction awareness:** Distinguishes binding vs. persuasive authority for the target circuit
- **Adverse authority detection:** Actively searches for cases that cut against the position
- **Circuit split identification:** Flags when circuits disagree on the issue
- **Honest coverage gaps:** Says when CL doesn't have what you need and suggests Westlaw/Lexis

## Output Format (Structured JSON)

All output is structured JSON — designed to pipe into the adversarial sim, render into memos, or filter/merge across multiple searches.

```json
{
  "query": "TVPA private right of action",
  "jurisdiction": "ca9",
  "results": [
    {
      "case_name": "Doe v. Smith",
      "citation": "--- F.4th ---",
      "court": "ca9",
      "date_filed": "2025-09-15",
      "binding": true,
      "holding": "One-sentence holding",
      "key_quotes": [{"text": "...", "pinpoint": "at *4"}],
      "relevance": "supports",
      "negative_treatment": null
    }
  ],
  "adverse_authority": [...],
  "circuit_splits": [...],
  "confidence": "high",
  "gaps": ["CL coverage of X is limited"]
}
```

## CourtListener API

### Coverage
- **Federal appellate opinions:** Excellent. This is CL's strength.
- **SCOTUS:** Complete.
- **Federal district courts:** Decent but not comprehensive — many opinions aren't published.
- **State courts:** Spotty. Varies significantly by state.
- **PACER/RECAP dockets:** Only covers dockets someone has already pulled through RECAP.

### API Details
- Base: `https://www.courtlistener.com/api/rest/v4/`
- Auth: Free API token (register at courtlistener.com)
- Rate limit: 5,000 requests/day (free tier)
- Key endpoints: `/search/` (opinions), `/dockets/`, `/citations/`, `/courts/`

## Research Library

Results are saved to a persistent, indexed library so you don't re-research
the same topics. Categories are created on the fly.

```
research/
├── index.json                          # topic → file map with metadata + staleness
└── topics/
    ├── tvpa/
    │   ├── private_right_of_action.json
    │   └── fee_shifting_lodestar.json
    ├── arbitration/
    │   ├── unconscionability.json
    │   └── separability_doctrine.json
    └── [new categories created automatically]
```

- Bot checks library BEFORE hitting CourtListener
- Stale topics (>90 days) flagged for refresh
- Library is git-tracked — persists across clones
- Adversarial sim agents can draw from library for authorities

## Data Sources

| Source | Use for | Coverage |
|---|---|---|
| **CourtListener** | Primary — current opinions, docket monitoring, citation chains | Excellent federal appellate; decent district; spotty state |
| **Harvard CAP** | Historical precedent through 2018 | 6.7M cases, 360 years, published-in-print only |
| **PACER** | Fallback for dockets not in RECAP | $0.10/page, comprehensive |

**Important:** CL's citation network shows which cases cite which. It does NOT provide treatment status (reversed, distinguished, etc.) like Shepard's or KeyCite. Our "shepardize" tool is forward citation analysis — useful but not a Westlaw/Lexis replacement for definitive treatment.

## Architecture
```
case-research/
├── README.md
├── cl_client.py          # CourtListener API client (httpx)
├── library.py            # Persistent research library with indexing
├── researcher.py         # Agent logic: search → filter → analyze → output
├── prompts/
│   └── researcher.md     # System prompt for the research agent
├── research/
│   ├── index.json        # Library index
│   └── topics/           # Saved research by category/topic
└── output/               # One-off research results
```

## Integration with Adversarial Sim

**Level 1 (manual):** Run research → copy key cases into adversarial sim scenario as "Key Authorities."

**Level 2 (planned):** Phase 1 agents in the adversarial sim get direct tool access to `search_cases`. Hostile OC independently finds counter-authorities. Appellate Panel verifies cited cases actually say what the advocate claims.

**Slack workflow:** Research in `#research` → results auto-available for sim runs in `#adversarial`. The Slack bot chains tools across projects using thread context.

## Setup
1. Register at courtlistener.com and get an API token
2. Set `COURTLISTENER_TOKEN` in `.env`
3. `uv pip install httpx`
4. Test: `python cl_client.py`

## What This Won't Replace
- Westlaw/Lexis for comprehensive state court coverage
- Westlaw KeyCite / Lexis Shepard's for definitive citation treatment
- PACER for dockets not in RECAP
- Human judgment on which cases actually matter for your argument

CL is excellent for federal appellate research — the bread and butter of most motion practice. For everything else, it's a starting point that tells you where to look next.
