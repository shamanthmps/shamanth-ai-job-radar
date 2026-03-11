"""
Pipeline Orchestrator — runs the full JobRadar pipeline.

Modes:
  --mode scrape   → Scrape jobs from all sources, deduplicate, save to DB
  --mode score    → AI-score unscored jobs (batch with rate limiting)
  --mode alert    → Send Telegram/email alerts for new high-score jobs
  --mode resume   → Generate custom resumes for top jobs not yet customized
  --mode all      → Run scrape → score → alert in sequence

Usage:
  python -m scripts.run_pipeline --mode all
  python -m scripts.run_pipeline --mode scrape
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database.db import Database
from src.scraper.jobspy_scraper import run_jobspy_scrape
from src.scraper.greenhouse import GreenhouseScraper
from src.scraper.lever import LeverScraper
from src.ai.scorer import score_jobs_batch
from src.ai.resume_customizer import generate_resume_artifacts
from src.models.job_posting import ResumeArtifact
from src.notifications.alerts import send_high_score_alerts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pipeline")


async def run_scrape(db: Database) -> int:
    """Scrape all sources, save new jobs to DB. Returns count of new jobs."""
    new_total = 0

    # --- Primary: JobSpy (LinkedIn, Indeed, Glassdoor, Google, Naukri) ---
    logger.info("=== Stage 1: JobSpy scrape ===")
    try:
        jobs = run_jobspy_scrape(
            results_per_query=int(os.environ.get("RESULTS_PER_QUERY", "25")),
            hours_old=int(os.environ.get("HOURS_OLD", "72")),
        )
        for job in jobs:
            is_new = await db.upsert_job(job)
            if is_new:
                new_total += 1
        await db.log_scraper_run("linkedin+indeed+naukri+google", len(jobs), new_total)
        logger.info("JobSpy: %d jobs found, %d new", len(jobs), new_total)
    except Exception as exc:
        logger.error("JobSpy scrape failed: %s", exc)
        await db.log_scraper_run("jobspy", 0, 0, status="failed", errors=str(exc))

    # --- Supplementary: Greenhouse (API-based, reliable) ---
    logger.info("=== Stage 2: Greenhouse API scrape ===")
    gh_scraper = GreenhouseScraper()
    try:
        gh_jobs = await gh_scraper.scrape()
        gh_new = 0
        for job in gh_jobs:
            if await db.upsert_job(job):
                gh_new += 1
        await db.log_scraper_run("greenhouse", len(gh_jobs), gh_new)
        new_total += gh_new
        logger.info("Greenhouse: %d jobs found, %d new", len(gh_jobs), gh_new)
    except Exception as exc:
        logger.error("Greenhouse scrape failed: %s", exc)
    finally:
        await gh_scraper.close()

    # --- Supplementary: Lever (API-based, reliable) ---
    logger.info("=== Stage 3: Lever API scrape ===")
    lever_scraper = LeverScraper()
    try:
        lever_jobs = await lever_scraper.scrape()
        lever_new = 0
        for job in lever_jobs:
            if await db.upsert_job(job):
                lever_new += 1
        await db.log_scraper_run("lever", len(lever_jobs), lever_new)
        new_total += lever_new
        logger.info("Lever: %d jobs found, %d new", len(lever_jobs), lever_new)
    except Exception as exc:
        logger.error("Lever scrape failed: %s", exc)
    finally:
        await lever_scraper.close()

    logger.info("=== Scrape complete. Total new jobs: %d ===", new_total)
    return new_total


async def run_score(db: Database) -> int:
    """AI-score unscored jobs. Returns count scored."""
    limit = int(os.environ.get("MAX_SCORE_PER_RUN", "50"))
    logger.info("=== Scoring up to %d unscored jobs ===", limit)
    unscored = await db.get_unscored_jobs(limit=limit)
    if not unscored:
        logger.info("No unscored jobs found.")
        return 0

    scores = score_jobs_batch(unscored)
    for score in scores:
        await db.upsert_score(score)

    logger.info("=== Scored %d jobs ===", len(scores))
    return len(scores)


async def run_alert(db: Database) -> int:
    """Send alerts for newly scored high-quality jobs. Returns count alerted."""
    min_score = int(os.environ.get("MIN_SCORE_ALERT", "85"))
    logger.info("=== Checking for new jobs with score >= %d ===", min_score)
    high_score_jobs = await db.get_new_high_score_jobs(
        min_score=min_score, since_hours=7
    )
    if not high_score_jobs:
        logger.info("No new high-score jobs to alert.")
        return 0

    alerted = await send_high_score_alerts(db, high_score_jobs)
    logger.info("=== Alerted %d jobs ===", alerted)
    return alerted


async def run_resume_gen(db: Database) -> int:
    """Generate custom resumes for top-scored jobs that don't have one yet."""
    logger.info("=== Generating resumes for top-scored jobs ===")
    # Get top-scored jobs without resume artifacts
    jobs = await db.get_top_opportunities(min_score=75, limit=10)
    count = 0
    for job in jobs:
        # Skip if already generated (join in view would show it, but double-check)
        from uuid import UUID
        job_id = UUID(str(job["id"]))
        artifacts = generate_resume_artifacts(
            job_id=job_id,
            title=str(job["title"]),
            company=str(job["company"]),
            description=str(job.get("ai_notes") or ""),  # Use AI notes as fallback
        )
        if artifacts:
            from src.models.job_posting import ResumeArtifact
            artifact = ResumeArtifact(
                job_id=job_id,
                resume_markdown=artifacts.get("resume_markdown"),
                cover_letter=artifacts.get("cover_letter"),
                recruiter_message=artifacts.get("recruiter_message"),
            )
            await db.save_resume_artifact(artifact)
            count += 1
    logger.info("=== Generated %d resume artifacts ===", count)
    return count


async def main(mode: str) -> None:
    db = Database()
    await db.connect()
    try:
        if mode in ("scrape", "all"):
            await run_scrape(db)
        if mode in ("score", "all"):
            await run_score(db)
        if mode in ("alert", "all"):
            await run_alert(db)
        if mode == "resume":
            await run_resume_gen(db)
    finally:
        await db.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JobRadar Pipeline")
    parser.add_argument(
        "--mode",
        choices=["scrape", "score", "alert", "resume", "all"],
        default="all",
        help="Pipeline stage to run",
    )
    args = parser.parse_args()
    asyncio.run(main(args.mode))
