"""
Workday career portal scraper — covers large enterprise companies using Workday ATS.

Workday portals are fully dynamic (JavaScript-rendered) — Playwright is required.

URL patterns:
  - https://{company}.wd5.myworkdayjobs.com/en-US/External
  - https://{company}.wd3.myworkdayjobs.com/en-US/careers

API approach (preferred over DOM scraping):
  Workday portals expose a hidden JSON API:
  POST https://{tenant}.wd5.myworkdayjobs.com/wday/cxs/{tenant}/External/jobs
  Body: {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "program manager"}

Target: Staff/Sr TPM roles at Flipkart, Amazon India, Google India, etc.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from uuid import uuid4

import httpx

from ..models.job_posting import JobPosting
from .base import BaseScraper

logger = logging.getLogger("scraper.workday")

# Workday tenants: {display_name: (tenant_id, wd_subdomain)}
# tenant_id is used in the API path; wd_subdomain is the DNS subdomain
WORKDAY_COMPANIES: dict[str, tuple[str, str]] = {
    "Flipkart": ("flipkart", "wd5"),
    "Amazon": ("amazon", "wd5"),
    "Microsoft": ("microsoft", "wd5"),
    "Cisco": ("cisco", "wd5"),
    "SAP": ("sap", "wd3"),
    "Box": ("box", "wd5"),
    "ServiceNow": ("servicenow", "wd5"),
    "Workday": ("workday", "wd5"),
    "Salesforce": ("salesforce", "wd5"),
    "Stripe": ("stripe", "wd5"),
    "Dropbox": ("dropbox", "wd5"),
    "Lyft": ("lyft", "wd5"),
    "Uber": ("uber", "wd5"),
    "Twitter": ("twitter", "wd5"),  # X Corp
    "Intuit": ("intuit", "wd5"),
    "Oracle": ("oracle", "wd5"),
    "Infosys": ("infosys", "wd5"),
    "TCS": ("tcs", "wd3"),
    "Wipro": ("wipro", "wd5"),
}

# Workday hidden JSON API endpoint pattern
WORKDAY_API_TEMPLATE = (
    "https://{tenant}.{subdomain}.myworkdayjobs.com"
    "/wday/cxs/{tenant}/External/jobs"
)

TPM_SEARCH_TERMS = [
    "technical program manager",
    "staff program manager",
    "senior program manager",
    "engineering program manager",
]


class WorkdayScraper(BaseScraper):
    """
    Scrapes Workday ATS portals for TPM/PM roles.

    Uses Workday's undocumented JSON API (POST endpoint) instead of Playwright
    DOM scraping — faster, more reliable, no browser needed.

    Fallback: If the API call fails, logs a warning and skips that company
    rather than falling back to slow Playwright (can be added later if needed).
    """

    SOURCE = "workday"

    HEADERS = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    def scrape(self) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        seen_hashes: set[str] = set()

        with httpx.Client(headers=self.HEADERS, timeout=25, follow_redirects=True) as client:
            for company_name, (tenant, subdomain) in WORKDAY_COMPANIES.items():
                try:
                    batch = self._fetch_company(client, company_name, tenant, subdomain)
                    for job in batch:
                        h = self.compute_content_hash(
                            job.title, job.company_name, job.external_id or ""
                        )
                        if h not in seen_hashes:
                            seen_hashes.add(h)
                            job.content_hash = h
                            jobs.append(job)
                    time.sleep(1.5)
                except Exception as exc:
                    logger.warning("Workday %s (%s) failed: %s", company_name, tenant, exc)

        logger.info("Workday: scraped %d TPM/PM jobs", len(jobs))
        return jobs

    def _fetch_company(
        self,
        client: httpx.Client,
        company_name: str,
        tenant: str,
        subdomain: str,
    ) -> list[JobPosting]:
        """Fetch jobs from Workday's JSON API for a given tenant."""
        api_url = WORKDAY_API_TEMPLATE.format(tenant=tenant, subdomain=subdomain)
        results: list[JobPosting] = []
        seen_ext_ids: set[str] = set()

        for search_term in TPM_SEARCH_TERMS:
            try:
                batch = self._paginate(client, api_url, search_term, company_name)
                for job in batch:
                    if job.external_id not in seen_ext_ids:
                        seen_ext_ids.add(job.external_id or "")
                        results.append(job)
            except Exception as exc:
                logger.debug("  Workday %s / '%s': %s", tenant, search_term, exc)

        return results

    def _paginate(
        self,
        client: httpx.Client,
        api_url: str,
        search_term: str,
        company_name: str,
        page_size: int = 20,
    ) -> list[JobPosting]:
        """Page through Workday results for a search term."""
        all_jobs: list[JobPosting] = []
        offset = 0

        while True:
            payload = {
                "appliedFacets": {},
                "limit": page_size,
                "offset": offset,
                "searchText": search_term,
            }
            response = client.post(api_url, json=payload)

            if response.status_code != 200:
                break

            data = response.json()
            job_postings = data.get("jobPostings", [])

            if not job_postings:
                break

            for jp in job_postings:
                job = self._posting_to_job(jp, company_name, api_url)
                if job:
                    all_jobs.append(job)

            total = data.get("total", 0)
            offset += page_size
            if offset >= total:
                break

        return all_jobs

    def _posting_to_job(
        self, posting: dict, company_name: str, base_url: str
    ) -> JobPosting | None:
        """Convert a Workday job posting dict to a JobPosting model."""
        title = posting.get("title", "")
        if not title:
            return None
        if self.is_excluded_title(title):
            return None

        ext_id = posting.get("externalPath", str(uuid4())).lstrip("/")
        location = posting.get("locationsText", "Unknown")
        is_remote = "remote" in location.lower()

        # Build apply URL from base API URL
        base = base_url.split("/wday/")[0]
        # Strip query tenant path: https://amazon.wd5.myworkdayjobs.com
        external_url = f"{base}/en-US/External/job/{ext_id}/apply"

        posted_at = None
        if date_str := posting.get("postedOn"):
            try:
                posted_at = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        return JobPosting(
            id=uuid4(),
            title=title,
            company_name=company_name,
            description=posting.get("jobDescription", ""),
            location=location,
            is_remote=is_remote,
            source=self.SOURCE,
            external_id=ext_id,
            external_url=external_url,
            posted_at=posted_at,
            scraped_at=datetime.utcnow(),
        )
