"""
Base scraper utilities — shared helpers for supplementary scrapers.

NOTE: The primary scraping engine is JobSpy (python-jobspy), which handles
LinkedIn, Indeed, Glassdoor, Google Jobs, and Naukri via a single pip package.
This module provides the base class for supplementary scrapers
(Greenhouse, Lever, Ashby, Workday direct-api scrapers) that JobSpy does not cover.

See: https://github.com/speedyapply/JobSpy
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from src.models.job_posting import JobPosting, JobSource

logger = logging.getLogger(__name__)

# Search config for the target profile
SEARCH_TITLES = [
    "Technical Program Manager",
    "Staff Technical Program Manager",
    "Senior Technical Program Manager",
    "Engineering Program Manager",
    "Program Manager Platform",
    "Delivery Lead",
    "Agile Delivery Manager",
    "Director Engineering Program Management",
]

SEARCH_LOCATIONS = [
    "Bangalore",
    "Bengaluru",
    "India Remote",
    "Remote",
]

EXCLUDE_TITLE_KEYWORDS = [
    "hr", "human resources", "recruiter", "marketing",
    "sales", "account manager", "support", "customer success",
    "finance", "legal", "communications",
]


def compute_content_hash(title: str, company: str, url: str) -> str:
    """SHA-256 of title+company+url for deduplication."""
    raw = f"{title.lower().strip()}|{company.lower().strip()}|{url.strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def is_excluded_title(title: str) -> bool:
    lower = title.lower()
    return any(kw in lower for kw in EXCLUDE_TITLE_KEYWORDS)


class BaseScraper(ABC):
    """Abstract base for all job scrapers."""

    source: JobSource                    # override in subclass
    BASE_DELAY = (2.0, 6.0)             # random delay range in seconds
    MAX_JOBS = 200                       # max per run

    def __init__(self) -> None:
        self.jobs_found: list[JobPosting] = []
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def scrape(self) -> list[JobPosting]:
        """Entry point. Returns deduplicated list of JobPosting objects."""
        logger.info("[%s] Starting scrape", self.source.value)
        try:
            self.jobs_found = []
            await self._scrape_impl()
            # Filter excluded titles
            before = len(self.jobs_found)
            self.jobs_found = [j for j in self.jobs_found if not is_excluded_title(j.title)]
            filtered = before - len(self.jobs_found)
            if filtered:
                logger.info("[%s] Filtered %d excluded titles", self.source.value, filtered)
            # Stamp content hashes
            for job in self.jobs_found:
                job.content_hash = compute_content_hash(job.title, job.company, job.url)
            logger.info("[%s] Collected %d jobs", self.source.value, len(self.jobs_found))
        except Exception as exc:
            logger.error("[%s] Scrape failed: %s", self.source.value, exc, exc_info=True)
        return self.jobs_found

    # ------------------------------------------------------------------
    # Abstract — implement in each platform scraper
    # ------------------------------------------------------------------

    @abstractmethod
    async def _scrape_impl(self) -> None:
        """Platform-specific scraping logic. Populate self.jobs_found."""
        ...

    # ------------------------------------------------------------------
    # Helpers available to subclasses
    # ------------------------------------------------------------------

    async def _delay(self) -> None:
        """Random polite delay to avoid rate limiting / bans."""
        wait = random.uniform(*self.BASE_DELAY)
        await asyncio.sleep(wait)

    async def _get_browser(self) -> Browser:
        """Lazy-init Playwright browser (headless Chromium)."""
        if self._browser is None:
            self._playwright = await async_playwright().__aenter__()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
        return self._browser

    async def _get_context(self, storage_state: Optional[str] = None) -> BrowserContext:
        """Get a browser context, optionally restoring saved session cookies."""
        browser = await self._get_browser()
        if self._context is None:
            ctx_kwargs: dict = {
                "viewport": {"width": 1280, "height": 800},
                "locale": "en-IN",
                "timezone_id": "Asia/Kolkata",
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/121.0.0.0 Safari/537.36"
                ),
            }
            if storage_state:
                ctx_kwargs["storage_state"] = storage_state
            self._context = await browser.new_context(**ctx_kwargs)
        return self._context

    async def _new_page(self, storage_state: Optional[str] = None) -> Page:
        ctx = await self._get_context(storage_state)
        return await ctx.new_page()

    async def close(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
            if hasattr(self, "_playwright"):
                await self._playwright.__aexit__(None, None, None)
