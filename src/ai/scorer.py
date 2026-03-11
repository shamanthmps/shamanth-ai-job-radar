"""
AI Scoring Engine — scores jobs 0-100 against your TPM profile using any LLM.

Uses litellm for provider-agnostic LLM calls (Groq, Gemini, Ollama, and 400+ providers).
Defaults to Groq free tier (llama-3.3-70b-versatile) — no paid subscription required.
Rate-limit delays are read from LLM_CALL_DELAY env var (default 2.5s for Groq free tier).

COMPLIANCE NOTE:
- Sends job descriptions + cleaned resume bullets to LLM API.
- Never send GEHC confidential data. Base resume must be reviewed before use.
- Use only personal API keys (see .env.example).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional
from uuid import UUID

import litellm
from litellm import completion

from src.models.job_posting import AIJobScore, SalaryBand

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Profile context — loaded at runtime from resume/profile.md (gitignored)
# ---------------------------------------------------------------------------

_PROFILE_PATH = Path(__file__).parent.parent.parent / "resume" / "profile.md"
_PROFILE_PLACEHOLDER = """
TARGET CANDIDATE PROFILE (use this to score job fit):
[Profile not configured — copy resume/profile.example.md to resume/profile.md and fill it in]
"""


def _load_candidate_profile() -> str:
    """Load profile from resume/profile.md (local only, gitignored)."""
    if _PROFILE_PATH.exists():
        return _PROFILE_PATH.read_text(encoding="utf-8")
    logger.warning(
        "resume/profile.md not found — scoring will use a placeholder profile. "
        "Copy resume/profile.example.md to resume/profile.md and fill in your details."
    )
    return _PROFILE_PLACEHOLDER

# ---------------------------------------------------------------------------
# Scoring prompt
# ---------------------------------------------------------------------------

def _build_scoring_prompt() -> str:
    """Build the scoring system prompt with the locally-loaded candidate profile."""
    return f"""
You are a senior career advisor specializing in technology leadership roles.

Your task is to score how well a job posting matches a candidate's profile.

{_load_candidate_profile()}

SCORING RUBRIC (score each dimension 0-100, then compute weighted total):
- Role Seniority (25%): Is this Staff / Senior / Director level? IC roles score low.
- PM Scope (25%): Does it involve cross-functional program ownership with real delivery accountability?
- Domain Match (20%): Does it touch AI, DevOps, Platform Engineering, or Delivery Ops?
- Leadership Level (20%): Size of teams/programs touched; executive stakeholder exposure?
- Compensation Signal (10%): Does the company tier or explicit salary suggest 70L+ total comp?

IMPORTANT:
- Penalize roles that are actually project coordinator, scrum master only, or pure IC engineering roles.
- Penalize roles at companies that are known to underpay (e.g., IT services firms, BPOs).
- Bonus for companies on this list: Google, Amazon, Microsoft, Stripe, Atlassian, Flipkart,
  Razorpay, Swiggy, Databricks, Snowflake, Uber, Coinbase, PhonePe, CRED.
- Be realistic — most roles will score 40-70. Reserve 85+ for genuinely excellent matches.

Respond ONLY with valid JSON. No prose, no markdown fences. Schema:
{{
  "total_score": <int 0-100>,
  "score_role_seniority": <int 0-100>,
  "score_pm_scope": <int 0-100>,
  "score_domain_match": <int 0-100>,
  "score_leadership": <int 0-100>,
  "score_comp_signal": <int 0-100>,
  "role_fit": "<excellent|good|fair|poor>",
  "compensation_probability": "<high|medium|low>",
  "leadership_level": "<director|staff|senior|mid|ic>",
  "estimated_salary_band": "<unknown|below_40l|40_60l|60_80l|80_100l|100l_plus>",
  "notes": "<2-3 sentence explanation>",
  "fit_tags": ["<tag1>", "<tag2>"],
  "red_flags": ["<flag1>"],
  "keywords_matched": ["<kw1>", "<kw2>"]
}}
"""


def score_job(
    job_id: UUID,
    title: str,
    company: str,
    location: Optional[str],
    description: str,
    model: Optional[str] = None,
) -> Optional[AIJobScore]:
    """
    Score a single job against the candidate profile.
    Returns AIJobScore or None if scoring fails.
    """
    effective_model = model or os.environ.get("LLM_MODEL", "groq/llama-3.3-70b-versatile")

    user_prompt = f"""
