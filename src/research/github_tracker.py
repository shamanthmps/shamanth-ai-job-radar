"""
GitHub Research Module — tracks OSS repos for job-search automation tools.

Uses the GitHub REST API (public, free, no auth needed for read-only searches).
Authenticated requests: 5,000 req/hr (use GITHUB_TOKEN env var for personal PAT).
Unauthenticated: 60 req/hr.

Purpose:
  - Weekly scan of job-search, job-scraping, job-automation GitHub topics.
  - Surfaces new repos worth integrating (>50 stars, Python, active within 90 days).
  - Caches results locally so reruns don't exhaust the API budget.

Free tier constraints:
  - Public GitHub API: free forever for read-only.
  - Personal PAT required only for more than 60 req/hr.
  - Get a free PAT at: https://github.com/settings/tokens (no scopes needed for public repos).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("research.github_tracker")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GITHUB_API = "https://api.github.com"
CACHE_PATH = Path(__file__).parent.parent.parent / "db" / "github_research_cache.json"
CACHE_TTL_HOURS = 24  # Don't re-fetch within 24 hours

SEARCH_TOPICS = [
    "job-search",
    "job-scraping",
    "job-automation",
    "linkedin-bot",
    "linkedin-automation",
    "job-apply",
]

# Minimum criteria to consider a repo worth tracking
MIN_STARS = 50
ACTIVE_WITHIN_DAYS = 90
LANGUAGE_FILTER = "Python"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TrackedRepo:
    full_name: str          # e.g. "cullenwatson/JobSpy"
    description: str
    stars: int
    forks: int
    language: str
    license: Optional[str]
    pushed_at: str          # ISO datetime of last push
    html_url: str
    topics: list[str]
    open_issues: int
    last_fetched: str       # When we fetched this record


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_weekly_scan(force: bool = False) -> list[TrackedRepo]:
    """
    Run a GitHub topic scan and return repos worth tracking.

    Args:
        force: If True, bypass cache and fetch fresh data.

    Returns:
        List of TrackedRepo objects sorted by stars descending.
    """
    if not force and _is_cache_fresh():
        logger.info("GitHub research: using cached results (< %dh old)", CACHE_TTL_HOURS)
        return _load_cache()

    headers = _build_headers()
    all_repos: dict[str, TrackedRepo] = {}

    with httpx.Client(headers=headers, timeout=20) as client:
        for topic in SEARCH_TOPICS:
            logger.info("GitHub: scanning topic '%s'", topic)
            batch = _search_topic(client, topic)
            for repo in batch:
                if repo.full_name not in all_repos:
                    all_repos[repo.full_name] = repo
            # Respect GitHub's rate limit — 30 req/min for search API
            time.sleep(2)

    results = sorted(all_repos.values(), key=lambda r: r.stars, reverse=True)
    _save_cache(results)
    logger.info("GitHub research: found %d qualifying repos", len(results))
    return results


def get_top_repos(limit: int = 20) -> list[TrackedRepo]:
    """Return the top N repos from the latest cached scan."""
    repos = run_weekly_scan()
    return repos[:limit]


def format_report(repos: list[TrackedRepo]) -> str:
    """Format a human-readable text report of tracked repos."""
    if not repos:
        return "No repos found matching criteria."

    lines = [
        f"GitHub OSS Research Report — {datetime.now().strftime('%Y-%m-%d')}",
        f"{'=' * 60}",
        f"Criteria: Python · {MIN_STARS}+ stars · active in {ACTIVE_WITHIN_DAYS} days",
        "",
    ]

    for i, r in enumerate(repos, 1):
        days_ago = _days_since(r.pushed_at)
        license_str = r.license or "no license"
        lines.append(
            f"{i:2}. [{r.stars:5} ⭐] {r.full_name}"
        )
        lines.append(
            f"     {r.description[:80] if r.description else '(no description)'}"
        )
        lines.append(
            f"     License: {license_str} | Forks: {r.forks} | "
            f"Issues: {r.open_issues} | Last push: {days_ago}d ago"
        )
        lines.append(f"     {r.html_url}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_headers() -> dict[str, str]:
    """Build GitHub API request headers, using PAT if available."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "JobRadar-OSS-Tracker/1.0",
    }
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
        logger.debug("GitHub: using authenticated requests (5000 req/hr)")
    else:
        logger.debug("GitHub: unauthenticated (60 req/hr) — set GITHUB_TOKEN for more")
    return headers


def _search_topic(client: httpx.Client, topic: str) -> list[TrackedRepo]:
    """Search GitHub repos by topic, filtered by language, stars, and activity."""
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=ACTIVE_WITHIN_DAYS)).strftime(
        "%Y-%m-%d"
    )
    query = (
        f"topic:{topic} language:{LANGUAGE_FILTER} "
        f"stars:>={MIN_STARS} pushed:>={cutoff}"
    )
    url = f"{GITHUB_API}/search/repositories"
    params = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": 30,
    }

    try:
        response = client.get(url, params=params)
        if response.status_code == 403:
            logger.warning(
                "GitHub API rate limit reached. Set GITHUB_TOKEN for higher limits."
            )
            return []
        if response.status_code != 200:
            logger.warning("GitHub search returned %d for topic '%s'", response.status_code, topic)
            return []

        items = response.json().get("items", [])
        now = datetime.now(tz=timezone.utc).isoformat()

        results: list[TrackedRepo] = []
        for item in items:
            # Secondary filter: ensure active within N days
            pushed = item.get("pushed_at", "")
            if pushed and _days_since(pushed) > ACTIVE_WITHIN_DAYS:
                continue

            license_name = None
            if lic := item.get("license"):
                license_name = lic.get("spdx_id") or lic.get("name")

            results.append(
                TrackedRepo(
                    full_name=item["full_name"],
                    description=item.get("description") or "",
                    stars=item.get("stargazers_count", 0),
                    forks=item.get("forks_count", 0),
                    language=item.get("language") or "",
                    license=license_name,
                    pushed_at=pushed,
                    html_url=item.get("html_url", ""),
                    topics=item.get("topics", []),
                    open_issues=item.get("open_issues_count", 0),
                    last_fetched=now,
                )
            )
        return results

    except Exception as exc:
        logger.error("GitHub search failed for topic '%s': %s", topic, exc)
        return []


def _days_since(iso_datetime: str) -> int:
    """Return number of days since an ISO datetime string."""
    try:
        dt = datetime.fromisoformat(iso_datetime.replace("Z", "+00:00"))
        delta = datetime.now(tz=timezone.utc) - dt
        return delta.days
    except (ValueError, TypeError):
        return 9999


def _is_cache_fresh() -> bool:
    if not CACHE_PATH.exists():
        return False
    try:
        mtime = datetime.fromtimestamp(CACHE_PATH.stat().st_mtime, tz=timezone.utc)
        return (datetime.now(tz=timezone.utc) - mtime).total_seconds() < CACHE_TTL_HOURS * 3600
    except OSError:
        return False


def _load_cache() -> list[TrackedRepo]:
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return [TrackedRepo(**r) for r in data]
    except Exception:
        return []


def _save_cache(repos: list[TrackedRepo]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps([asdict(r) for r in repos], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="GitHub OSS Research Tracker")
    parser.add_argument("--force", action="store_true", help="Bypass cache, fetch fresh")
    parser.add_argument("--top", type=int, default=20, help="Number of repos to show")
    args = parser.parse_args()

    repos = run_weekly_scan(force=args.force)
    print(format_report(repos[: args.top]))
