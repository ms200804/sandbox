# Case Research Agent

## Overview
An agent that queries public legal databases — primarily CourtListener — to do preliminary case research. Given a legal question, case citation, or topic, it finds relevant opinions, summarizes holdings, and pulls key quotes.

## Capabilities (Planned)

### Search & Retrieval
- **Opinion search:** Full-text search of federal and state court opinions via CourtListener API
- **Citation lookup:** Given a case cite, pull the full opinion text and metadata
- **Docket monitoring:** Watch specific case dockets for new filings (useful for active matters)
- **RECAP/PACER:** Access federal docket sheets and filings through CourtListener's RECAP archive

### Analysis
- **Summarize holdings:** For each relevant case, extract the holding and key reasoning
- **Quote extraction:** Pull the most citable passages with pinpoint citations
- **Distinguish/analogize:** Given your position, flag which cases help and which hurt
- **Shepardize (basic):** Check if opinions have been overruled or distinguished (via CL's citation network)

## CourtListener API

### Endpoints
- Base: `https://www.courtlistener.com/api/rest/v4/`
- **Opinions:** `/search/` — full-text search across opinions
- **Dockets:** `/dockets/` — docket-level metadata and filings
- **Courts:** `/courts/` — court metadata
- **Citations:** `/citations/` — citation relationships between opinions
- Auth: Free API token (register at courtlistener.com)
- Rate limit: 5,000 requests/day (free tier) — sufficient for research use

### Example Queries
```bash
# Search opinions for a topic in a specific court
curl "https://www.courtlistener.com/api/rest/v4/search/?q=trafficking+victims+protection+act&court=scotus&type=o" \
  -H "Authorization: Token YOUR_TOKEN"

# Get a specific opinion by ID
curl "https://www.courtlistener.com/api/rest/v4/opinions/12345/" \
  -H "Authorization: Token YOUR_TOKEN"

# Search dockets
curl "https://www.courtlistener.com/api/rest/v4/dockets/?case_name=smith+v+jones" \
  -H "Authorization: Token YOUR_TOKEN"
```

## Other Data Sources (Future)
- **Google Scholar** (case law) — no API, would need scraping; CL is better
- **Congress.gov** — legislative history for statutory interpretation
- **SEC EDGAR** — for securities matters (Sakhai, Mannechez, Cox)
- **PACER** direct — for filings not in RECAP (costs $0.10/page)

## Architecture
```
case-research/
├── README.md
├── cl_client.py          # CourtListener API client
├── researcher.py         # Main agent logic: search → filter → summarize
├── prompts/              # System prompts for the research agent
│   └── researcher.md
└── output/               # Research memos by topic/matter
```

## Design Questions
- [ ] Should output be structured (JSON) or prose (research memo markdown)?
- [ ] How to handle CL rate limits for large research sweeps?
- [ ] Integration with claude repo matter_summary.md files?
- [ ] Should it auto-Shepardize every case it cites?