Job Title: {title}
Company: {company}
Location: {location or 'Not specified'}

Job Description:
{description[:4000]}
""".strip()

    try:
        response = _call_llm_with_backoff(
            model=effective_model,
            system=_build_scoring_prompt(),
            user=user_prompt,
        )
        raw_json = response.strip()
        data = json.loads(raw_json)

        # Map estimated_salary_band string to enum
        band_raw = data.get("estimated_salary_band", "unknown")
        try:
            band = SalaryBand(band_raw)
        except ValueError:
            band = SalaryBand.UNKNOWN

        return AIJobScore(
            job_id=job_id,
            total_score=int(data.get("total_score", 0)),
            score_role_seniority=data.get("score_role_seniority"),
            score_pm_scope=data.get("score_pm_scope"),
            score_domain_match=data.get("score_domain_match"),
            score_leadership=data.get("score_leadership"),
            score_comp_signal=data.get("score_comp_signal"),
            role_fit=data.get("role_fit"),
            compensation_probability=data.get("compensation_probability"),
            leadership_level=data.get("leadership_level"),
            estimated_salary_band=band,
            notes=data.get("notes"),
            fit_tags=data.get("fit_tags", []),
            red_flags=data.get("red_flags", []),
            keywords_matched=data.get("keywords_matched", []),
            model_used=effective_model,
            prompt_version="v1",
        )

    except json.JSONDecodeError as exc:
        logger.warning("[Scorer] JSON parse error for %s/%s: %s", company, title, exc)
        return None
    except Exception as exc:
        logger.error("[Scorer] Failed to score %s/%s: %s", company, title, exc)
        return None


def score_jobs_batch(
    jobs: list[dict],
    model: Optional[str] = None,
    delay_between: Optional[float] = None,
) -> list[AIJobScore]:
    """
    Score a batch of jobs (dicts from DB).
    Adds delay between calls to respect free-tier rate limits.
    Delay defaults to LLM_CALL_DELAY env var (2.5s for Groq, 4.5s for Gemini).
    """
    if delay_between is None:
        delay_between = float(os.environ.get("LLM_CALL_DELAY", "2.5"))
    results: list[AIJobScore] = []
    for i, job in enumerate(jobs):
        logger.info(
            "[Scorer] %d/%d — %s @ %s",
            i + 1, len(jobs), job.get("title"), job.get("company"),
        )
        description = job.get("description") or ""
        if len(description) < 50:
            logger.info("[Scorer] Skipping — description too short")
            continue

        score = score_job(
            job_id=UUID(str(job["id"])),
            title=str(job.get("title", "")),
            company=str(job.get("company", "")),
            location=job.get("location"),
            description=description,
            model=model,
        )
        if score:
            results.append(score)

        if i < len(jobs) - 1:
            time.sleep(delay_between)

    return results


# ---------------------------------------------------------------------------
# LLM call with exponential backoff
# ---------------------------------------------------------------------------

def _call_llm_with_backoff(
    model: str,
    system: str,
    user: str,
    max_retries: int = 3,
) -> str:
    """Call LLM via litellm with automatic exponential backoff on rate limits."""
    for attempt in range(max_retries):
        try:
            resp = completion(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,   # Low temp for consistent scoring output
                max_tokens=800,
                response_format={"type": "json_object"},  # Supported by Groq, OpenAI, Gemini; fallback below handles others
            )
            return resp.choices[0].message.content or ""
        except litellm.RateLimitError:
            wait = 2 ** (attempt + 1)
            logger.warning("[LLM] Rate limit hit. Retrying in %ds...", wait)
            time.sleep(wait)
        except litellm.BadRequestError as exc:
            # json_object mode not supported by all models — retry without it
            logger.warning("[LLM] Bad request (%s), retrying without json_object mode", exc)
            resp = completion(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                max_tokens=800,
            )
            content = resp.choices[0].message.content or ""
            # Strip markdown fences if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            return content

    raise RuntimeError(f"LLM call failed after {max_retries} retries")
