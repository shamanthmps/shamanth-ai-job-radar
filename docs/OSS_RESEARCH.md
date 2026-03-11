# Open Source Research Report — JobRadar Integration Strategy

**Researched:** March 2026  
**Purpose:** Identify reusable OSS components to extend the existing JobRadar architecture rather than reinventing them.

---

## 1. GitHub Topic Pages Surveyed

| Topic | Repos Found | Key Signal |
|-------|-------------|-----------|
| `job-search` | 794 | JobSpy (2.9k ⭐), GodsScion Auto-Applier (1.9k ⭐), JobFunnel, Job_search_agent |
| `job-scraping` | 24 | JobSpy already integrated; darsan-in Job-Crawler API design useful |
| `job-automation` | 29 | job-autopilot (Streamlit + Docker), LinkedIn-Referral-Automator |
| `linkedin-bot` | 72 | StaffSpy (employee/recruiter lookup); ManiMozaffar LinkedIn scraper (Playwright + Telegram) |
| `linkedin-automation` | 83 | JobScout (Selenium + Notion sync); open-linkedin-api (community-maintained) |
| `ai-agent` | broad | LLM-based agents with form-filling, TensorZero gateway, LangChain function calling |

---

## 2. Repository Deep Analysis

### 2.1 GodsScion/Auto_job_applier_linkedIn ⭐ 1.9k
**URL:** https://github.com/GodsScion/Auto_job_applier_linkedIn  
**License:** AGPL-3.0  
**Activity:** Updated Jan 2026 — actively maintained

| Dimension | Details |
|-----------|---------|
| **Purpose** | LinkedIn Easy Apply bot — fills all form types and submits applications at scale |
| **Stack** | Python, undetected-chromedriver, Selenium, OpenAI, Flask, PyAutoGUI |
| **Scraping** | Selenium with `undetected-chromedriver` to evade LinkedIn bot detection |
| **Automation** | Fills text, textarea, radio, select, checkbox, address fields; handles EEO questions |
| **Resume** | Uploads default PDF; AI resume generation from job description (in development) |
| **Application Logic** | Randomized click timing; stops at configurable daily limit; skips `bad_words` jobs |
| **Limitations** | LinkedIn only; needs Chrome; AGPL license (any derivative must be open source) |

**Reusable Components for JobRadar:**
- `modules/validator.py` — config validation patterns
- Form-fill question answering logic (text/radio/select/checkbox handlers)
- `bad_words` / company blacklist filtering concept
- Application history Flask app (→ adapt as Streamlit tracker tab)
- Stealth Chrome patterns (undetected-chromedriver + randomized delays)

---

### 2.2 surapuramakhil-org/Job_search_agent ⭐ 127
**URL:** https://github.com/surapuramakhil-org/Job_search_agent  
**License:** AGPL-3.0  
**Activity:** Updated Feb 2025; has 4 releases

| Dimension | Details |
|-----------|---------|
| **Purpose** | Full AI-powered job search agent — search, filter, auto-apply |
| **Stack** | Python, LangChain, TensorZero LLM gateway, Selenium, Chrome, Poetry |
| **Scraping** | LinkedIn Selenium (session-cookie based login) |
| **Automation** | Dynamic per-job resume generation; YAML-based profile; form auto-fill |
| **Resume** | Generates unique resume per job from `plain_text_resume.yaml`, saved as PDF |
| **Application Logic** | `--collect` mode (scrape only), `--resume` mode; answer history stored in `answers.json` |
| **Limitations** | LinkedIn only; TensorZero adds complexity; Poetry dependency management |

**Reusable Components for JobRadar:**
- `plain_text_resume.yaml` schema concept → adapt to our `base_resume.md` format
- `--collect` vs `--apply` mode separation (already in our `--mode` flag)
- Answer history file (`answers.json`) → store in DB as `application_qa_log`
- TensorZero gateway concept → LiteLLM already covers this more simply

---

