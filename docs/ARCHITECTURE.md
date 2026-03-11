# JobRadar — System Architecture

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         JOBRADOR SYSTEM                                  │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                      SCRAPER LAYER (Layer 1)                     │    │
│  │                                                                   │    │
│  │  LinkedIn  Indeed  Naukri  Greenhouse  Lever  Wellfound  Workday │    │
│  │      ↓        ↓      ↓         ↓         ↓        ↓        ↓    │    │
│  │  ┌─────────────────────────────────────────────────────────┐    │    │
│  │  │             Job Aggregator (Unified Schema)              │    │    │
│  │  └──────────────────────────┬──────────────────────────────┘    │    │
│  └─────────────────────────────│───────────────────────────────────┘    │
│                                 │                                         │
│  ┌─────────────────────────────▼───────────────────────────────────┐    │
│  │                      DATA LAYER (Layer 2)                        │    │
│  │                                                                   │    │
│  │   PostgreSQL / Supabase                                          │    │
│  │   ┌───────────────┐  ┌──────────────┐  ┌─────────────────────┐ │    │
│  │   │  job_postings │  │  job_scores  │  │  applications       │ │    │
│  │   └───────────────┘  └──────────────┘  └─────────────────────┘ │    │
│  └─────────────────────────────┬───────────────────────────────────┘    │
│                                 │                                         │
│  ┌─────────────────────────────▼───────────────────────────────────┐    │
│  │                      AI ENGINE (Layer 3)                         │    │
│  │                                                                   │    │
│  │   ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐ │    │
│  │   │ Job Scorer   │  │ Salary Est.  │  │ Resume Customizer    │ │    │
│  │   │ (LLM 0-100)  │  │ (Heuristic)  │  │ (LLM bullets + CL)  │ │    │
│  │   └──────────────┘  └──────────────┘  └──────────────────────┘ │    │
│  └─────────────────────────────┬───────────────────────────────────┘    │
│                                 │                                         │
│  ┌─────────────────────────────▼───────────────────────────────────┐    │
│  │                   PRESENTATION LAYER (Layer 4)                   │    │
│  │                                                                   │    │
│  │   ┌──────────────────┐   ┌────────────────┐  ┌───────────────┐ │    │
│  │   │ Streamlit        │   │ Alert System   │  │ Tracker       │ │    │
│  │   │ Dashboard        │   │ Email/Telegram │  │ Lifecycle     │ │    │
│  │   └──────────────────┘   └────────────────┘  └───────────────┘ │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Design

### 2.1 Scraper Layer

Each scraper is a standalone Python class extending `BaseScraper`. Scrapers use **Playwright** (headless Chromium) for JavaScript-heavy sites (LinkedIn, Indeed, Naukri) and **httpx + BeautifulSoup** for API-friendly sites (Greenhouse, Lever, Ashby).

**Rate limiting strategy:**
- Randomized delay: 2–6 seconds between requests
- Max 200 jobs per source per run
- Rotate user-agent strings
- LinkedIn: uses session cookies (not password scraping)

**Deduplication:**
- Each job has a `content_hash = SHA256(title + company + url)`
- Skip insert if hash already exists in DB

### 2.2 Aggregation Layer

The `JobAggregator` collects results from all scrapers and normalizes them into the unified `JobPosting` Pydantic model before persisting to Postgres.

```
Raw Scraper Output → Normalizer → JobPosting → DB Insert (upsert on url)
```

### 2.3 AI Scoring Engine

Uses OpenAI `gpt-4o` (or `claude-3-5-sonnet`) to score each job.

**Scoring flow:**
1. Retrieve job from DB (unscored = `ai_score IS NULL`)
2. Build prompt: system prompt (profile) + user prompt (job description)
3. Parse JSON response → extract score, notes, fit tags
4. Write back to `job_scores` table
5. Batch: 20 jobs per run to manage token cost

**Cost estimate:** ~$0.02–0.05 per job scored with GPT-4o

### 2.4 Salary Estimation Engine

Uses a two-stage approach:

1. **Regex extraction** — parse salary bands from job text (₹, LPA, CTC, lakh, cr)
2. **Heuristic scoring** — if no salary found, estimate from:
   - Company tier (Tier 1–4 lookup table)
   - Role seniority keywords (Staff/Sr/Director add premium)
   - Location (Bangalore remote ≈ 1.2x multiplier)
3. **LLM fallback** — for ambiguous roles, ask LLM to estimate band

