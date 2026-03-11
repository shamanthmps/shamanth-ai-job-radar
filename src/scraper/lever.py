"""
Lever scraper — uses the public Lever API (postings endpoint).
No auth required; returns JSON with full job content.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from src.models.job_posting import CompanyTier, JobPosting, JobSource
from src.scraper.base import BaseScraper

logger = logging.getLogger(__name__)

LEVER_COMPANIES: dict[str, tuple[str, CompanyTier]] = {
    "uber": ("Uber", CompanyTier.TIER2_ENTERPRISE),
    "netflix": ("Netflix", CompanyTier.TIER2_ENTERPRISE),
    "canva": ("Canva", CompanyTier.TIER2_ENTERPRISE),
    "shopify": ("Shopify", CompanyTier.TIER2_ENTERPRISE),
    "zendesk": ("Zendesk", CompanyTier.TIER2_ENTERPRISE),
    "cloudflare": ("Cloudflare", CompanyTier.TIER2_ENTERPRISE),
    "grafana": ("Grafana Labs", CompanyTier.TIER4_GLOBAL_MID),
    "gitlab": ("GitLab", CompanyTier.TIER2_ENTERPRISE),
    "elastic": ("Elastic", CompanyTier.TIER2_ENTERPRISE),
    "mongodb": ("MongoDB", CompanyTier.TIER2_ENTERPRISE),
    "okta": ("Okta", CompanyTier.TIER2_ENTERPRISE),
    "segment": ("Segment (Twilio)", CompanyTier.TIER4_GLOBAL_MID),
}

LOCATION_KEYWORDS = ["bangalore", "bengaluru", "india", "remote"]
TITLE_KEYWORDS = [
    "technical program manager", "tpm", "engineering program manager",
    "program manager", "delivery lead", "agile delivery",
]


class LeverScraper(BaseScraper):
    source = JobSource.LEVER

    async def _scrape_impl(self) -> None:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            for slug, (company_name, tier) in LEVER_COMPANIES.items():
                try:
                    jobs = await self._fetch_company_jobs(client, slug, company_name, tier)
                    self.jobs_found.extend(jobs)
                    logger.info("[Lever] %s → %d matching jobs", company_name, len(jobs))
                    await self._delay()
                except Exception as exc:
                    logger.warning("[Lever] %s failed: %s", company_name, exc)

    async def _fetch_company_jobs(
        self,
        client: httpx.AsyncClient,
        slug: str,
        company_name: str,
        tier: CompanyTier,
    ) -> list[JobPosting]:
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        resp = await client.get(url)
        resp.raise_for_status()
        postings = resp.json()

        results: list[JobPosting] = []
        for p in postings:
            title: str = p.get("text", "")
            location_obj = p.get("categories", {})
            location: str = location_obj.get("location", "") or p.get("workplaceType", "")

            if not self._title_matches(title):
                continue
            if not self._location_matches(location):
                continue

            # Build description from Lever's lists structure
            description = self._build_description(p)
            apply_url = p.get("applyUrl") or p.get("hostedUrl", "")

            results.append(
                JobPosting(
                    title=title,
                    company=company_name,
                    location=location,
                    is_remote="remote" in location.lower(),
                    description=description,
                    source=self.source,
                    url=p.get("hostedUrl", apply_url),
                    apply_url=apply_url,
                    posted_at=self._parse_ts(p.get("createdAt")),
                    company_tier=tier,
                )
            )
        return results

    @staticmethod
    def _build_description(posting: dict) -> str:
        parts = []
        if posting.get("descriptionPlain"):
            parts.append(posting["descriptionPlain"])
        for lst in posting.get("lists", []):
            parts.append(lst.get("text", ""))
            items_html = lst.get("content", "")
            items_text = BeautifulSoup(items_html, "html.parser").get_text(
                separator="\n", strip=True
            )
            parts.append(items_text)
        return "\n\n".join(parts)

    @staticmethod
    def _title_matches(title: str) -> bool:
        lower = title.lower()
        return any(kw in lower for kw in TITLE_KEYWORDS)

    @staticmethod
    def _location_matches(location: str) -> bool:
        lower = location.lower()
        return any(kw in lower for kw in LOCATION_KEYWORDS) or location == ""

    @staticmethod
    def _parse_ts(ts: Optional[int]) -> Optional[datetime]:
        if not ts:
            return None
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
