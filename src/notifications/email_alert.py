"""
Email alert sender — Gmail SMTP daily digest.

Sends an HTML email digest of top new jobs. Uses Gmail App Password (not
your main password) with SMTP+TLS on port 587.

Setup:
  1. Enable 2FA on your *personal* Gmail account
  2. Go to Google Account → Security → App Passwords → create one
  3. Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env (never commit)
  4. Set ALERT_EMAIL_TO to your destination address

COMPLIANCE NOTE: Uses a personal Gmail account only. Never use GEHC
email credentials or send job search alerts to GEHC addresses.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

logger = logging.getLogger("notifications.email_alert")


async def send_email_digest(jobs: list[dict[str, Any]]) -> bool:
    """Send an HTML email digest of high-score jobs. Returns True if sent."""
    sender = os.environ.get("GMAIL_ADDRESS", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    recipient = os.environ.get("ALERT_EMAIL_TO", sender)

    if not sender or not password:
        logger.warning("GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set — skipping email")
        return False

    subject = f"JobRadar: {len(jobs)} high-match job{'s' if len(jobs) != 1 else ''} found"
    html = _build_html(jobs)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        logger.info("Email digest sent to %s (%d jobs)", recipient, len(jobs))
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("Gmail authentication failed — check GMAIL_APP_PASSWORD")
    except Exception as exc:
        logger.error("Email send failed: %s", exc)
    return False


def _build_html(jobs: list[dict[str, Any]]) -> str:
    rows = ""
    for job in jobs:
        score = int(job.get("total_score") or 0)
        badge_color = "#16a34a" if score >= 85 else "#ca8a04"
        rows += f"""
        <tr>
            <td style="padding:12px;border-bottom:1px solid #e5e7eb;">
                <span style="background:{badge_color};color:#fff;border-radius:4px;
                             padding:2px 8px;font-weight:bold;font-size:14px;">
                    {score}/100
                </span>
            </td>
            <td style="padding:12px;border-bottom:1px solid #e5e7eb;">
                <strong>{_html_esc(str(job.get('title', '')))}</strong><br>
                <span style="color:#6b7280;">{_html_esc(str(job.get('company', '')))}</span>
            </td>
            <td style="padding:12px;border-bottom:1px solid #e5e7eb;color:#6b7280;">
                {_html_esc(str(job.get('location', '')))}
            </td>
            <td style="padding:12px;border-bottom:1px solid #e5e7eb;color:#6b7280;">
                {_html_esc(str(job.get('salary_band', '') or '—'))}
            </td>
            <td style="padding:12px;border-bottom:1px solid #e5e7eb;">
                <a href="{_html_esc(str(job.get('url', '')))}">Apply →</a>
            </td>
        </tr>"""

    return f"""
<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;max-width:900px;margin:0 auto;color:#111;">
    <h2 style="color:#2563eb;">JobRadar — High-Match Jobs</h2>
    <p style="color:#6b7280;">{len(jobs)} new job{'s' if len(jobs) != 1 else ''} matched your profile</p>
    <table style="width:100%;border-collapse:collapse;">
        <thead>
            <tr style="background:#f3f4f6;text-align:left;">
                <th style="padding:10px;">Score</th>
                <th style="padding:10px;">Role</th>
                <th style="padding:10px;">Location</th>
                <th style="padding:10px;">Salary</th>
                <th style="padding:10px;">Link</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    <p style="margin-top:24px;color:#9ca3af;font-size:12px;">
        JobRadar — personal job search automation. Not affiliated with any employer.
    </p>
</body>
</html>"""


def _html_esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
