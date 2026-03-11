"""
Database layer — async PostgreSQL via asyncpg / Supabase-compatible.
Handles all read/write operations for JobRadar.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional
from uuid import UUID

import asyncpg

from src.models.job_posting import (
    AIJobScore,
    Application,
    JobPosting,
    OpportunityView,
    ResumeArtifact,
)


class Database:
    """Async PostgreSQL client wrapping asyncpg connection pool."""

    def __init__(self, dsn: Optional[str] = None) -> None:
        self._dsn = dsn or os.environ["DATABASE_URL"]
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[asyncpg.Connection, None]:
        if not self._pool:
            raise RuntimeError("Database not connected. Call db.connect() first.")
        async with self._pool.acquire() as conn:
            yield conn

    # ------------------------------------------------------------------
    # Job Postings
    # ------------------------------------------------------------------

    async def upsert_job(self, job: JobPosting) -> bool:
        """Insert job if not already seen (by content_hash). Returns True if new."""
        data = job.to_db_dict()
        async with self.acquire() as conn:
            result = await conn.fetchval(
                """
                INSERT INTO job_postings (
                    id, content_hash, title, company, location, is_remote, country,
                    description, skills, experience_years,
                    salary_raw, salary_min_lpa, salary_max_lpa, salary_band,
                    source, url, apply_url, scraped_at, posted_at, expires_at,
                    is_active, company_tier, company_size, company_domain
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7,
                    $8, $9, $10,
                    $11, $12, $13, $14,
                    $15, $16, $17, $18, $19, $20,
                    $21, $22, $23, $24
                )
                ON CONFLICT (content_hash) DO NOTHING
                RETURNING id
                """,
                data["id"], data["content_hash"], data["title"], data["company"],
                data["location"], data["is_remote"], data["country"],
                data["description"], data["skills"], data["experience_years"],
                data["salary_raw"], data["salary_min_lpa"], data["salary_max_lpa"],
                data["salary_band"],
                data["source"], data["url"], data["apply_url"],
                data["scraped_at"], data["posted_at"], data["expires_at"],
                data["is_active"], data["company_tier"], data["company_size"],
                data["company_domain"],
            )
        return result is not None

    async def get_unscored_jobs(self, limit: int = 50) -> list[dict]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, title, company, location, description, skills,
                       salary_raw, salary_min_lpa, salary_max_lpa, source, url, company_tier
                FROM job_postings
                WHERE ai_scored = FALSE AND is_active = TRUE
                ORDER BY scraped_at DESC
                LIMIT $1
                """,
                limit,
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Scores
    # ------------------------------------------------------------------

    async def upsert_score(self, score: AIJobScore) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO job_scores (
                    job_id, total_score,
                    score_role_seniority, score_pm_scope, score_domain_match,
                    score_leadership, score_comp_signal,
                    role_fit, compensation_probability, leadership_level,
                    estimated_salary_band, notes, fit_tags, red_flags,
                    keywords_matched, scored_at, model_used, prompt_version
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
                ON CONFLICT (job_id) DO UPDATE SET
                    total_score = EXCLUDED.total_score,
                    score_role_seniority = EXCLUDED.score_role_seniority,
                    score_pm_scope = EXCLUDED.score_pm_scope,
                    score_domain_match = EXCLUDED.score_domain_match,
                    score_leadership = EXCLUDED.score_leadership,
                    score_comp_signal = EXCLUDED.score_comp_signal,
                    role_fit = EXCLUDED.role_fit,
                    compensation_probability = EXCLUDED.compensation_probability,
                    leadership_level = EXCLUDED.leadership_level,
                    estimated_salary_band = EXCLUDED.estimated_salary_band,
                    notes = EXCLUDED.notes,
                    fit_tags = EXCLUDED.fit_tags,
                    red_flags = EXCLUDED.red_flags,
                    keywords_matched = EXCLUDED.keywords_matched,
                    scored_at = EXCLUDED.scored_at,
                    model_used = EXCLUDED.model_used
                """,
                str(score.job_id), score.total_score,
                score.score_role_seniority, score.score_pm_scope,
                score.score_domain_match, score.score_leadership,
                score.score_comp_signal,
                score.role_fit, score.compensation_probability,
                score.leadership_level,
                score.estimated_salary_band.value if score.estimated_salary_band else None,
                score.notes, score.fit_tags, score.red_flags,
                score.keywords_matched,
                score.scored_at, score.model_used, score.prompt_version,
            )
            # Mark the posting as scored
            await conn.execute(
                "UPDATE job_postings SET ai_scored = TRUE WHERE id = $1",
                str(score.job_id),
            )

    # ------------------------------------------------------------------
    # Opportunity View (for dashboard)
    # ------------------------------------------------------------------

    async def get_top_opportunities(
        self,
        min_score: int = 0,
        limit: int = 50,
        source: Optional[str] = None,
    ) -> list[dict]:
        query = """
            SELECT * FROM v_top_opportunities
            WHERE ($1 = 0 OR total_score >= $1)
        """
        params: list[Any] = [min_score]

        if source:
            query += " AND source = $2"
            params.append(source)

        query += f" LIMIT ${len(params) + 1}"
        params.append(limit)

        async with self.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_new_high_score_jobs(
        self, min_score: int = 85, since_hours: int = 6
    ) -> list[dict]:
        """Jobs scored above threshold within the last N hours (for alerts)."""
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT jp.id, jp.title, jp.company, jp.location, jp.url,
                       js.total_score, js.role_fit, js.notes
                FROM job_postings jp
                JOIN job_scores js ON jp.id = js.job_id
                WHERE js.total_score >= $1
                  AND js.scored_at >= NOW() - ($2 || ' hours')::INTERVAL
                  AND jp.is_active = TRUE
                ORDER BY js.total_score DESC
                """,
                min_score, str(since_hours),
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------

    async def create_application(self, app: Application) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO applications (
                    id, job_id, status, priority, resume_version, cover_letter_path,
                    applied_at, applied_via, referral_contact,
                    recruiter_name, recruiter_email, recruiter_linkedin,
                    notes, created_at, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                ON CONFLICT (job_id) DO NOTHING
                """,
                str(app.id), str(app.job_id), app.status.value, app.priority,
                app.resume_version, app.cover_letter_path,
                app.applied_at, app.applied_via, app.referral_contact,
                app.recruiter_name, app.recruiter_email, app.recruiter_linkedin,
                app.notes, app.created_at, app.updated_at,
            )

    async def update_application_status(
        self,
        job_id: UUID,
        new_status: str,
        notes: Optional[str] = None,
    ) -> None:
        async with self.acquire() as conn:
            old = await conn.fetchval(
                "SELECT status FROM applications WHERE job_id = $1", str(job_id)
            )
            await conn.execute(
                """
                UPDATE applications
                SET status = $1, notes = COALESCE($2, notes), updated_at = NOW()
                WHERE job_id = $3
                """,
                new_status, notes, str(job_id),
            )
            await conn.execute(
                """
                INSERT INTO application_events (application_id, from_status, to_status, event_notes)
                SELECT id, $1, $2, $3 FROM applications WHERE job_id = $4
                """,
                old, new_status, notes, str(job_id),
            )

    # ------------------------------------------------------------------
    # Resume Artifacts
    # ------------------------------------------------------------------

    async def save_resume_artifact(self, artifact: ResumeArtifact) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO resume_artifacts (
                    job_id, resume_markdown, resume_pdf_path,
                    cover_letter, recruiter_message, generated_at, model_used
                ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT (job_id) DO UPDATE SET
                    resume_markdown = EXCLUDED.resume_markdown,
                    resume_pdf_path = EXCLUDED.resume_pdf_path,
                    cover_letter = EXCLUDED.cover_letter,
                    recruiter_message = EXCLUDED.recruiter_message,
                    generated_at = EXCLUDED.generated_at,
                    model_used = EXCLUDED.model_used
                """,
                str(artifact.job_id), artifact.resume_markdown,
                artifact.resume_pdf_path, artifact.cover_letter,
                artifact.recruiter_message, artifact.generated_at,
                artifact.model_used,
            )
            await conn.execute(
                "UPDATE job_postings SET resume_generated = TRUE WHERE id = $1",
                str(artifact.job_id),
            )

    # ------------------------------------------------------------------
    # Scraper Run Logging
    # ------------------------------------------------------------------

    async def log_scraper_run(
        self,
        source: str,
        jobs_found: int,
        jobs_new: int,
        status: str = "success",
        errors: Optional[str] = None,
    ) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO scraper_runs
                    (source, completed_at, jobs_found, jobs_new, status, errors)
                VALUES ($1, NOW(), $2, $3, $4, $5)
                """,
                source, jobs_found, jobs_new, status, errors,
            )

    # ------------------------------------------------------------------
    # Alert Logging
    # ------------------------------------------------------------------

    async def log_alert(
        self,
        job_id: Optional[UUID],
        channel: str,
        score: Optional[int],
        message: str,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO alert_log (job_id, channel, score, message, success, error_message)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                str(job_id) if job_id else None,
                channel, score, message, success, error_message,
            )
