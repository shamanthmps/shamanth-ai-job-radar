"""
Resume Customization Engine — generates tailored resume bullets, cover letters,
and recruiter outreach messages for high-scored jobs.

COMPLIANCE GUARDRAILS:
1. The base resume (resume/base_resume.md) must be reviewed before use.
   → Remove GEHC customer names, internal project codenames, confidential metrics.
2. The LLM is instructed to ONLY rephrase existing content, never invent experience.
3. Generated files are saved to resume/generated/ (gitignored).
4. Only personal API keys must be used — never GEHC-provisioned LLM credentials.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional
from uuid import UUID

import litellm
from litellm import completion

logger = logging.getLogger(__name__)

RESUME_DIR = Path(__file__).parent.parent.parent / "resume"
BASE_RESUME_PATH = RESUME_DIR / "base_resume.md"
GENERATED_DIR = RESUME_DIR / "generated"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

RESUME_CUSTOMIZATION_SYSTEM = """
You are an expert technical resume writer specializing in Staff TPM / Engineering
Program Manager roles at FAANG and high-growth tech companies.

Your task is to tailor a candidate's existing resume for a specific job posting.

STRICT RULES — follow these exactly:
1. ONLY use experience that already exists in the base resume. Do NOT invent new roles,
   projects, metrics, or skills that are not present in the original.
2. Rephrase, reorder, and reframe existing bullet points to align with the job description.
3. Mirror the language and keywords from the job description where they accurately describe
   the candidate's real experience.
4. Keep all bullets truthful and defensible in an interview setting.
5. Do not include any employer-confidential information (customer names, internal codenames,
   unreleased product details, classified metrics).
6. Format output as Markdown.

Output format:
## Professional Summary
<2-3 sentence summary tailored to this role>

## Key Skills
<comma-separated list of most relevant skills for this JD>

## Experience (tailored bullets for top 2 roles only)
### <Most Recent Role Title> — <Company> (<dates>)
- <tailored bullet 1>
- <tailored bullet 2>
- ...

### <Second Role Title> — <Company> (<dates>)
- <tailored bullet 1>
- ...
"""

COVER_LETTER_SYSTEM = """
You are writing a concise, high-impact cover letter for a Staff-level TPM applying
to a specific role.

Rules:
- Maximum 3 short paragraphs
- Opening: Why this company + role excites you (be specific to the company)
- Middle: 2-3 most relevant achievements from the candidate's background (use only truthful,
  non-confidential experience)
- Closing: Clear call to action

Tone: Confident, professional, not sycophantic. No "I am writing to express my interest..."
Do not start with "Dear Hiring Manager". Use a direct opener.

Format: Plain text (no markdown).
"""

RECRUITER_MESSAGE_SYSTEM = """
Write a short LinkedIn connection request message (≤300 characters) for a Staff TPM
reaching out to a recruiter or hiring manager at a target company.

Rules:
- Never mention a specific internal GEHC project or customer by name
- Be genuine and specific to the company/role
- Express interest without being desperate or generic
- No hashtags, no emojis
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_resume_artifacts(
    job_id: UUID,
    title: str,
    company: str,
    description: str,
    model: Optional[str] = None,
) -> dict:
    """
    Generate tailored resume, cover letter, and recruiter message for one job.

    Returns dict with keys: resume_markdown, cover_letter, recruiter_message.
    Also saves resume_markdown to resume/generated/<job_id>_resume.md.
    """
    effective_model = model or os.environ.get("LLM_MODEL", "groq/llama-3.3-70b-versatile")
    base_resume = _load_base_resume()
    if not base_resume:
        logger.warning("[ResumeGen] base_resume.md not found — skipping generation")
        return {}

    results = {}

    # 1. Tailored resume
    try:
        resume_md = _call_llm(
            model=effective_model,
            system=RESUME_CUSTOMIZATION_SYSTEM,
            user=f"JOB TITLE: {title}\nCOMPANY: {company}\n\n"
                 f"JOB DESCRIPTION:\n{description[:3000]}\n\n"
                 f"BASE RESUME:\n{base_resume[:4000]}",
        )
        results["resume_markdown"] = resume_md
        _save_resume(job_id, resume_md)
        logger.info("[ResumeGen] Resume generated for %s @ %s", title, company)
    except Exception as exc:
        logger.error("[ResumeGen] Resume generation failed: %s", exc)

    _rate_limit_sleep()

    # 2. Cover letter
    try:
        cover_letter = _call_llm(
            model=effective_model,
            system=COVER_LETTER_SYSTEM,
            user=f"ROLE: {title} at {company}\n\n"
                 f"JOB DESCRIPTION:\n{description[:2000]}\n\n"
                 f"CANDIDATE BACKGROUND (summarized):\n{base_resume[:2000]}",
        )
        results["cover_letter"] = cover_letter
    except Exception as exc:
        logger.error("[ResumeGen] Cover letter generation failed: %s", exc)

    _rate_limit_sleep()

    # 3. Recruiter message
    try:
        recruiter_msg = _call_llm(
            model=effective_model,
            system=RECRUITER_MESSAGE_SYSTEM,
            user=f"Role: {title} at {company}",
        )
        results["recruiter_message"] = recruiter_msg
    except Exception as exc:
        logger.error("[ResumeGen] Recruiter message generation failed: %s", exc)

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_base_resume() -> Optional[str]:
    if not BASE_RESUME_PATH.exists():
        logger.warning(
            "[ResumeGen] %s not found. "
            "Create it from your resume — see docs/COMPLIANCE.md before adding content.",
            BASE_RESUME_PATH,
        )
        return None
    return BASE_RESUME_PATH.read_text(encoding="utf-8")


def _save_resume(job_id: UUID, content: str) -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / f"{job_id}_resume.md"
    path.write_text(content, encoding="utf-8")


def _rate_limit_sleep() -> None:
    """Sleep the configured delay between LLM calls to respect free-tier rate limits."""
    delay = float(os.environ.get("LLM_CALL_DELAY", "2.5"))
    time.sleep(delay)


def _call_llm(model: str, system: str, user: str, max_retries: int = 3) -> str:
    for attempt in range(max_retries):
        try:
            resp = completion(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.4,
                max_tokens=1500,
            )
            return resp.choices[0].message.content or ""
        except litellm.RateLimitError:
            wait = 2 ** (attempt + 1)
            logger.warning("[LLM] Rate limit. Retrying in %ds...", wait)
            time.sleep(wait)
    raise RuntimeError(f"LLM call failed after {max_retries} retries")