### 2.3 anandanair/job-scraper ⭐ 9 (actively maintained)
**URL:** https://github.com/anandanair/job-scraper  
**License:** MIT  
**Activity:** Updated daily — most architecturally similar to JobRadar

| Dimension | Details |
|-----------|---------|
| **Purpose** | LinkedIn + CareersFuture scraper, AI scoring, PDF resume generation |
| **Stack** | Python, LiteLLM, Playwright, Supabase, Pydantic, GitHub Actions, ReportLab |
| **Scraping** | Playwright for LinkedIn; LinkedIn geo_id + job_type filter params |
| **Automation** | GitHub Actions cron workflows (separate for scrape/score/manage) |
| **Resume** | PDF generation via `ReportLab`; ATS-friendly output; stored in Supabase Storage |
| **Application Logic** | `job_manager.py` — marks expired jobs, checks if still active |
| **Limitations** | LinkedIn-focused; no Easy Apply; 2 sources only |

**Reusable Components for JobRadar:**
- `pdf_generator.py` pattern → our `src/adapters/pdf_resume_engine.py`
- `llm_client.py` rate-limiting + model rotation → already in our `scorer.py`
- `job_manager.py` expiry logic → add to our `Database` class
- GitHub Actions workflow YAML structure (split into scrape/score/manage)
- LinkedIn geo_id search parameter patterns

---

### 2.4 darsan-in/Job-Hunter ⭐ 17
**URL:** https://github.com/darsan-in/Job-Hunter  
**License:** MIT  
**Activity:** Last release Dec 2022 — archived, not maintained

| Dimension | Details |
|-----------|---------|
| **Purpose** | CareerBot — Windows-only Selenium job application bot |
| **Stack** | Python, Selenium, ChromeDriver, batch scripts |
| **Scraping** | Selenium-based, criteria matching |
| **Automation** | Daily quota system, skill-matching filters |
| **Resume** | No resume customization |
| **Limitations** | Windows-only, Selenium-based, abandoned, limited scope |

**Reusable Components for JobRadar:**
- Daily application quota concept (already implemented in our `MAX_SCORE_PER_RUN`)
- Skill-based criteria filtering (already in our `CANDIDATE_PROFILE`)
- **Overall: minimal reuse value — archived project**

---

### 2.5 NathanDuma/LinkedIn-Easy-Apply-Bot ⭐ (legacy)
**URL:** https://github.com/NathanDuma/LinkedIn-Easy-Apply-Bot  

| Dimension | Details |
|-----------|---------|
| **Purpose** | Original LinkedIn Easy Apply bot, frequently forked |
| **Stack** | Python, Selenium |
| **Key Pattern** | Page-scroll + job card iteration + form detection |
| **Limitation** | Abandoned; LinkedIn UI changes broke it; no AI |

**Reusable:** Form detection DOM patterns (adapt for our easy_apply_engine adapter).

---

### 2.6 wodsuz/EasyApplyJobsBot ⭐ (fork of NathanDuma)
Active fork with Turkish job board support and improved Selenium logic.  
**Reusable:** `checkBlacklist()` and multi-page pagination patterns.

---

### 2.7 jomacs/linkedIn_auto_jobs_applier_with_AI (OpenInterpreter fork)
Based on Open-Interpreter + AI agent approach.  
**Reusable:** AI prompt patterns for filling unknown form questions dynamically.

---

### 2.8 OnlineGBC/Jobs_Applier_AI_Agent
Full-stack AI agent (Python + LLM + Selenium).  
**Reusable:** Job application state machine concept.

---

## 3. Additional High-Value Repos from Topic Research

| Repo | Stars | Key Value |
|------|-------|-----------|
| `speedyapply/JobSpy` | 2.9k ⭐ | **Already integrated** — our primary scraper |
| `PaulMcInnis/JobFunnel` | high | TF-IDF based deduplication; YAML config pattern |
| `cullenwatson/StaffSpy` | 600+ | LinkedIn employee lookup → find referral contacts |
| `krishnavalliappan/JobScout` | — | Selenium + Notion sync for application tracking |
| `ManiMozaffar/linkedIn-scraper` | — | Playwright + Telegram + SQL — similar notification stack |
| `KTleft93/joburls` | — | Streamlit UI on top of JobSpy — validates our dashboard approach |
| `darsan-in/Job-Crawler` | — | Multi-source job aggregator API design |

