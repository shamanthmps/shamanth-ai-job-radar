# JobRadar — AI-Powered Job Discovery & Application System

> Production-grade system for automated discovery, scoring, and tracking of high-quality
> technology leadership roles in Bangalore / Remote India.

---

## Target Profile

| Attribute | Value |
|---|---|
| **Roles** | Staff TPM, Sr. TPM, Engineering Program Manager, Delivery Lead, Director EPM |
| **Location** | Bengaluru · Remote (India) · Remote Global |
| **Compensation** | ₹75L–1CR+ total comp |
| **Company tier** | FAANG+ · Unicorns · High-growth series B/C |

---

## System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                         JOBRADOR PIPELINE                        │
│                                                                   │
│  [Scraper Layer]  →  [Aggregator]  →  [AI Engine]  →  [Ranking]  │
│       ↓                                    ↓              ↓       │
│  LinkedIn, Indeed,               Score + Salary     Dashboard     │
│  Naukri, Greenhouse,             Resume Match       Alerts        │
│  Lever, Wellfound,               Cover Letter       Tracker       │
│  Workday, Ashby                                                    │
└──────────────────────────────────────────────────────────────────┘
```

### Pipeline Stages

| Stage | Description |
|---|---|
| **1. Discovery** | Scrape 9 job sources every 6 hours via GitHub Actions |
| **2. Aggregation** | Normalize into unified `JobPosting` schema → Postgres |
| **3. AI Scoring** | LLM scores each job 0–100 against your profile |
| **4. Salary Estimation** | Heuristic + LLM estimates CTC; filters <70L |
| **5. Resume Matching** | Keyword + semantic match against base resume |
| **6. Resume Customization** | LLM rewrites resume bullets for top-scored jobs |
| **7. Application Prep** | Cover letter + recruiter outreach message |
| **8. Tracking** | Full lifecycle: discovered → applied → interview → offer |
| **9. Alerts** | Email / Telegram / Slack when score > 85 |

---

## Quick Start

```bash
# 1. Clone and enter project
cd C:\Shamanth\Resume\JobRadar

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Mac/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your API keys and DB connection

# 5. Set up database
python scripts/setup_db.py

# 6. Install Playwright browsers
playwright install chromium

# 7. Run first pipeline
python scripts/run_pipeline.py

# 8. Launch dashboard
streamlit run dashboard/app.py
```

---

## Project Structure

```
JobRadar/
├── src/
│   ├── scraper/          # Platform-specific scrapers
│   ├── models/           # Pydantic data models
│   ├── database/         # Postgres/Supabase layer
│   ├── ai/               # LLM scoring, salary estimation, resume gen
│   ├── notifications/    # Email, Telegram, Slack alerts
│   ├── tracker/          # Application lifecycle tracking
│   └── pipeline/         # Orchestration layer
├── dashboard/            # Streamlit opportunity dashboard
├── resume/               # Base resume + generated customizations
├── scripts/              # CLI utilities (setup, run, export)
├── docs/                 # Architecture, deployment, API docs
└── .github/workflows/    # Scheduled scraping via GitHub Actions
```

---

## Scoring Rubric

Jobs are scored 0–100 by the AI engine across 5 dimensions:

| Dimension | Weight | Description |
|---|---|---|
| Role Seniority | 25% | Staff / Sr / Director level match |
| PM Scope | 25% | Cross-functional program ownership |
| Domain Match | 20% | AI / Platform / DevOps / Delivery |
| Leadership Level | 20% | Number of teams, budget, org size |
| Compensation Signal | 10% | Explicit band or company tier |

Threshold: **Score ≥ 75** → Auto-shortlisted · **Score ≥ 85** → Instant alert

---

## Configuration

All settings are in `.env`. Key variables:

```
OPENAI_API_KEY=...          # or ANTHROPIC_API_KEY for Claude
DATABASE_URL=...            # Postgres connection string
TELEGRAM_BOT_TOKEN=...      # For Telegram alerts
TELEGRAM_CHAT_ID=...
SMTP_USER=...               # For email alerts
LINKEDIN_EMAIL=...          # LinkedIn login (used by scraper)
LINKEDIN_PASSWORD=...
NAUKRI_EMAIL=...
NAUKRI_PASSWORD=...
MIN_SCORE_ALERT=85          # Alert threshold
MIN_SALARY_FILTER=7000000   # 70L in rupees
```

---

## Automation Schedule

GitHub Actions runs the full pipeline on a cron schedule:

```
Every 6 hours → Scrape → Score → Rank → Alert
Every Sunday  → Weekly digest email
Every Monday  → Refresh resume customizations for top 10 jobs
```

---

## Priority Company List

Tier 1 (FAANG+): Google · Amazon · Microsoft · Meta · Apple  
Tier 2 (Enterprise tech): Stripe · Atlassian · Salesforce · Adobe · ServiceNow · Snowflake · Databricks  
Tier 3 (India unicorns): Flipkart · Swiggy · Razorpay · Zepto · Meesho · PhonePe · CRED · Zomato  
Tier 4 (Global cos with India presence): Booking Holdings · Uber · Coinbase · Twilio · HashiCorp  

---

## Docs

- [Architecture](docs/ARCHITECTURE.md)
- [Deployment Guide](docs/DEPLOYMENT.md)
- [AI Prompts Reference](docs/PROMPTS.md)
- [Database Schema](src/database/schema.sql)
