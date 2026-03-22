#!/usr/bin/env python3
"""
CourtListener API Client

Provides search, citation lookup, and docket monitoring
via the CourtListener REST API v4.

Requires: COURTLISTENER_TOKEN env var (free at courtlistener.com)
"""

import os
import re
from dataclasses import dataclass
from typing import Optional

import httpx

BASE_URL = "https://www.courtlistener.com/api/rest/v4"
SITE_URL = "https://www.courtlistener.com"

# Harvard CAP (Caselaw Access Project) — free, no token needed
CAP_BASE = "https://api.case.law/v1"


@dataclass
class Opinion:
    id: int
    case_name: str
    court: str
    date_filed: str
    citation: str
    text: str
    url: str


@dataclass
class Docket:
    id: int
    case_name: str
    court: str
    docket_number: str
    date_filed: str
    entries: list


class CourtListenerClient:
    """Client for CourtListener REST API v4."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("COURTLISTENER_TOKEN")
        if not self.token:
            raise ValueError("Set COURTLISTENER_TOKEN env var or pass token to constructor")
        self.client = httpx.Client(
            headers={"Authorization": f"Token {self.token}"},
            timeout=30.0,
        )

    def _get(self, url: str, params: dict | None = None) -> dict:
        """Make a GET request and return JSON. Accepts full URLs or paths."""
        if url.startswith("http"):
            resp = self.client.get(url, params=params)
        else:
            resp = self.client.get(f"{BASE_URL}{url}", params=params)
        resp.raise_for_status()
        return resp.json()

    def search_opinions(self, query: str, court: Optional[str] = None,
                        date_after: Optional[str] = None, limit: int = 20) -> list[dict]:
        """Full-text search across opinions."""
        params = {
            "q": query,
            "type": "o",
            "order_by": "score desc",
        }
        if court:
            params["court"] = court
        if date_after:
            params["filed_after"] = date_after

        data = self._get(f"{BASE_URL}/search/", params=params)

        results = data.get("results", [])[:limit]
        out = []
        for r in results:
            # Extract citation — it's a list in search results
            cites = r.get("citation", [])
            cite_str = cites[0] if isinstance(cites, list) and cites else str(cites) if cites else ""

            # Get opinion text snippet from the nested opinions array
            snippet = r.get("snippet", "")
            opinions = r.get("opinions", [])
            opinion_id = opinions[0].get("id") if opinions else None

            out.append({
                "id": r.get("cluster_id"),
                "opinion_id": opinion_id,
                "case_name": r.get("caseName", ""),
                "court": r.get("court", ""),
                "court_id": r.get("court_id", ""),
                "date_filed": r.get("dateFiled", ""),
                "citation": cite_str,
                "cite_count": r.get("citeCount", 0),
                "snippet": snippet,
                "judge": r.get("judge", ""),
                "url": f"{SITE_URL}{r.get('absolute_url', '')}",
            })
        return out

    def get_opinion_text(self, opinion_id: int) -> str:
        """Fetch the full text of a single opinion by its opinion ID."""
        try:
            data = self._get(f"{BASE_URL}/opinions/{opinion_id}/")
            # Try different text fields in order of preference
            text = (data.get("plain_text") or "").strip()
            if not text:
                html = data.get("html_with_citations") or data.get("html") or ""
                # Basic HTML stripping
                text = re.sub(r'<[^>]+>', '', html).strip()
            return text
        except Exception:
            return ""

    def get_opinion(self, cluster_id: int) -> Opinion:
        """Fetch a single opinion by its cluster ID."""
        cluster = self._get(f"{BASE_URL}/clusters/{cluster_id}/")

        # Get opinion text
        text = ""
        sub_opinions = cluster.get("sub_opinions", [])
        if sub_opinions:
            sub_url = sub_opinions[0]
            if isinstance(sub_url, str):
                try:
                    sub_data = self._get(sub_url)
                    text = (sub_data.get("plain_text") or "").strip()
                    if not text:
                        html = sub_data.get("html_with_citations") or sub_data.get("html") or ""
                        text = re.sub(r'<[^>]+>', '', html).strip()
                except Exception:
                    pass

        citations = cluster.get("citations", [])
        cite_str = citations[0].get("cite", "") if citations else ""

        return Opinion(
            id=cluster["id"],
            case_name=cluster.get("case_name", ""),
            court=cluster.get("court", ""),
            date_filed=cluster.get("date_filed", ""),
            citation=cite_str,
            text=text,
            url=f"{SITE_URL}{cluster.get('absolute_url', '')}",
        )

    def citation_lookup(self, citation: str) -> Optional[Opinion]:
        """Look up an opinion by its citation string."""
        # Search with the citation
        results = self.search_opinions(f'citation:("{citation}")', limit=5)
        if not results:
            results = self.search_opinions(citation, limit=5)

        if not results:
            return None

        best = results[0]
        cluster_id = best.get("id")
        opinion_id = best.get("opinion_id")

        # Try to get full text
        text = ""
        if opinion_id:
            text = self.get_opinion_text(opinion_id)

        # If no text from opinion endpoint, try cluster
        if not text and cluster_id:
            try:
                full = self.get_opinion(cluster_id)
                return full
            except Exception:
                pass

        return Opinion(
            id=cluster_id or 0,
            case_name=best.get("case_name", ""),
            court=best.get("court", ""),
            date_filed=best.get("date_filed", ""),
            citation=best.get("citation", citation),
            text=text,
            url=best.get("url", ""),
        )

    def citing_opinions(self, cluster_id: int, limit: int = 50) -> list[dict]:
        """Find opinions that cite a given opinion (forward citations)."""
        data = self._get(
            f"{BASE_URL}/search/",
            params={
                "q": f"cites:({cluster_id})",
                "type": "o",
                "order_by": "score desc",
            },
        )
        results = data.get("results", [])[:limit]
        return [
            {
                "id": r.get("cluster_id"),
                "case_name": r.get("caseName", ""),
                "court": r.get("court", ""),
                "date_filed": r.get("dateFiled", ""),
                "citation": (r.get("citation") or [""])[0] if isinstance(r.get("citation"), list) else str(r.get("citation", "")),
            }
            for r in results
        ]

    def cited_by(self, cluster_id: int, limit: int = 50) -> list[dict]:
        """Find opinions cited BY a given opinion (backward citations)."""
        try:
            cluster = self._get(f"{BASE_URL}/clusters/{cluster_id}/")
            sub_opinions = cluster.get("sub_opinions", [])
            if not sub_opinions:
                return []

            sub_url = sub_opinions[0]
            if isinstance(sub_url, str):
                sub_data = self._get(sub_url)
                cited_ids = sub_data.get("opinions_cited", [])
                results = []
                for cited_url in cited_ids[:limit]:
                    if isinstance(cited_url, str):
                        try:
                            cited_data = self._get(cited_url)
                            cluster_url = cited_data.get("cluster", "")
                            if isinstance(cluster_url, str):
                                cl_data = self._get(cluster_url)
                                citations = cl_data.get("citations", [])
                                cite_str = citations[0].get("cite", "") if citations else ""
                                results.append({
                                    "id": cl_data["id"],
                                    "case_name": cl_data.get("case_name", ""),
                                    "court": cl_data.get("court", ""),
                                    "date_filed": cl_data.get("date_filed", ""),
                                    "citation": cite_str,
                                })
                        except Exception:
                            continue
                return results
        except Exception:
            pass
        return []

    def search_dockets(self, case_name: Optional[str] = None,
                       docket_number: Optional[str] = None,
                       court: Optional[str] = None, limit: int = 20) -> list[dict]:
        """Search dockets by case name or number."""
        params = {}
        if case_name:
            params["case_name__icontains"] = case_name
        if docket_number:
            params["docket_number"] = docket_number
        if court:
            params["court__id"] = court
        params["order_by"] = "-date_filed"

        data = self._get(f"{BASE_URL}/dockets/", params=params)
        results = data.get("results", [])[:limit]
        return [
            {
                "id": r.get("id"),
                "case_name": r.get("case_name", ""),
                "court": r.get("court", ""),
                "docket_number": r.get("docket_number", ""),
                "date_filed": r.get("date_filed", ""),
            }
            for r in results
        ]

    def get_docket(self, docket_id: int) -> Docket:
        """Fetch a single docket with entries."""
        data = self._get(f"{BASE_URL}/dockets/{docket_id}/")
        entries = []
        entries_url = data.get("docket_entries", "")
        if entries_url and isinstance(entries_url, str):
            try:
                entries_data = self._get(entries_url)
                entries = entries_data.get("results", [])
            except Exception:
                pass

        return Docket(
            id=data["id"],
            case_name=data.get("case_name", ""),
            court=data.get("court", ""),
            docket_number=data.get("docket_number", ""),
            date_filed=data.get("date_filed", ""),
            entries=[
                {
                    "entry_number": e.get("entry_number"),
                    "date_filed": e.get("date_filed", ""),
                    "description": e.get("description", ""),
                }
                for e in entries[:50]
            ],
        )


# ── Harvard CAP (Caselaw Access Project) ──────────────────────────

class HarvardCAPClient:
    """Client for Harvard Caselaw Access Project API. No token needed."""

    def __init__(self):
        self.client = httpx.Client(timeout=30.0)

    def search(self, query: str, jurisdiction: Optional[str] = None,
               decision_date_min: Optional[str] = None,
               limit: int = 10) -> list[dict]:
        """Search cases in Harvard CAP."""
        params = {
            "search": query,
            "page_size": min(limit, 100),
            "ordering": "-relevance",
            "full_case": "true",
        }
        if jurisdiction:
            params["jurisdiction"] = jurisdiction
        if decision_date_min:
            params["decision_date_min"] = decision_date_min

        try:
            resp = self.client.get(f"{CAP_BASE}/cases/", params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        results = data.get("results", [])
        out = []
        for r in results:
            # Get citations
            cites = r.get("citations", [])
            cite_str = cites[0].get("cite", "") if cites else ""

            # Get opinion text
            casebody = r.get("casebody", {})
            if isinstance(casebody, dict):
                text = casebody.get("data", {}).get("opinions", [{}])[0].get("text", "") if isinstance(casebody.get("data"), dict) else ""
            else:
                text = ""

            out.append({
                "id": r.get("id"),
                "case_name": r.get("name", r.get("name_abbreviation", "")),
                "citation": cite_str,
                "court": r.get("court", {}).get("name", "") if isinstance(r.get("court"), dict) else "",
                "date_filed": r.get("decision_date", ""),
                "url": r.get("frontend_url", ""),
                "text": text[:5000] if text else "",
                "source": "harvard_cap",
            })
        return out

    def lookup_citation(self, citation: str) -> Optional[dict]:
        """Look up a case by citation string."""
        params = {
            "cite": citation,
            "full_case": "true",
        }
        try:
            resp = self.client.get(f"{CAP_BASE}/cases/", params=params)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                return None

            r = results[0]
            cites = r.get("citations", [])
            cite_str = cites[0].get("cite", "") if cites else citation

            casebody = r.get("casebody", {})
            text = ""
            if isinstance(casebody, dict):
                opinions = casebody.get("data", {}).get("opinions", []) if isinstance(casebody.get("data"), dict) else []
                if opinions:
                    text = opinions[0].get("text", "")

            return {
                "id": r.get("id"),
                "case_name": r.get("name", r.get("name_abbreviation", "")),
                "citation": cite_str,
                "court": r.get("court", {}).get("name", "") if isinstance(r.get("court"), dict) else "",
                "date_filed": r.get("decision_date", ""),
                "url": r.get("frontend_url", ""),
                "text": text,
                "source": "harvard_cap",
            }
        except Exception:
            return None


if __name__ == "__main__":
    # Test CL
    try:
        cl = CourtListenerClient()
        print("=== CourtListener ===")
        results = cl.search_opinions("Arbor Hill attorney fees lodestar", court="ca2", limit=2)
        for r in results:
            print(f"  {r['citation']} — {r['case_name']} (id={r['id']})")
            if r.get("opinion_id"):
                text = cl.get_opinion_text(r["opinion_id"])
                print(f"    Text: {text[:200]}..." if text else "    Text: (none)")
    except ValueError as e:
        print(f"CL setup needed: {e}")

    # Test Harvard CAP
    print("\n=== Harvard CAP ===")
    cap = HarvardCAPClient()
    results = cap.search("Arbor Hill attorney fees lodestar", limit=2)
    for r in results:
        print(f"  {r['citation']} — {r['case_name']}")
        print(f"    Text: {r['text'][:200]}..." if r.get("text") else "    Text: (none)")
