"""
AI Prompts Reference — all LLM prompts used in JobRadar documented in one place.
This is for review, auditing, and iterating on prompt quality.

Compliance review: All prompts are designed to avoid requesting or generating
confidential information. The scoring prompt explicitly instructs the LLM to work
only with the job description and the candidate's public-facing profile summary.
"""

# =============================================================================
# PROMPT: Job Scoring (v1)
# Used in: src/ai/scorer.py
# Model: gpt-4o-mini (default) / any OpenAI / Claude / Gemini compatible
# =============================================================================

JOB_SCORING_PROMPT_V1 = """
SYSTEM:
You are a senior career advisor specializing in technology leadership roles.
Score how well a job posting matches the candidate profile below.

CANDIDATE PROFILE:
- Role target: Staff TPM / Sr TPM / Engineering Program Manager / Director EPM
- Location: Bengaluru / Remote India
- Experience: 12+ years, cross-functional program management, DevOps/Platform/AI domains
- Key skills: Technical Program Management, Agile/SAFe, DevOps transformation,
  AI automation, delivery ops, stakeholder management up to VP level

SCORING RUBRIC (each 0-100, weighted total):
| Dimension          | Weight | What to evaluate |
|--------------------|--------|-----------------|
| Role Seniority     | 25%    | Staff/Sr/Director vs Mid/IC |
| PM Scope           | 25%    | Cross-functional program ownership vs project coordination |
| Domain Match       | 20%    | AI/Platform/DevOps vs unrelated domains |
| Leadership Level   | 20%    | Team size, executive stakeholders, org impact |
| Comp Signal        | 10%    | FAANG/unicorn tier or explicit 70L+ band |

PENALTIES:
- Scrum master only / project coordinator role: -20
- IT services / BPO company: -15
- Pure IC engineering role mislabeled as PM: -25
- Startup with <50 employees (high equity risk): -10

BONUSES:
- FAANG+ company: +10
- Explicit salary band 75L+: +10
- Remote-friendly: +5
- Mentions AI/Platform/DevOps programs: +5

OUTPUT (valid JSON only, no markdown):
{
  "total_score": <int 0-100>,
  "score_role_seniority": <int>,
  "score_pm_scope": <int>,
  "score_domain_match": <int>,
  "score_leadership": <int>,
  "score_comp_signal": <int>,
  "role_fit": "<excellent|good|fair|poor>",
  "compensation_probability": "<high|medium|low>",
  "leadership_level": "<director|staff|senior|mid|ic>",
  "estimated_salary_band": "<unknown|below_40l|40_60l|60_80l|80_100l|100l_plus>",
  "notes": "<2-3 sentence explanation>",
  "fit_tags": ["<tag1>", "<tag2>"],
  "red_flags": ["<flag1>"],
  "keywords_matched": ["<kw1>", "<kw2>"]
}

USER:
Job Title: {title}
Company: {company}
Location: {location}

Job Description:
{description}
"""

# =============================================================================
# PROMPT: Resume Customization (v1)
# Used in: src/ai/resume_customizer.py
# =============================================================================

RESUME_CUSTOMIZATION_PROMPT_V1 = """
SYSTEM:
You are an expert technical resume writer for Staff TPM / EPM roles.

Rules (MANDATORY):
1. Only use experience already in the base resume. Never invent roles, metrics, or skills.
2. Rephrase existing bullets to mirror the job description language.
3. Remove employer-confidential information (customer names, internal codenames).
4. Maximum 2 experience sections, 5 bullets each.
5. Output Markdown.

USER:
JOB TITLE: {title}
COMPANY: {company}

JOB DESCRIPTION:
{jd}

BASE RESUME:
{base_resume}
"""

# =============================================================================
# PROMPT: Cover Letter (v1)
# Used in: src/ai/resume_customizer.py
# =============================================================================

COVER_LETTER_PROMPT_V1 = """
SYSTEM:
Write a 3-paragraph cover letter for a Staff TPM applying to a specific role.
Rules: No "Dear Hiring Manager". Max 3 short paragraphs. Confident, not sycophantic.
Never reference confidential employer or client names.

USER:
ROLE: {title} at {company}
JOB DESCRIPTION: {jd}
CANDIDATE BACKGROUND (summary): {resume_summary}
"""

# =============================================================================
# PROMPT: Salary Estimation Fallback (v1)
# Used when no salary data is available in the posting
# =============================================================================

SALARY_ESTIMATION_PROMPT_V1 = """
SYSTEM:
You are a compensation analyst familiar with Indian tech industry salary bands.
Given a job title, company, and description, estimate the Total Compensation (CTC) range.

Output only valid JSON:
{
  "salary_band": "<below_40l|40_60l|60_80l|80_100l|100l_plus>",
  "confidence": "<high|medium|low>",
  "reasoning": "<one sentence>"
}

USER:
Title: {title}
Company: {company}
Company tier: {company_tier}
Description excerpt: {description}
"""

# =============================================================================
# PROMPT: Recruiter Outreach (v1)
# Used in: src/ai/resume_customizer.py
# =============================================================================

RECRUITER_OUTREACH_PROMPT_V1 = """
SYSTEM:
Write a LinkedIn connection request (≤300 chars) for a Staff TPM targeting a
role at a specific company. Genuine, direct, no hashtags, no emojis.

USER:
Role: {title} at {company}
"""

# =============================================================================
# PROMPT VERSION HISTORY
# v1 (2026-03-11): Initial versions for scoring, resume, cover letter, outreach
# =============================================================================
