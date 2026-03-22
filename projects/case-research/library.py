#!/usr/bin/env python3
from __future__ import annotations
"""
Research Library — persistent, indexed case law storage.

Saves research results by topic so they don't need to be re-researched
every time. Auto-creates new categories on the fly. Checks freshness
and flags stale topics for refresh.

Structure:
    research/
    ├── index.json              # topic → file map with metadata
    └── topics/
        ├── tvpa/
        │   ├── private_right_of_action.json
        │   └── fee_shifting_lodestar.json
        ├── arbitration/
        │   └── unconscionability.json
        └── ...
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

RESEARCH_DIR = Path(__file__).parent / "research"
TOPICS_DIR = RESEARCH_DIR / "topics"
INDEX_PATH = RESEARCH_DIR / "index.json"

DEFAULT_STALE_DAYS = 90


def _load_index() -> dict:
    """Load the topic index."""
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text())
    return {"description": "Research library index", "stale_after_days": DEFAULT_STALE_DAYS, "topics": {}}


def _save_index(index: dict):
    """Save the topic index."""
    INDEX_PATH.write_text(json.dumps(index, indent=2) + "\n")


def slugify(text: str) -> str:
    """Convert a topic name to a filesystem-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '_', slug)
    slug = slug.strip('_')
    return slug


def _topic_key(category: str, topic: str) -> str:
    """Create a unique key for a category/topic pair."""
    return f"{slugify(category)}/{slugify(topic)}"


def save_research(category: str, topic: str, results: dict,
                  query: str = "", jurisdiction: str = "",
                  confidence: str = "medium",
                  matters: list[str] | None = None) -> Path:
    """
    Save research results to the library.

    Args:
        category: Broad area (e.g., "tvpa", "arbitration", "securities")
        topic: Specific topic (e.g., "private_right_of_action", "unconscionability")
        results: Structured JSON research results
        query: The original search query
        jurisdiction: Target jurisdiction
        confidence: "high", "medium", or "low" — based on source quality
        matters: Optional list of matter tags (e.g., ["hubbard_goedinghaus_tvpa"])

    Returns:
        Path to the saved file
    """
    cat_slug = slugify(category)
    topic_slug = slugify(topic)
    topic_dir = TOPICS_DIR / cat_slug
    topic_dir.mkdir(parents=True, exist_ok=True)

    # Wrap results with library metadata
    entry = {
        "category": category,
        "topic": topic,
        "query": query,
        "jurisdiction": jurisdiction,
        "confidence": confidence,
        "matters": matters or [],
        "saved_at": datetime.now().isoformat(),
        "result_count": len(results.get("results", [])),
        "results": results,
    }

    file_path = topic_dir / f"{topic_slug}.json"
    file_path.write_text(json.dumps(entry, indent=2) + "\n")

    # Update index
    index = _load_index()
    key = _topic_key(category, topic)
    index["topics"][key] = {
        "category": category,
        "topic": topic,
        "file": f"topics/{cat_slug}/{topic_slug}.json",
        "query": query,
        "jurisdiction": jurisdiction,
        "confidence": confidence,
        "matters": matters or [],
        "saved_at": entry["saved_at"],
        "result_count": entry["result_count"],
    }
    _save_index(index)

    return file_path


def lookup(category: str, topic: str) -> dict | None:
    """
    Look up a topic in the library. Returns the stored research
    results if found, None otherwise.
    """
    key = _topic_key(category, topic)
    index = _load_index()
    entry = index.get("topics", {}).get(key)
    if not entry:
        return None

    file_path = RESEARCH_DIR / entry["file"]
    if not file_path.exists():
        return None

    return json.loads(file_path.read_text())


def is_stale(category: str, topic: str) -> bool:
    """Check if a topic's research is stale (older than threshold)."""
    key = _topic_key(category, topic)
    index = _load_index()
    entry = index.get("topics", {}).get(key)
    if not entry:
        return True  # doesn't exist = stale

    stale_days = index.get("stale_after_days", DEFAULT_STALE_DAYS)
    saved_at = datetime.fromisoformat(entry["saved_at"])
    return datetime.now() - saved_at > timedelta(days=stale_days)


def search_library(query: str) -> list[dict]:
    """
    Search the library index for topics matching a query string.
    Matches against category, topic, and original query fields.
    Returns matching index entries.
    """
    index = _load_index()
    query_lower = query.lower()
    matches = []

    for key, entry in index.get("topics", {}).items():
        searchable = f"{entry['category']} {entry['topic']} {entry.get('query', '')}".lower()
        if query_lower in searchable:
            entry_copy = dict(entry)
            entry_copy["key"] = key
            entry_copy["stale"] = is_stale(entry["category"], entry["topic"])
            matches.append(entry_copy)

    return matches


def list_categories() -> dict[str, list[str]]:
    """List all categories and their topics."""
    index = _load_index()
    categories: dict[str, list[str]] = {}

    for entry in index.get("topics", {}).values():
        cat = entry["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(entry["topic"])

    return categories


def list_stale() -> list[dict]:
    """List all stale topics that should be refreshed."""
    index = _load_index()
    stale = []

    for key, entry in index.get("topics", {}).items():
        if is_stale(entry["category"], entry["topic"]):
            entry_copy = dict(entry)
            entry_copy["key"] = key
            stale.append(entry_copy)

    return stale


def update_confidence(category: str, topic: str, confidence: str) -> bool:
    """Update the confidence level of a topic."""
    key = _topic_key(category, topic)
    index = _load_index()
    entry = index.get("topics", {}).get(key)
    if not entry:
        return False

    entry["confidence"] = confidence
    _save_index(index)

    # Also update the file
    file_path = RESEARCH_DIR / entry["file"]
    if file_path.exists():
        data = json.loads(file_path.read_text())
        data["confidence"] = confidence
        file_path.write_text(json.dumps(data, indent=2) + "\n")

    return True


def add_matter(category: str, topic: str, matter: str) -> bool:
    """Tag a topic with a matter identifier."""
    key = _topic_key(category, topic)
    index = _load_index()
    entry = index.get("topics", {}).get(key)
    if not entry:
        return False

    matters = entry.get("matters", [])
    if matter not in matters:
        matters.append(matter)
        entry["matters"] = matters
        _save_index(index)

        file_path = RESEARCH_DIR / entry["file"]
        if file_path.exists():
            data = json.loads(file_path.read_text())
            data["matters"] = matters
            file_path.write_text(json.dumps(data, indent=2) + "\n")

    return True


def search_by_matter(matter: str) -> list[dict]:
    """Find all research tagged to a specific matter."""
    index = _load_index()
    matches = []
    for key, entry in index.get("topics", {}).items():
        if matter in entry.get("matters", []):
            entry_copy = dict(entry)
            entry_copy["key"] = key
            matches.append(entry_copy)
    return matches


def delete_topic(category: str, topic: str) -> bool:
    """Remove a topic from the library."""
    key = _topic_key(category, topic)
    index = _load_index()

    entry = index.get("topics", {}).get(key)
    if not entry:
        return False

    # Delete file
    file_path = RESEARCH_DIR / entry["file"]
    if file_path.exists():
        file_path.unlink()

    # Clean up empty category directory
    cat_dir = file_path.parent
    if cat_dir.exists() and not any(cat_dir.iterdir()):
        cat_dir.rmdir()

    # Remove from index
    del index["topics"][key]
    _save_index(index)

    return True


if __name__ == "__main__":
    # Quick self-test
    print("Library location:", RESEARCH_DIR)
    print("Categories:", list_categories())
    print("Stale topics:", len(list_stale()))
