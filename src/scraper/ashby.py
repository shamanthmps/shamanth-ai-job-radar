"""
Ashby job board scraper — covers modern tech companies using Ashby ATS.

Ashby provides a public, unauthenticated JSON API (same pattern as Greenhouse/Lever):
  GET https://jobs.ashbyhq.com/api/non-user-facing/posting-board/{company-slug}

Response:
  {
    "jobPostings": [
      {
        "id": "...", "title": "...", "department": "...",
        "locationName": "...", "employmentType": "...",
        "descriptionHtml": "...", "isRemote": bool,
        "publishedAt": "ISO datetime"
      }
    ]
  }

Target: TPM/PM openings at global product companies with India presence.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from uuid import uuid4

import httpx

from ..models.job_posting import JobPosting
from .base import BaseScraper

logger = logging.getLogger("scraper.ashby")

# Companies using Ashby ATS — slug matches their Ashby posting board URL
# https://jobs.ashbyhq.com/{slug}
ASHBY_COMPANIES: dict[str, str] = {
    "samsara": "Samsara",
    "verkada": "Verkada",
    "persona": "Persona",
    "retool": "Retool",
    "hex": "Hex",
    "brex": "Brex",
    "ramp": "Ramp",
    "modern-treasury": "Modern Treasury",
    "prefect": "Prefect",
    "metronome": "Metronome",
    "watershed": "Watershed",
    "ashby": "Ashby",         # Ashby itself posts jobs on its own platform
    "sequoia-capital": "Sequoia Capital",
    "benchmark": "Benchmark",
    "mercury": "Mercury",
    "deel": "Deel",
    "rippling": "Rippling",
    "workos": "WorkOS",
    "turso": "Turso",
    "dbt-labs": "dbt Labs",
    "snorkel-ai": "Snorkel AI",
    "cohere": "Cohere",
    "weights-and-biases": "Weights & Biases",
    "modal": "Modal Labs",
}

ASHBY_API = "https://jobs.ashbyhq.com/api/non-user-facing/posting-board/{slug}"

# Keywords for TPM/PM filtering
TPM_KEYWORDS = {
    "technical program manager", "tpm", "staff tpm", "senior tpm",
    "program manager", "engineering program manager", "epm",
    "delivery manager", "technical delivery", "technology program",
}


class AshbyScraper(BaseScraper):
    """
    Scrapes Ashby-hosted job boards for TPM/PM roles.

    Follows the same pattern as the Greenhouse scraper (greenhouse.py).
    Public API, no auth required, returns structured JSON.
    """

    SOURCE = "ashby"

    HEADERS = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    def scrape(self) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        seen_hashes: set[str] = set()

        with httpx.Client(headers=self.HEADERS, timeout=20, follow_redirects=True) as client:
            for slug, company_name in ASHBY_COMPANIES.items():
                try:
                    batch = self._fetch_company(client, slug, company_name)
                    for job in batch:
                        h = self.compute_content_hash(
                            job.title, job.company_name, job.external_id or ""
                        )
                        if h not in seen_hashes:
                            seen_hashes.add(h)
                            job.content_hash = h
                            jobs.append(job)
                    time.sleep(0.8)
                except Exception as exc:
                    logger.warning("Ashby %s failed: %s", slug, exc)

        logger.info("Ashby: scraped %d TPM/PM jobs across %d companies", len(jobs), len(ASHBY_COMPANIES))
        return jobs

    def _fetch_company(
        self, client: httpx.Client, slug: str, company_name: str
    ) -> list[JobPosting]:
        """Fetch all open roles from a company's Ashby posting board."""
        url = ASHBY_API.format(slug=slug)
        response = client.get(url)

        if response.status_code == 404:
            logger.debug("Ashby: %s not found (404)", slug)
            return []

        if response.status_code != 200:
            logger.warning("Ashby %s → HTTP %d", slug, response.status_code)
            return []

        data = response.json()
        postings = data.get("jobPostings", [])

        results: list[JobPosting] = []
        for p in postings:
            title = p.get("title", "")
            if not title:
                continue
            if not self._is_tpm_relevant(title):
                continue
            if self.is_excluded_title(title):
                continue

            ext_id = p.get("id", str(uuid4()))
            description_html = p.get("descriptionHtml", "")
            description = self._strip_html(description_html)
            location = p.get("locationName") or ("Remote" if p.get("isRemote") else "Unknown")

            posted_at = None
            if pub := p.get("publishedAt"):
                try:
                    posted_at = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                except ValueError:
                    pass

            results.append(
                JobPosting(
                    id=uuid4(),
                    title=title,
                    company_name=company_name,
                    description=description,
                    location=location,
                    is_remote=p.get("isRemote", False),
                    job_type=p.get("employmentType"),
                    source=self.SOURCE,
                    external_id=ext_id,
                    external_url=f"https://jobs.ashbyhq.com/{slug}/{ext_id}",
                    posted_at=posted_at,
                    scraped_at=datetime.utcnow(),
                )
            )

        return results

    @staticmethod
    def _is_tpm_relevant(title: str) -> bool:
        """Return True if the title is relevant to TPM/PM roles."""
        title_lower = title.lower()
        return any(kw in title_lower for kw in TPM_KEYWORDS)

    @staticmethod
    def _strip_html(html: str) -> str:
        """Minimal HTML tag stripping — avoids pulling in BeautifulSoup for this lightweight use."""
        import re
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text
