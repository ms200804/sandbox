#!/usr/bin/env python3
"""
CourtListener API Client (stub)

Provides search, citation lookup, and docket monitoring
via the CourtListener REST API v4.

Requires: COURTLISTENER_TOKEN env var (free at courtlistener.com)
"""

import json
import os
import sys
from dataclasses import dataclass
from typing import Optional

# TODO: implement with httpx or requests
# For now, this is a structural stub showing the planned interface


BASE_URL = "https://www.courtlistener.com/api/rest/v4"


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
        self.headers = {"Authorization": f"Token {self.token}"}

    def search_opinions(self, query: str, court: Optional[str] = None,
                        date_after: Optional[str] = None, limit: int = 20) -> list[dict]:
        """
        Full-text search across opinions.

        Args:
            query: Search terms
            court: Court filter (e.g., "scotus", "ca2", "nysd")
            date_after: ISO date, only opinions after this date
            limit: Max results
        """
        # TODO: implement
        raise NotImplementedError

    def get_opinion(self, opinion_id: int) -> Opinion:
        """Fetch a single opinion by ID."""
        # TODO: implement
        raise NotImplementedError

    def search_dockets(self, case_name: Optional[str] = None,
                       docket_number: Optional[str] = None,
                       court: Optional[str] = None, limit: int = 20) -> list[dict]:
        """Search dockets by case name or number."""
        # TODO: implement
        raise NotImplementedError

    def get_docket(self, docket_id: int) -> Docket:
        """Fetch a single docket with entries."""
        # TODO: implement
        raise NotImplementedError

    def citation_lookup(self, citation: str) -> Optional[Opinion]:
        """
        Look up an opinion by its citation string.
        E.g., "546 U.S. 440" or "68 F.3d 554"
        """
        # TODO: implement — may need to parse citation format
        raise NotImplementedError

    def citing_opinions(self, opinion_id: int, limit: int = 50) -> list[dict]:
        """Find opinions that cite a given opinion (forward citations)."""
        # TODO: implement via /citations/ endpoint
        raise NotImplementedError

    def cited_by(self, opinion_id: int, limit: int = 50) -> list[dict]:
        """Find opinions cited BY a given opinion (backward citations)."""
        # TODO: implement
        raise NotImplementedError


if __name__ == "__main__":
    # Quick test
    try:
        client = CourtListenerClient()
        print("Client initialized. API methods are stubs — implement with httpx.")
    except ValueError as e:
        print(f"Setup needed: {e}")
