"""
Wellfound (AngelList Talent) scraper — targets AI/SaaS/deep-tech startups.

API approach:
  - Wellfound provides a public jobs listing at wellfound.com/jobs
  - GraphQL endpoint: https://wellfound.com/graphql (requires session cookies)
  - Fallback: public listing page parsed via BeautifulSoup

Target: Staff TPM / Sr. TPM at Series B+ startups in Bengaluru / Remote India.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx

from ..models.job_posting import JobPosting
from .base import BaseScraper

logger = logging.getLogger("scraper.wellfound")

# Wellfound companies to target (company slug → display name)
WELLFOUND_COMPANIES: dict[str, str] = {
    "razorpay": "Razorpay",
    "zepto": "Zepto",
    "meesho": "Meesho",
    "groww": "Groww",
    "cred": "CRED",
    "slice": "Slice",
    "khatabook": "KhataBook",
    "darwinbox": "Darwinbox",
    "leadsquared": "LeadSquared",
    "hasura": "Hasura",
    "browserstack": "BrowserStack",
    "postman": "Postman",
    "freshworks": "Freshworks",
    "zoho": "Zoho",
    "chargebee": "Chargebee",
    "clevertap": "CleverTap",
    "apna": "Apna",
    "vedantu": "Vedantu",
    "simplilearn": "Simplilearn",
    "unacademy": "Unacademy",
}

WELLFOUND_JOBS_API = "https://wellfound.com/graphql"

WELLFOUND_JOBS_QUERY = """
query JobSearchQuery($query: String!, $locationSlug: String) {
  talent {
    jobListings(query: $query, locationTagSlug: $locationSlug, first: 50) {
      edges {
        node {
          id
          title
          description
          remote
          primaryRoleTitle
          jobType
          compensation
          equity
          currency
          startupStartupInfo {
            name
            highConcept
            companySize
            websiteUrl
          }
          locationNames
          liveStartAt
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""


class WellfoundScraper(BaseScraper):
    """
    Scrapes Wellfound (AngelList Talent) for TPM/PM roles at Indian startups.

    Strategy:
    1. GraphQL query for "technical program manager" in Bengaluru/Remote India
    2. Company-specific page scrape for target companies
    """

    SOURCE = "wellfound"

    # HTTP headers mimicking a real browser (Wellfound requires JS-rendered cookies
    # for authenticated GraphQL; the public endpoint works without auth for basic queries)
    BASE_HEADERS = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://wellfound.com/jobs",
        "Origin": "https://wellfound.com",
    }

    def __init__(self) -> None:
        super().__init__()
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers=self.BASE_HEADERS, timeout=30, follow_redirects=True
            )
        return self._client

    def scrape(self) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        seen_hashes: set[str] = set()

        search_terms = [
            "technical program manager",
            "staff TPM",
            "senior technical program manager",
            "program manager engineering",
        ]
        locations = ["bengaluru", "india", "remote-india"]

        for term in search_terms:
            for loc in locations:
                batch = self._graphql_search(term, loc)
                for job in batch:
                    h = self.compute_content_hash(
                        job.title, job.company_name, job.external_url or ""
                    )
                    if h not in seen_hashes:
                        seen_hashes.add(h)
                        job.content_hash = h
                        jobs.append(job)
                time.sleep(2)  # polite rate limiting

        # Company-page direct scrape as fallback
        for slug, name in WELLFOUND_COMPANIES.items():
            batch = self._scrape_company_page(slug, name)
            for job in batch:
                h = self.compute_content_hash(
                    job.title, job.company_name, job.external_url or ""
                )
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    job.content_hash = h
                    jobs.append(job)
            time.sleep(1.5)

        logger.info("Wellfound: scraped %d unique jobs", len(jobs))
        return jobs

    def _graphql_search(self, query: str, location_slug: str) -> list[JobPosting]:
        """Run a GraphQL query against the Wellfound jobs API."""
        payload = {
            "query": WELLFOUND_JOBS_QUERY,
            "variables": {"query": query, "locationSlug": location_slug},
        }
        try:
            client = self._get_client()
            response = client.post(WELLFOUND_JOBS_API, json=payload)

            if response.status_code != 200:
                logger.warning(
                    "Wellfound GraphQL returned %d for '%s/%s'",
                    response.status_code, query, location_slug,
                )
                return []

            data = response.json()
            edges = (
                data.get("data", {})
                .get("talent", {})
                .get("jobListings", {})
                .get("edges", [])
            )
            return [self._edge_to_job(e) for e in edges if e.get("node")]

        except Exception as exc:
            logger.error("Wellfound GraphQL error: %s", exc)
            return []

    def _edge_to_job(self, edge: dict[str, Any]) -> JobPosting:
        """Convert a GraphQL job edge to a JobPosting model."""
        node = edge["node"]
        startup = node.get("startupStartupInfo") or {}

        title = node.get("title") or node.get("primaryRoleTitle", "Unknown")
        company = startup.get("name", "Unknown Company")
        description = node.get("description", "")
        locations = node.get("locationNames") or []
        location = locations[0] if locations else ("Remote" if node.get("remote") else "India")

        # Parse date
        posted_at = None
        if live_start := node.get("liveStartAt"):
            try:
                posted_at = datetime.fromisoformat(live_start.replace("Z", "+00:00"))
            except ValueError:
                pass

        # Build URL
        job_id_str = str(node.get("id", uuid4()))
        external_url = f"https://wellfound.com/l/apply/{job_id_str}"

        return JobPosting(
            id=uuid4(),
            title=title,
            company_name=company,
            description=description,
            location=location,
            is_remote=node.get("remote", False),
            source=self.SOURCE,
            external_id=job_id_str,
            external_url=external_url,
            posted_at=posted_at,
            scraped_at=datetime.utcnow(),
            job_type=node.get("jobType"),
        )

    def _scrape_company_page(self, slug: str, company_name: str) -> list[JobPosting]:
        """
        Scrape a company's Wellfound jobs page via their public careers listing.
        URL: https://wellfound.com/company/{slug}/jobs
        """
        url = f"https://wellfound.com/company/{slug}/jobs"
        try:
            client = self._get_client()
            response = client.get(url)
            if response.status_code != 200:
                logger.debug("Wellfound company page %s → %d", slug, response.status_code)
                return []

            # Extract job data from __NEXT_DATA__ JSON embedded in page HTML
            import re

            match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
                response.text,
                re.DOTALL,
            )
            if not match:
                return []

            page_data = json.loads(match.group(1))
            jobs_data = (
                page_data.get("props", {})
                .get("pageProps", {})
                .get("startupJobListings", [])
            ) or []

            results: list[JobPosting] = []
            for jd in jobs_data:
                title = jd.get("title", "")
                if not title:
                    continue
                if self.is_excluded_title(title):
                    continue

                ext_id = str(jd.get("id", uuid4()))
                results.append(
                    JobPosting(
                        id=uuid4(),
                        title=title,
                        company_name=company_name,
                        description=jd.get("description", ""),
                        location=jd.get("locationNames", ["India"])[0],
                        is_remote=jd.get("remote", False),
                        source=self.SOURCE,
                        external_id=ext_id,
                        external_url=f"https://wellfound.com/l/apply/{ext_id}",
                        scraped_at=datetime.utcnow(),
                    )
                )
            return results

        except Exception as exc:
            logger.error("Wellfound company page error for %s: %s", slug, exc)
            return []

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