---

## 4. Component → Adapter Mapping

| OSS Component | Source Repo(s) | Our Adapter |
|---------------|----------------|-------------|
| LinkedIn Easy Apply form handler | GodsScion, NathanDuma, surapuramakhil | `src/adapters/easy_apply_engine.py` |
| ATS PDF resume generator | anandanair (ReportLab) | `src/adapters/pdf_resume_engine.py` |
| Wellfound/Ashby/Workday scraper | viktor-shcherb/job-seek design | `src/scraper/wellfound.py` etc. |
| Job expiry manager | anandanair/job_manager.py | `src/database/db.py` (extend) |
| Referral contact finder | StaffSpy | `src/research/staffspy_adapter.py` |
| GitHub OSS tracker | GitHub REST API | `src/research/github_tracker.py` |
| Answer history store | surapuramakhil answers.json | DB table `application_qa_log` |

---

## 5. Integration Risk Assessment

| Component | Risk | Mitigation |
|-----------|------|-----------|
| LinkedIn Easy Apply bot | HIGH — ToS violation risk, account ban | Use conservatively; human-in-loop mode; randomize timing |
| Undetected ChromeDriver | MEDIUM — arms race with LinkedIn | Rotate user-agents; add random delays 3–10s |
| PDF generation (ReportLab) | LOW — pure local generation | Fine to use directly |
| GitHub API tracker | LOW — public API, rate limited | Use personal token; max 5000 req/hr |
| StaffSpy employee lookup | MEDIUM — LinkedIn ToS | Use sparingly for referral research only |

---

## 6. Architecture Update

```
JobRadar Extended Architecture
═══════════════════════════════════════════════════════
┌─────────────────────────────────────────────────────┐
│                   DISCOVERY LAYER                   │
│  JobSpy (LinkedIn/Indeed/Glassdoor/Google/Naukri)   │
│  Greenhouse API │ Lever API │ Wellfound API          │
│  Ashby API      │ Workday Playwright scraper         │
└──────────────────────────┬──────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│                 INTELLIGENCE LAYER                  │
│  AI Scorer (LiteLLM — GPT/Claude/Gemini/Groq)       │
│  Resume Customizer → ATS PDF Generator              │
│  GitHub Research Module (new OSS tracker)           │
└──────────────────────────┬──────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│               OSS ADAPTER LAYER (NEW)               │
│  easy_apply_engine  │  pdf_resume_engine             │
│  job_board_scraper_adapter (Wellfound/Ashby/Workday) │
│  staffspy_adapter (referral contact research)       │
└──────────────────────────┬──────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│                    DATA LAYER                       │
│  PostgreSQL/Supabase  │  asyncpg connection pool     │
│  8 tables + views   │  job expiry manager           │
└──────────────────────────┬──────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│                 PRESENTATION LAYER                  │
│  Streamlit Dashboard (5 tabs — extended)            │
│  Telegram alerts │ Gmail digest                     │
└─────────────────────────────────────────────────────┘
```

---

## 7. Recommended Integration Priority

| Priority | Component | Effort | Value |
|----------|-----------|--------|-------|
| P1 | Wellfound + Ashby + Workday scrapers | Medium | High — covers startup ecosystem |
| P1 | ATS PDF resume generator | Low | High — production artifact for applications |
| P2 | Easy Apply engine (human-in-loop mode) | High | Very High — actual application submission |
| P2 | GitHub Research Module | Low | Medium — tracks new OSS tools |
| P3 | StaffSpy referral contact finder | Medium | High — warm outreach beats cold apply |
| P3 | Job expiry manager | Low | Medium — DB hygiene |
