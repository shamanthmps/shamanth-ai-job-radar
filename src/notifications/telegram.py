"""
Telegram alert sender.

Sends a formatted message to a personal Telegram chat when a high-score job
is found. Uses the Bot API — no library dependency, just httpx.

Setup:
  1. Create a bot with @BotFather → get TELEGRAM_BOT_TOKEN
  2. Start a chat with the bot, then GET /getUpdates to find your chat_id
  3. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env

COMPLIANCE NOTE: Uses a personal Telegram account only. Never use GEHC
managed devices, accounts, or credentials here.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("notifications.telegram")

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


async def send_telegram_alert(
    *,
    title: str,
    company: str,
    score: int,
    url: str,
    location: str = "",
    salary_band: str = "",
    notes: str = "",
) -> bool:
    """Send a job alert to the configured Telegram chat. Returns True if sent."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — skipping")
        return False

    score_emoji = "🔥" if score >= 90 else "🎯" if score >= 80 else "👀"

    lines = [
        f"{score_emoji} *{score}/100* — {_esc(title)} @ *{_esc(company)}*",
        f"📍 {_esc(location)}" if location else "",
        f"💰 {_esc(salary_band)}" if salary_band else "",
        f"📝 {_esc(notes)}" if notes else "",
        f"[View Job →]({url})" if url else "",
    ]
    text = "\n".join(line for line in lines if line)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _TELEGRAM_API.format(token=token),
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": False,
                },
            )
            resp.raise_for_status()
            return True
    except httpx.HTTPStatusError as exc:
        logger.error("Telegram HTTP error %s: %s", exc.response.status_code, exc.response.text)
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)
    return False


def _esc(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in text)
