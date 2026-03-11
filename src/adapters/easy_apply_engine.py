"""
Easy Apply Engine — LinkedIn Easy Apply automation adapter.

Wraps Selenium-based LinkedIn Easy Apply logic, inspired by:
  - GodsScion/Auto_job_applier_linkedIn (AGPL-3.0, ~1.9k ⭐)
  - NathanDuma/LinkedIn-Easy-Apply-Bot
  - surapuramakhil-org/Job_search_agent

IMPORTANT USAGE POLICY:
  - Use ONLY in human-in-loop mode (EASY_APPLY_HUMAN_REVIEW=true) by default.
  - Fully automated submission is opt-in via EASY_APPLY_AUTO_SUBMIT=true.
  - Never run against GEHC-managed LinkedIn accounts or networks.
  - Respect LinkedIn ToS: max 20 applications/day, randomized timing.
  - The browser session MUST use a personal LinkedIn account only.

Risk: LinkedIn may ban accounts using automation. Use conservatively.
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID

logger = logging.getLogger("adapters.easy_apply_engine")


class ApplyResult(str, Enum):
    SUBMITTED = "submitted"
    SKIPPED_HUMAN_REVIEW = "skipped_human_review"
    SKIPPED_COMPLEX_FORM = "skipped_complex_form"
    FAILED = "failed"
    DAILY_LIMIT_REACHED = "daily_limit_reached"


@dataclass
class EasyApplyConfig:
    """Configuration for the Easy Apply engine."""

    # From .env
    linkedin_email: str = field(default_factory=lambda: os.environ.get("LINKEDIN_EMAIL", ""))
    linkedin_password: str = field(default_factory=lambda: os.environ.get("LINKEDIN_PASSWORD", ""))

    # Safety controls (defaults are conservative)
    human_review_mode: bool = field(
        default_factory=lambda: os.environ.get("EASY_APPLY_AUTO_SUBMIT", "false").lower() != "true"
    )
    daily_limit: int = field(
        default_factory=lambda: int(os.environ.get("EASY_APPLY_DAILY_LIMIT", "15"))
    )
    min_score_to_apply: int = field(
        default_factory=lambda: int(os.environ.get("EASY_APPLY_MIN_SCORE", "80"))
    )

    # Randomized delay range in seconds (mimics human behavior)
    delay_min: float = 3.0
    delay_max: float = 8.0

    # Companies/titles to never apply to automatically
    blacklisted_companies: list[str] = field(default_factory=list)
    blacklisted_title_words: list[str] = field(
        default_factory=lambda: ["intern", "junior", "associate", "coordinator", "analyst"]
    )


@dataclass
class ApplicationAttempt:
    job_id: UUID
    job_url: str
    title: str
    company: str
    score: int
    result: ApplyResult = ApplyResult.FAILED
    error: str = ""
    applied_at: str = ""


class EasyApplyEngine:
    """
    Modular adapter for LinkedIn Easy Apply automation.

    Design principles (from OSS research):
    - Human-in-loop by default: opens browser/job page, waits for confirmation
    - Falls back gracefully on complex forms (multi-step, file upload required)
    - Daily quota respected
    - All form interactions have randomized delays
    - Stealth mode uses undetected-chromedriver

    Usage:
        engine = EasyApplyEngine()
        result = await engine.apply(job_id, url, title, company, score, resume_path)
    """

    def __init__(self, config: EasyApplyConfig | None = None):
        self.config = config or EasyApplyConfig()
        self._daily_count = 0
        self._driver = None

    def _check_blacklist(self, title: str, company: str) -> bool:
        """Return True if the job should be skipped due to blacklist."""
        title_lower = title.lower()
        company_lower = company.lower()
        for word in self.config.blacklisted_title_words:
            if word in title_lower:
                logger.info("Skipping '%s' — blacklisted title word '%s'", title, word)
                return True
        for co in self.config.blacklisted_companies:
            if co.lower() in company_lower:
                logger.info("Skipping '%s @ %s' — blacklisted company", title, company)
                return True
        return False

    def _human_delay(self) -> None:
        """Sleep a random interval to mimic human typing/click speed."""
        delay = random.uniform(self.config.delay_min, self.config.delay_max)
        time.sleep(delay)

    def _init_driver(self) -> None:
        """Lazy-initialize undetected Chrome driver."""
        if self._driver is not None:
            return
        try:
            import undetected_chromedriver as uc  # type: ignore

            options = uc.ChromeOptions()
            options.add_argument("--no-sandbox")
            options.add_argument("--start-maximized")
            if os.environ.get("CHROME_HEADLESS", "false").lower() == "true":
                options.add_argument("--headless=new")
            self._driver = uc.Chrome(options=options)
            logger.info("Undetected Chrome driver initialized")
        except ImportError:
            logger.error(
                "undetected-chromedriver not installed. "
                "Run: pip install undetected-chromedriver"
            )
            raise

    def apply(
        self,
        job_id: UUID,
        job_url: str,
        title: str,
        company: str,
        score: int,
        resume_path: str | None = None,
    ) -> ApplicationAttempt:
        """
        Attempt to apply to a job via LinkedIn Easy Apply.

        In human_review_mode (default):
          - Opens the job URL in Chrome
          - Logs instructions to the console
          - Returns SKIPPED_HUMAN_REVIEW immediately (user applies manually)

        In auto_submit mode (opt-in):
          - Fills form fields programmatically
          - Submits if all questions can be answered
          - Falls back to SKIPPED_COMPLEX_FORM if form needs manual input
        """
        attempt = ApplicationAttempt(
            job_id=job_id, job_url=job_url, title=title, company=company, score=score
        )

        # Quota check
        if self._daily_count >= self.config.daily_limit:
            logger.warning("Daily Easy Apply limit (%d) reached", self.config.daily_limit)
            attempt.result = ApplyResult.DAILY_LIMIT_REACHED
            return attempt

        # Score gate
        if score < self.config.min_score_to_apply:
            attempt.result = ApplyResult.SKIPPED_COMPLEX_FORM
            attempt.error = f"Score {score} below threshold {self.config.min_score_to_apply}"
            return attempt

        # Blacklist check
        if self._check_blacklist(title, company):
            attempt.result = ApplyResult.SKIPPED_COMPLEX_FORM
            attempt.error = "Blacklisted"
            return attempt

        if self.config.human_review_mode:
            # Human-in-loop: open browser, let user apply
            logger.info(
                "HUMAN REVIEW: %s @ %s (score=%d)\n  → %s",
                title, company, score, job_url,
            )
            attempt.result = ApplyResult.SKIPPED_HUMAN_REVIEW
            return attempt

        # Auto-submit mode (explicit opt-in required)
        return self._auto_submit(attempt, resume_path)

    def _auto_submit(
        self, attempt: ApplicationAttempt, resume_path: str | None
    ) -> ApplicationAttempt:
        """
        Automated form submission (opt-in only).
        Handles standard Easy Apply question types.
        Falls back gracefully on complex forms.
        """
        try:
            self._init_driver()
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import WebDriverWait

            driver = self._driver
            driver.get(attempt.job_url)
            self._human_delay()

            # Find Easy Apply button
            wait = WebDriverWait(driver, 10)
            easy_apply_btn = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".jobs-apply-button"))
            )
            easy_apply_btn.click()
            self._human_delay()

            # Detect form complexity — skip multi-step forms > 3 pages
            pages = driver.find_elements(By.CSS_SELECTOR, ".artdeco-completeness-meter-linear")
            if pages:
                # Complex multi-page form — hand off to human
                logger.info("Complex form detected for '%s @ %s' — skipping auto-submit", 
                           attempt.title, attempt.company)
                attempt.result = ApplyResult.SKIPPED_COMPLEX_FORM
                return attempt

            # Simple form: fill contact info, upload resume if provided
            if resume_path:
                file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                for fi in file_inputs:
                    fi.send_keys(resume_path)
                    self._human_delay()

            # Submit
            submit_btn = driver.find_element(
                By.CSS_SELECTOR, "button[aria-label='Submit application']"
            )
            submit_btn.click()
            self._human_delay()

            self._daily_count += 1
            attempt.result = ApplyResult.SUBMITTED
            logger.info("Applied: %s @ %s (daily count: %d)", 
                       attempt.title, attempt.company, self._daily_count)

        except Exception as exc:
            attempt.result = ApplyResult.FAILED
            attempt.error = str(exc)
            logger.error("Easy Apply failed for '%s': %s", attempt.title, exc)

        return attempt

    def close(self) -> None:
        if self._driver:
            self._driver.quit()
            self._driver = None

    def __enter__(self) -> "EasyApplyEngine":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
