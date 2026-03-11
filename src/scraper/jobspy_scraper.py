"""
Primary job scraper — wraps the JobSpy library (python-jobspy).

JobSpy handles LinkedIn, Indeed, Glassdoor, Google Jobs, and Naukri in
a single call. This module runs those searches, normalizes results into
our JobPosting schema, and returns them ready for DB upsert.

Library: https://github.com/speedyapply/JobSpy
Install: pip install python-jobspy

Key gotchas discovered:
- LinkedIn rate-limits ~10 pages/IP. Use proxies or low results_wanted for now.
- Indeed is the most reliable, no rate limiting observed.
- Naukri returns extra fields: skills, experience_range, company_rating.
- Salary data is rare on LinkedIn; Google Jobs often has ranges.
- hours_old and job_type cannot be combined on Indeed in one call — run separately.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from jobspy import scrape_jobs

from src.models.job_posting import (
    CompanyTier,
    JobPosting,
    JobSource,
    SalaryBand,
)
from src.scraper.base import compute_content_hash, is_excluded_title

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Search configuration — tune these to your target profile
# ---------------------------------------------------------------------------

SEARCH_QUERIES = [
    "Technical Program Manager",
    "Staff Technical Program Manager",
    "Engineering Program Manager",
]

LOCATIONS = [
    "Bengaluru, India",
    "India",  # catches remote-India roles
]

# JobSpy site names — LinkedIn intentionally excluded here.
# Glassdoor (400 - India location broken), Naukri (406 - recaptcha), Google (0 results for India) all excluded.
# LinkedIn is handled separately below with conservative settings.
JOBSPY_SITES_NO_LINKEDIN = ["indeed"]

# Separate conservative LinkedIn config — max 15 results, no description fetch
# (fetching descriptions multiplies requests 15x per query — too aggressive)
LINKEDIN_MAX_RESULTS = 15
LINKEDIN_FETCH_DESCRIPTION = False  # Set True only if using a proxy

# Company tier lookup — companies explicitly known to pay above 70L
HIGH_TIER_COMPANIES: dict[str, CompanyTier] = {
    # FAANG+
    "google": CompanyTier.TIER1_FAANG,
    "amazon": CompanyTier.TIER1_FAANG,
    "microsoft": CompanyTier.TIER1_FAANG,
    "meta": CompanyTier.TIER1_FAANG,
    "apple": CompanyTier.TIER1_FAANG,
    # Enterprise tech
    "stripe": CompanyTier.TIER2_ENTERPRISE,
    "atlassian": CompanyTier.TIER2_ENTERPRISE,
    "salesforce": CompanyTier.TIER2_ENTERPRISE,
    "adobe": CompanyTier.TIER2_ENTERPRISE,
    "servicenow": CompanyTier.TIER2_ENTERPRISE,
    "snowflake": CompanyTier.TIER2_ENTERPRISE,
    "databricks": CompanyTier.TIER2_ENTERPRISE,
    "twilio": CompanyTier.TIER2_ENTERPRISE,
    "gitlab": CompanyTier.TIER2_ENTERPRISE,
    "elastic": CompanyTier.TIER2_ENTERPRISE,
    "mongodb": CompanyTier.TIER2_ENTERPRISE,
    "okta": CompanyTier.TIER2_ENTERPRISE,
    "cloudflare": CompanyTier.TIER2_ENTERPRISE,
    "uber": CompanyTier.TIER2_ENTERPRISE,
    "netflix": CompanyTier.TIER2_ENTERPRISE,
    "coinbase": CompanyTier.TIER2_ENTERPRISE,
    "booking": CompanyTier.TIER4_GLOBAL_MID,
    # India unicorns
    "flipkart": CompanyTier.TIER3_INDIA_UNICORN,
    "swiggy": CompanyTier.TIER3_INDIA_UNICORN,
    "razorpay": CompanyTier.TIER3_INDIA_UNICORN,
    "zepto": CompanyTier.TIER3_INDIA_UNICORN,
    "phonepe": CompanyTier.TIER3_INDIA_UNICORN,
    "cred": CompanyTier.TIER3_INDIA_UNICORN,
    "zomato": CompanyTier.TIER3_INDIA_UNICORN,
    "meesho": CompanyTier.TIER3_INDIA_UNICORN,
    "paytm": CompanyTier.TIER3_INDIA_UNICORN,
    "ola": CompanyTier.TIER3_INDIA_UNICORN,
    "freshworks": CompanyTier.TIER3_INDIA_UNICORN,
}


# ---------------------------------------------------------------------------
# Main scraper function
# ---------------------------------------------------------------------------

def run_jobspy_scrape(
    results_per_query: int = 20,
    hours_old: int = 72,
    proxies: Optional[list[str]] = None,
    include_linkedin: bool = True,
) -> list[JobPosting]:
    """
    Run all search queries across job sites.
    LinkedIn is scraped conservatively (1 query, low result count, no description fetch)
    to avoid IP-level rate limiting. It does NOT use your LinkedIn account.

    Args:
        results_per_query: Max results per (site × query × location) combination.
        hours_old: Only fetch jobs posted within this many hours.
        proxies: Optional proxy list — recommended if using LinkedIn description fetch.
        include_linkedin: Whether to include LinkedIn (default True, conservative mode).
    """
    all_jobs: list[JobPosting] = []
    seen_hashes: set[str] = set()

    # --- Non-LinkedIn sites: full query matrix ---
    for query in SEARCH_QUERIES:
        for location in LOCATIONS:
            logger.info("[JobSpy] Scraping (no-LinkedIn): '%s' in '%s'", query, location)
            try:
                df = scrape_jobs(
                    site_name=JOBSPY_SITES_NO_LINKEDIN,
                    search_term=query,
                    location=location,
                    results_wanted=results_per_query,
                    hours_old=hours_old,
                    country_indeed="India",
                    description_format="markdown",
                    verbose=1,
                    proxies=proxies or [],
                )
            except Exception as exc:
                logger.warning(
                    "[JobSpy] Query '%s' / '%s' failed: %s", query, location, exc
                )
                continue

            if df is None or df.empty:
                continue

            for _, row in df.iterrows():
                job = _row_to_job_posting(row)
                if job is None:
                    continue
                if is_excluded_title(job.title):
                    continue
                if job.content_hash in seen_hashes:
                    continue
                seen_hashes.add(job.content_hash)
                all_jobs.append(job)

    # --- LinkedIn: single conservative query, Bengaluru only, no description fetch ---
    # One query, one location, low result count = minimal footprint on LinkedIn's servers.
    # This does NOT use your LinkedIn account — it's unauthenticated HTTP only.
    if include_linkedin:
        logger.info("[JobSpy] LinkedIn (conservative): 'Technical Program Manager' in 'Bengaluru, India'")
        try:
            df_li = scrape_jobs(
                site_name=["linkedin"],
                search_term="Technical Program Manager",
                location="Bengaluru, India",
                results_wanted=LINKEDIN_MAX_RESULTS,
                hours_old=hours_old,
                linkedin_fetch_description=LINKEDIN_FETCH_DESCRIPTION,
                description_format="markdown",
                verbose=1,
                proxies=proxies or [],
            )
            if df_li is not None and not df_li.empty:
                for _, row in df_li.iterrows():
                    job = _row_to_job_posting(row)
                    if job is None or is_excluded_title(job.title):
                        continue
                    if job.content_hash in seen_hashes:
                        continue
                    seen_hashes.add(job.content_hash)
                    all_jobs.append(job)
        except Exception as exc:
            logger.warning("[JobSpy] LinkedIn conservative scrape failed: %s", exc)

    logger.info("[JobSpy] Total unique jobs collected: %d", len(all_jobs))
    return all_jobs


# ---------------------------------------------------------------------------
# Row normalizer
# ---------------------------------------------------------------------------

def _row_to_job_posting(row: pd.Series) -> Optional[JobPosting]:
    """Convert a single JobSpy DataFrame row into our JobPosting model."""
    try:
        title: str = str(row.get("title") or "").strip()
        company: str = str(row.get("company") or "").strip()
        if not title or not company:
            return None

        # Source mapping
        site_raw = str(row.get("site") or "").lower()
        source_map = {
            "linkedin": JobSource.LINKEDIN,
            "indeed": JobSource.INDEED,
            "glassdoor": JobSource.INDEED,   # treat glassdoor as indeed
            "google": JobSource.GOOGLE_JOBS,
            "naukri": JobSource.NAUKRI,
        }
        source = source_map.get(site_raw, JobSource.DIRECT)

        # Location
        city = str(row.get("city") or "")
        state = str(row.get("state") or "")
        location_parts = [p for p in [city, state] if p and p != "nan"]
        location = ", ".join(location_parts) or str(row.get("location") or "")
        is_remote = bool(row.get("is_remote"))

        # URL
        url = str(row.get("job_url") or row.get("job_url_direct") or "").strip()
        if not url:
            return None

        # Description
        description = str(row.get("description") or "").strip() or None

        # Skills (Naukri-specific field)
        skills_raw = row.get("skills")
        skills: list[str] = []
        if skills_raw and not (isinstance(skills_raw, float)):
            if isinstance(skills_raw, list):
                skills = [str(s) for s in skills_raw]
            else:
                skills = [s.strip() for s in str(skills_raw).split(",") if s.strip()]

        # Salary
        salary_min = _safe_float(row.get("min_amount"))
        salary_max = _safe_float(row.get("max_amount"))
        currency = str(row.get("currency") or "INR")
        salary_raw_str = None
        if salary_min or salary_max:
            interval = str(row.get("interval") or "yearly")
            salary_raw_str = (
                f"{currency} {salary_min or '?'}–{salary_max or '?'} {interval}"
            )

        # Convert to LPA (Indian salary context)
        salary_min_lpa = _to_lpa(salary_min, currency, row.get("interval"))
        salary_max_lpa = _to_lpa(salary_max, currency, row.get("interval"))
        salary_band = _estimate_band(salary_min_lpa, salary_max_lpa)

        # Posted date
        date_posted = row.get("date_posted")
        posted_at: Optional[datetime] = None
        if date_posted is not None and not (
            isinstance(date_posted, float) and str(date_posted) == "nan"
        ):
            try:
                if isinstance(date_posted, datetime):
                    posted_at = date_posted
                else:
                    posted_at = datetime.fromisoformat(str(date_posted))
            except (ValueError, TypeError):
                pass

        # Company tier
        company_lower = company.lower()
        tier = CompanyTier.TIER5_OTHER
        for keyword, t in HIGH_TIER_COMPANIES.items():
            if keyword in company_lower:
                tier = t
                break

        content_hash = compute_content_hash(title, company, url)

        return JobPosting(
            content_hash=content_hash,
            title=title,
            company=company,
            location=location or None,
            is_remote=is_remote,
            country="India",
            description=description,
            skills=skills,
            salary_raw=salary_raw_str,
            salary_min_lpa=salary_min_lpa,
            salary_max_lpa=salary_max_lpa,
            salary_band=salary_band,
            source=source,
            url=url,
            apply_url=str(row.get("job_url_direct") or url),
            posted_at=posted_at,
            company_tier=tier,
            company_domain=str(row.get("company_url") or "")[:255] or None,
        )

    except Exception as exc:
        logger.debug("[JobSpy] Row parse error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Salary helpers
# ---------------------------------------------------------------------------

def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _to_lpa(
    amount: Optional[float],
    currency: str,
    interval: object,
) -> Optional[float]:
    """Convert salary amount to LPA (Lakhs Per Annum)."""
    if amount is None:
        return None
    interval_str = str(interval or "yearly").lower()
    # Annualize
    multipliers = {"hourly": 2080, "daily": 260, "weekly": 52, "monthly": 12, "yearly": 1}
    annual = amount * multipliers.get(interval_str, 1)
    # Convert to INR if USD/GBP
    if currency.upper() in ("USD", "US$"):
        annual *= 84  # approx exchange rate
    elif currency.upper() in ("GBP", "£"):
        annual *= 105
    # Convert to LPA (1L = 100,000)
    return round(annual / 100_000, 2)


def _estimate_band(
    min_lpa: Optional[float], max_lpa: Optional[float]
) -> SalaryBand:
    lpa = max_lpa or min_lpa
    if lpa is None:
        return SalaryBand.UNKNOWN
    if lpa >= 100:
        return SalaryBand.ABOVE_100L
    if lpa >= 80:
        return SalaryBand.BAND_80_100L
    if lpa >= 60:
        return SalaryBand.BAND_60_80L
    if lpa >= 40:
        return SalaryBand.BAND_40_60L
    return SalaryBand.BELOW_40L
