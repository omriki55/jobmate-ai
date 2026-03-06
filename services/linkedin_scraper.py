"""
LinkedIn Profile Scraper — extracts profile data from public LinkedIn URLs.

Fetches the LinkedIn profile page server-side with realistic browser headers,
then parses the HTML for structured data (JSON-LD, meta tags, noscript sections).
Falls back gracefully when LinkedIn blocks or limits the request.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 15

# Realistic browser headers
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
}


class LinkedInScrapeError(Exception):
    """Raised when scraping fails or returns insufficient data."""
    pass


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _normalize_linkedin_url(url: str) -> str:
    """Ensure URL is a valid LinkedIn profile URL."""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    # Strip trailing slashes and query params
    url = url.split("?")[0].rstrip("/")
    if "linkedin.com/in/" not in url:
        raise LinkedInScrapeError(f"Not a valid LinkedIn profile URL: {url}")
    return url


# ---------------------------------------------------------------------------
# HTML extraction layers
# ---------------------------------------------------------------------------

def _extract_json_ld(soup: BeautifulSoup) -> dict[str, Any]:
    """Extract structured data from JSON-LD script tags."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict) and data.get("@type") == "Person":
                return data
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "Person":
                        return item
        except (json.JSONDecodeError, TypeError):
            continue
    return {}


def _extract_meta(soup: BeautifulSoup) -> dict[str, str]:
    """Extract profile info from meta tags."""
    meta: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        prop = tag.get("property", "") or tag.get("name", "")
        content = tag.get("content", "")
        if prop in ("og:title", "title"):
            meta["title"] = content
        elif prop in ("og:description", "description"):
            meta["description"] = content
    if not meta.get("title") and soup.title:
        meta["title"] = soup.title.string or ""
    return meta


def _extract_noscript(soup: BeautifulSoup) -> str:
    """Extract text from noscript sections (LinkedIn renders profile for SEO)."""
    texts = []
    for ns in soup.find_all("noscript"):
        inner = BeautifulSoup(ns.decode_contents(), "html.parser")
        text = inner.get_text(separator="\n", strip=True)
        if text and len(text) > 50:
            texts.append(text)
    return "\n\n".join(texts)


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------

def _build_profile_text(json_ld: dict, meta: dict, noscript_text: str) -> str:
    """Combine extracted data into a readable profile text for the optimizer."""
    parts: list[str] = []

    # Name
    name = json_ld.get("name") or ""
    if not name and meta.get("title"):
        name = meta["title"].split(" - ")[0].split(" | ")[0].strip()
    if name:
        parts.append(f"Name: {name}")

    # Headline / Job Title
    headline = json_ld.get("jobTitle") or ""
    if not headline and meta.get("title") and " - " in meta["title"]:
        headline = meta["title"].split(" - ", 1)[1].split(" | ")[0].strip()
    if headline:
        parts.append(f"Headline: {headline}")

    # Location
    location = ""
    addr = json_ld.get("address")
    if isinstance(addr, dict):
        location = addr.get("addressLocality", "") or addr.get("name", "")
    elif isinstance(addr, str):
        location = addr
    if location:
        parts.append(f"Location: {location}")

    # About / Description
    desc = json_ld.get("description") or meta.get("description") or ""
    if desc:
        parts.append(f"\n## About\n{desc}")

    # Work experience from JSON-LD
    work = json_ld.get("worksFor")
    if work:
        parts.append("\n## Experience")
        if isinstance(work, list):
            for w in work:
                org = w.get("name", "") if isinstance(w, dict) else str(w)
                if org:
                    parts.append(f"- {org}")
        elif isinstance(work, dict):
            parts.append(f"- {work.get('name', '')}")

    # Education from JSON-LD
    alumni = json_ld.get("alumniOf")
    if alumni:
        parts.append("\n## Education")
        if isinstance(alumni, list):
            for a in alumni:
                org = a.get("name", "") if isinstance(a, dict) else str(a)
                if org:
                    parts.append(f"- {org}")
        elif isinstance(alumni, dict):
            parts.append(f"- {alumni.get('name', '')}")

    # Skills from JSON-LD
    skills = json_ld.get("knowsAbout") or json_ld.get("skills")
    if skills:
        parts.append("\n## Skills")
        if isinstance(skills, list):
            parts.append(", ".join(str(s) for s in skills))
        else:
            parts.append(str(skills))

    # Noscript content (often richest text)
    if noscript_text and len(noscript_text) > 100:
        parts.append(f"\n## Additional Profile Content\n{noscript_text}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def scrape_linkedin_profile(linkedin_url: str) -> str:
    """
    Fetch a LinkedIn profile page and extract available profile text.

    Returns structured text with profile sections.
    Raises LinkedInScrapeError if fetching fails or no data is found.
    """
    url = _normalize_linkedin_url(linkedin_url)
    logger.info("Scraping LinkedIn profile: %s", url)

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers=_HEADERS,
            timeout=HTTP_TIMEOUT,
        ) as client:
            response = await client.get(url)

        if response.status_code == 999:
            raise LinkedInScrapeError(
                "LinkedIn blocked the request (status 999)."
            )

        if response.status_code != 200:
            raise LinkedInScrapeError(
                f"LinkedIn returned status {response.status_code}"
            )

        html = response.text
        if len(html) < 500:
            raise LinkedInScrapeError("Response too short — likely blocked")

    except httpx.HTTPError as exc:
        raise LinkedInScrapeError(f"HTTP error: {exc}") from exc

    soup = BeautifulSoup(html, "html.parser")

    json_ld = _extract_json_ld(soup)
    meta = _extract_meta(soup)
    noscript_text = _extract_noscript(soup)

    profile_text = _build_profile_text(json_ld, meta, noscript_text)

    if len(profile_text.strip()) < 50:
        raise LinkedInScrapeError(
            "Could not extract meaningful profile data. "
            "The profile may be private or LinkedIn blocked the request."
        )

    logger.info(
        "Extracted %d chars (JSON-LD: %s, meta: %d keys, noscript: %d chars)",
        len(profile_text),
        "yes" if json_ld else "no",
        len(meta),
        len(noscript_text),
    )

    return profile_text