Output: `salary_band` in enum: `<40L | 40-60L | 60-80L | 80-100L | 100L+`

### 2.5 Resume Customization Engine

Takes the base resume (`resume/base_resume.md`) and rewrites key bullet points to align with the target JD.

**Safety guardrails:**
- Never invent experience not in base resume
- Only rephrase and reorder existing bullets
- Always write truthful content

Output files saved to `resume/generated/<job_id>_resume.md`

### 2.6 Application Automation (Optional / Manual Approval Mode)

For platforms with "Easy Apply" (LinkedIn, Naukri):

1. Playwright logs in via stored session
2. Navigates to job URL
3. Clicks "Easy Apply" or "Apply Now"
4. Fills form fields from profile config
5. Uploads generated custom resume PDF
6. **PAUSES for manual review before submit** (default mode)
7. Logs application to tracker

**Hard limits:**
- Max 5 auto-attempts per day
- `MANUAL_APPROVAL=true` by default — NEVER auto-submits without confirmation
- Blocklist for companies you've already applied to

### 2.7 Dashboard

Streamlit app with 4 tabs:

| Tab | Content |
|---|---|
| **Top Picks** | Top 20 scored jobs this week, sortable by score/salary/company |
| **All Jobs** | Full paginated table with filters |
| **Applications** | Tracker: shortlisted → applied → interview → offer |
| **Insights** | Charts: jobs by source, score distribution, company tier breakdown |

### 2.8 Notification System

| Channel | Trigger | Content |
|---|---|---|
| Telegram | score ≥ 85 | Title, company, score, apply link |
| Email | Daily digest (9 AM IST) | Top 10 new jobs |
| Slack (optional) | score ≥ 90 | Same as Telegram |

### 2.9 Tracking System

Application states: `discovered` → `shortlisted` → `applied` → `phone_screen` → `interview` → `offer` → `rejected` → `accepted`

---

## 3. Database Schema (Logical ERD)

```
job_postings (1) ─────────── (1) job_scores
     │
     └──────────── (many) applications
                        │
                        └─── application_events (status history)
```

---

## 4. Scheduling Architecture

```
GitHub Actions (every 6 hours)
    │
    ├── pipeline/orchestrator.py --mode=scrape
    │       ├── Run all scrapers in parallel (ThreadPoolExecutor)
    │       ├── Aggregate + deduplicate
    │       └── Insert to DB
    │
    ├── pipeline/orchestrator.py --mode=score
    │       ├── Fetch unscored jobs (limit 50)
    │       ├── AI score each
    │       └── Update job_scores
    │
    └── pipeline/orchestrator.py --mode=alert
            ├── Find new jobs with score >= MIN_SCORE_ALERT
            └── Send Telegram + email alerts
```

---

## 5. Security Considerations

- All credentials in `.env` (gitignored)
- DB connection uses SSL (Supabase / hosted Postgres)
- LinkedIn/Naukri passwords stored encrypted at rest (Fernet key in `.env`)
- No credentials ever logged or surfaced in API responses
- Playwright runs in sandboxed container (Docker)
- Rate limits enforced to avoid scraper bans

---

## 6. Proposed Enhancements

### 6.1 AI Recruiter Outreach
- Use LinkedIn profile URL from job posting
- LLM generates personalized connection request message
- Template: highlight shared background, express interest, ask for referral

### 6.2 Network Intelligence
- Cross-reference company names against your LinkedIn connections (export CSV)
- Flag jobs where you have 1st/2nd degree connections
- Rank those jobs with a "referral probability" boost

### 6.3 Referral Detection
- Scrape Blind/Glassdoor for companies with active referral programs
- Check if any ex-colleagues now work there (via LinkedIn)
- Surface "referral opportunities" separately in dashboard

### 6.4 Hidden Job Discovery
- Monitor company career pages directly (not job boards)
- Detect new postings from Tier 1–2 companies within 24 hours of posting
- Subscribe to company newsletters / LinkedIn company page alerts

### 6.5 Compensation Intelligence
- Parse and index Levels.fyi data for target companies
- Build a local compensation database (title → company → band)
- Automatically attach compensation reference to each job card

---

## 7. Cost Estimate (Monthly)

| Component | Cost |
|---|---|
| LLM scoring (500 jobs/month × $0.03) | ~$15 |
| Supabase (free tier) | $0 |
| GitHub Actions (free tier, < 2000 min) | $0 |
| Telegram Bot | $0 |
| Email (Gmail SMTP) | $0 |
| **Total** | **~$15/month** |
