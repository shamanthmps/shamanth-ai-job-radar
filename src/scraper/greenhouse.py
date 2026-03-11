"""
Greenhouse scraper — uses the public JSON feed API.
No login required; no scraping ToS concern for public job feeds.
Targets known high-priority companies that use Greenhouse.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from src.models.job_posting import CompanyTier, JobPosting, JobSource
from src.scraper.base import BaseScraper, SEARCH_TITLES

logger = logging.getLogger(__name__)

# Companies known to use Greenhouse — map subdomain → company name + tier
GREENHOUSE_COMPANIES: dict[str, tuple[str, CompanyTier]] = {
    "stripe": ("Stripe", CompanyTier.TIER2_ENTERPRISE),
    "coinbase": ("Coinbase", CompanyTier.TIER2_ENTERPRISE),
    "databricks": ("Databricks", CompanyTier.TIER2_ENTERPRISE),
    "snowflake": ("Snowflake", CompanyTier.TIER2_ENTERPRISE),
    "atlassian": ("Atlassian", CompanyTier.TIER2_ENTERPRISE),
    "twilio": ("Twilio", CompanyTier.TIER4_GLOBAL_MID),
    "hashicorp": ("HashiCorp", CompanyTier.TIER4_GLOBAL_MID),
    "figma": ("Figma", CompanyTier.TIER2_ENTERPRISE),
    "notion": ("Notion", CompanyTier.TIER4_GLOBAL_MID),
    "plaid": ("Plaid", CompanyTier.TIER4_GLOBAL_MID),
    "affirm": ("Affirm", CompanyTier.TIER4_GLOBAL_MID),
    "robinhood": ("Robinhood", CompanyTier.TIER4_GLOBAL_MID),
    "brex": ("Brex", CompanyTier.TIER4_GLOBAL_MID),
    "airtable": ("Airtable", CompanyTier.TIER4_GLOBAL_MID),
    "rippling": ("Rippling", CompanyTier.TIER2_ENTERPRISE),
}

LOCATION_KEYWORDS = ["bangalore", "bengaluru", "india", "remote"]
TITLE_KEYWORDS = [
    "technical program manager", "tpm", "engineering program manager",
    "program manager", "delivery lead", "agile", "staff tpm",
]


class GreenhouseScraper(BaseScraper):
    source = JobSource.GREENHOUSE

    async def _scrape_impl(self) -> None:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            for board_token, (company_name, tier) in GREENHOUSE_COMPANIES.items():
                try:
                    jobs = await self._fetch_company_jobs(
                        client, board_token, company_name, tier
                    )
                    self.jobs_found.extend(jobs)
                    logger.info(
                        "[Greenhouse] %s → %d matching jobs", company_name, len(jobs)
                    )
                    await self._delay()
                except Exception as exc:
                    logger.warning("[Greenhouse] %s failed: %s", company_name, exc)

    async def _fetch_company_jobs(
        self,
        client: httpx.AsyncClient,
        board_token: str,
        company_name: str,
        tier: CompanyTier,
    ) -> list[JobPosting]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

        results: list[JobPosting] = []
        for job in data.get("jobs", []):
            title: str = job.get("title", "")
            location: str = job.get("location", {}).get("name", "")

            if not self._title_matches(title):
                continue
            if not self._location_matches(location):
                continue

            description_html: str = job.get("content", "") or ""
            description = BeautifulSoup(description_html, "html.parser").get_text(
                separator="\n", strip=True
            )

            apply_url = f"https://boards.greenhouse.io/{board_token}/jobs/{job['id']}"

            results.append(
                JobPosting(
                    title=title,
                    company=company_name,
                    location=location,
                    is_remote="remote" in location.lower(),
                    description=description,
                    source=self.source,
                    url=apply_url,
                    apply_url=apply_url,
                    posted_at=self._parse_date(job.get("updated_at")),
                    company_tier=tier,
                    company_domain=f"{board_token}.com",
                )
            )
            if len(self.jobs_found) + len(results) >= self.MAX_JOBS:
                break

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _title_matches(title: str) -> bool:
        lower = title.lower()
        return any(kw in lower for kw in TITLE_KEYWORDS)

    @staticmethod
    def _location_matches(location: str) -> bool:
        lower = location.lower()
        return any(kw in lower for kw in LOCATION_KEYWORDS)

    @staticmethod
    def _parse_date(raw: Optional[str]) -> Optional[datetime]:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
