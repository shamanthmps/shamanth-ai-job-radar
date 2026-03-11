# JobRadar — Compliance & IP Separation Policy

> This document defines the rules that keep this personal job-search tool
> fully separated from your employer (GEHC) and compliant with typical
> corporate acceptable-use and IP policies.
>
> Read this before running the system for the first time.

---

## 1. This Is a Personal Tool — Not a Work Tool

JobRadar is a **personal productivity project** for managing your private job search.

| Rule | Detail |
|---|---|
| **Run on personal hardware only** | Never execute this on a GEHC-managed laptop, VM, or server |
| **Run on personal network only** | Do not run scrapers over the GEHC corporate VPN or proxy |
| **Use personal accounts only** | All API keys, email, LinkedIn, Telegram must be personal — never GEHC accounts |
| **Store data on personal infra only** | Postgres / Supabase must be on your personal paid/free tier, not GEHC-managed DBs |
| **No GEHC repo** | This project must live in the Shamanth personal workspace only — never commit to GEHC GitLab |

---

## 2. Resume Content — What Must NOT Appear

Your AI-generated resume customizations must never include:

### Prohibited content
- Customer names or any customer-identifiable information (e.g., "GE Healthcare customer X")
- Internal GEHC program names that are not public (internal codenames, project IDs, PI names)
- Non-public financial metrics (cost savings figures, budget amounts that haven't been disclosed publicly)
- Security-related details (architecture of GEHC systems, vulnerability information, access control designs)
- Personnel data (performance ratings, team member details, org charts not in public filings)
- Unreleased product details

### Safe to include (already public or standard professional disclosure)
- Your job title, tenure, and reporting level (visible on LinkedIn already)
- High-level scope descriptions using standard TPM language ("led a 3-team program across Platform and DevOps")
- Generic metrics you'd comfortably say in any interview ("reduced deployment cycle by 40%") — only if you're confident they're not classified
- Skills and frameworks (Agile, Rally, Jira, Python, etc.)

**When in doubt — paraphrase more broadly and remove specifics.**

---

## 3. LLM / AI Usage

| Rule | Detail |
|---|---|
| **Do not paste GEHC confidential data into LLM prompts** | Job descriptions are fine; your resume base content should be cleaned before sending to OpenAI/Anthropic |
| **Use only personal API keys** | Never use a GEHC-provisioned OpenAI or Azure OpenAI key |
| **Review generated content** | Always review AI-generated resume bullets before sending — the AI may hallucinate or phrase things that sound more confidential than intended |

### Prompt safety note
The `ai/scorer.py` and `ai/resume_customizer.py` modules send your base resume + job descriptions to OpenAI APIs. Ensure your `resume/base_resume.md` has been personally reviewed and cleaned before first use.

---

## 4. Credentials & Secrets

```
# .env MUST only contain personal credentials:

OPENAI_API_KEY        → personal OpenAI account
ANTHROPIC_API_KEY     → personal Anthropic account
DATABASE_URL          → personal Supabase or local Postgres
TELEGRAM_BOT_TOKEN    → personal Telegram bot (BotFather)
TELEGRAM_CHAT_ID      → your personal Telegram user ID
SMTP_USER             → personal Gmail / personal email
SMTP_PASSWORD         → Gmail app password (not GEHC SSO)
LINKEDIN_EMAIL        → personal LinkedIn (not GEHC SSO login)
LINKEDIN_PASSWORD     → personal LinkedIn password
NAUKRI_EMAIL          → personal Naukri account
NAUKRI_PASSWORD       → personal Naukri password
```

**Hard Rule:** If any credential contains `ge.com`, `gehealthcare.com`, or any corporate SSO — stop and replace it with a personal account.

---

## 5. What Connects to What — Allowed Topology

```
PERSONAL LAPTOP
      │
      ├── JobRadar (this system)
      │       ├── → LinkedIn (personal account) [OK]
      │       ├── → Naukri (personal account)   [OK]
      │       ├── → Greenhouse / Lever / Ashby  [OK – public job APIs]
      │       ├── → OpenAI API (personal key)   [OK]
      │       ├── → Supabase (personal account) [OK]
      │       ├── → Telegram Bot API            [OK]
      │       └── → Personal Gmail SMTP         [OK]
      │
      └── GEHC Work Tools (KEPT SEPARATE)
              ├── Rally                         [NEVER connected to JobRadar]
              ├── GEHC GitLab                   [NEVER connected to JobRadar]
              ├── Sprint Server port 7847       [NEVER connected to JobRadar]
              └── GEHC email / SSO              [NEVER used by JobRadar]
```

---

## 6. Scheduling & Automation

- GitHub Actions workflows must run in your **personal GitHub account**, not GEHC GitLab CI
- Docker containers (if used) should run on your **personal machine or personal cloud account**
- Do not schedule GitHub Actions to run while connected to GEHC VPN (some corporate proxies log outbound traffic)

---

## 7. Data Retention

- All scraped job data and application history is stored locally (Supabase free tier or local Postgres)
- No GEHC data ever enters this database
- If you leave your current employer, no cleanup is required for this system since GEHC data was never involved

---

## 8. Quick Compliance Checklist Before First Run

- [ ] Confirmed running on personal hardware (not GEHC managed device)
- [ ] Confirmed not on GEHC VPN
- [ ] All credentials in `.env` are personal accounts only
- [ ] `resume/base_resume.md` reviewed — no confidential GEHC customer/project names
- [ ] Using personal GitHub account for Actions (not GEHC GitLab)
- [ ] Supabase/Postgres account is personal
- [ ] Telegram bot created on personal Telegram account
- [ ] SMTP configured with personal Gmail (App Password enabled)

---

*If you have specific questions about what is or is not allowed under your employment agreement, consult Section 5 (Intellectual Property) and Section 8 (Acceptable Use) of your GEHC employment contract.*
