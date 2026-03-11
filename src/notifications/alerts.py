"""
Notification dispatcher — Telegram + email alerts for high-score jobs.
"""

from __future__ import annotations

import logging
from typing import Any

from src.database.db import Database
from src.notifications.telegram import send_telegram_alert
from src.notifications.email_alert import send_email_digest

logger = logging.getLogger("notifications.alerts")


async def send_high_score_alerts(
    db: Database, jobs: list[dict[str, Any]]
) -> int:
    """Send Telegram + email for each high-score job. Returns count alerted."""
    sent = 0
    for job in jobs:
        job_id = str(job["id"])
        title = str(job["title"])
        company = str(job["company"])
        score = int(job.get("total_score") or 0)
        url = str(job.get("url") or "")
        location = str(job.get("location") or "")
        salary_band = str(job.get("salary_band") or "")

        tg_ok = await send_telegram_alert(
            title=title,
            company=company,
            score=score,
            url=url,
            location=location,
            salary_band=salary_band,
        )
        if tg_ok:
            await db.log_alert(job_id=job_id, channel="telegram", score=score)
            sent += 1

    # Also send a batch email digest for all of these
    if jobs:
        email_ok = await send_email_digest(jobs)
        if email_ok:
            for job in jobs:
                await db.log_alert(
                    job_id=str(job["id"]),
                    channel="email",
                    score=int(job.get("total_score") or 0),
                )

    return sent
