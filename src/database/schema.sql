-- ============================================================
-- JobRadar Database Schema
-- PostgreSQL 15+ / Supabase compatible
-- ============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- ENUM TYPES
-- ============================================================

CREATE TYPE salary_band AS ENUM (
    'unknown',
    'below_40l',
    '40_60l',
    '60_80l',
    '80_100l',
    '100l_plus'
);

CREATE TYPE application_status AS ENUM (
    'discovered',
    'shortlisted',
    'applied',
    'phone_screen',
    'technical_interview',
    'final_interview',
    'offer_received',
    'offer_accepted',
    'offer_declined',
    'rejected',
    'withdrawn'
);

CREATE TYPE job_source AS ENUM (
    'linkedin',
    'indeed',
    'naukri',
    'greenhouse',
    'lever',
    'wellfound',
    'workday',
    'ashby',
    'google_jobs',
    'direct'
);

CREATE TYPE company_tier AS ENUM (
    'tier1_faang',
    'tier2_enterprise',
    'tier3_india_unicorn',
    'tier4_global_mid',
    'tier5_other'
);

-- ============================================================
-- CORE TABLES
-- ============================================================

-- 1. Job Postings (raw aggregated from all sources)
CREATE TABLE job_postings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_hash        VARCHAR(64) UNIQUE NOT NULL,  -- SHA256(title+company+url)

    -- Core fields
    title               VARCHAR(255) NOT NULL,
    company             VARCHAR(255) NOT NULL,
    location            VARCHAR(255),
    is_remote           BOOLEAN DEFAULT FALSE,
    country             VARCHAR(100) DEFAULT 'India',

    -- Description
    description         TEXT,
    skills              TEXT[],                        -- extracted skill tags
    experience_years    INT,                          -- parsed min years required

    -- Compensation
    salary_raw          VARCHAR(255),                 -- raw salary string from posting
    salary_min_lpa      NUMERIC(6,2),                 -- parsed minimum in LPA
    salary_max_lpa      NUMERIC(6,2),                 -- parsed maximum in LPA
    salary_band         salary_band DEFAULT 'unknown',

    -- Meta
    source              job_source NOT NULL,
    url                 TEXT NOT NULL,
    apply_url           TEXT,
    scraped_at          TIMESTAMPTZ DEFAULT NOW(),
    posted_at           TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ,
    is_active           BOOLEAN DEFAULT TRUE,

    -- Company metadata
    company_tier        company_tier DEFAULT 'tier5_other',
    company_size        VARCHAR(50),                  -- e.g. "1001-5000"
    company_domain      VARCHAR(255),

    -- Processing flags
    ai_scored           BOOLEAN DEFAULT FALSE,
    resume_generated    BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_job_postings_company ON job_postings(company);
CREATE INDEX idx_job_postings_source ON job_postings(source);
CREATE INDEX idx_job_postings_scraped_at ON job_postings(scraped_at DESC);
CREATE INDEX idx_job_postings_is_active ON job_postings(is_active);
CREATE INDEX idx_job_postings_salary_band ON job_postings(salary_band);

-- ============================================================

-- 2. AI Scores (one-to-one with job_postings)
CREATE TABLE job_scores (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id                  UUID NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,

    -- Core score
    total_score             INT NOT NULL CHECK (total_score BETWEEN 0 AND 100),

    -- Dimension scores (0–100 each)
    score_role_seniority    INT CHECK (score_role_seniority BETWEEN 0 AND 100),
    score_pm_scope          INT CHECK (score_pm_scope BETWEEN 0 AND 100),
    score_domain_match      INT CHECK (score_domain_match BETWEEN 0 AND 100),
    score_leadership        INT CHECK (score_leadership BETWEEN 0 AND 100),
    score_comp_signal       INT CHECK (score_comp_signal BETWEEN 0 AND 100),

    -- Qualitative outputs
    role_fit                VARCHAR(50),              -- 'excellent' | 'good' | 'fair' | 'poor'
    compensation_probability VARCHAR(50),             -- 'high' | 'medium' | 'low'
    leadership_level        VARCHAR(50),              -- 'director' | 'staff' | 'senior' | 'mid'
    estimated_salary_band   salary_band,

    -- LLM reasoning
    notes                   TEXT,
    fit_tags                TEXT[],                   -- ["cross-functional", "AI domain", "platform"]
    red_flags               TEXT[],                   -- ["might be IC role", "startup risk"]
    keywords_matched        TEXT[],

    -- Meta
    scored_at               TIMESTAMPTZ DEFAULT NOW(),
    model_used              VARCHAR(100),             -- 'gpt-4o' | 'claude-3-5-sonnet'
    prompt_version          VARCHAR(20),

    UNIQUE(job_id)
);

CREATE INDEX idx_job_scores_total ON job_scores(total_score DESC);
CREATE INDEX idx_job_scores_job_id ON job_scores(job_id);

-- ============================================================

-- 3. Applications (tracking lifecycle)
CREATE TABLE applications (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id              UUID NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,

    -- Status
    status              application_status DEFAULT 'shortlisted',
    priority            INT DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),  -- 1=highest

    -- Resume used
    resume_version      VARCHAR(255),            -- filename of generated resume
    cover_letter_path   VARCHAR(255),

    -- Application details
    applied_at          TIMESTAMPTZ,
    applied_via         VARCHAR(100),            -- 'easy_apply' | 'portal' | 'email' | 'referral'
    referral_contact    VARCHAR(255),

    -- Recruiter / contact
    recruiter_name      VARCHAR(255),
    recruiter_email     VARCHAR(255),
    recruiter_linkedin  VARCHAR(255),

    -- Notes
    notes               TEXT,

    -- Meta
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_applications_job_id ON applications(job_id);
CREATE INDEX idx_applications_status ON applications(status);

-- ============================================================

-- 4. Application Events (status history / audit trail)
CREATE TABLE application_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id  UUID NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    from_status     application_status,
    to_status       application_status NOT NULL,
    event_notes     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================

-- 5. Generated Resume Artifacts
CREATE TABLE resume_artifacts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id              UUID NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,

    resume_markdown     TEXT,
    resume_pdf_path     VARCHAR(500),
    cover_letter        TEXT,
    recruiter_message   TEXT,

    generated_at        TIMESTAMPTZ DEFAULT NOW(),
    model_used          VARCHAR(100),

    UNIQUE(job_id)
);

-- ============================================================

-- 6. Alert Log
CREATE TABLE alert_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID REFERENCES job_postings(id),
    channel         VARCHAR(50) NOT NULL,    -- 'telegram' | 'email' | 'slack'
    score           INT,
    message         TEXT,
    sent_at         TIMESTAMPTZ DEFAULT NOW(),
    success         BOOLEAN DEFAULT TRUE,
    error_message   TEXT
);

-- ============================================================

-- 7. Scraper Run Log (audit)
CREATE TABLE scraper_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source          job_source NOT NULL,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    jobs_found      INT DEFAULT 0,
    jobs_new        INT DEFAULT 0,
    jobs_updated    INT DEFAULT 0,
    errors          TEXT,
    status          VARCHAR(50) DEFAULT 'running'   -- 'running' | 'success' | 'failed'
);

-- ============================================================

-- 8. Company Reference Table
CREATE TABLE companies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) UNIQUE NOT NULL,
    domain          VARCHAR(255),
    tier            company_tier DEFAULT 'tier5_other',
    typical_salary_band salary_band DEFAULT 'unknown',
    headcount       INT,
    industry        VARCHAR(100),
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Pre-populate priority companies
INSERT INTO companies (name, domain, tier, typical_salary_band) VALUES
    ('Google', 'google.com', 'tier1_faang', '100l_plus'),
    ('Amazon', 'amazon.com', 'tier1_faang', '100l_plus'),
    ('Microsoft', 'microsoft.com', 'tier1_faang', '100l_plus'),
    ('Meta', 'meta.com', 'tier1_faang', '100l_plus'),
    ('Apple', 'apple.com', 'tier1_faang', '100l_plus'),
    ('Stripe', 'stripe.com', 'tier2_enterprise', '100l_plus'),
    ('Atlassian', 'atlassian.com', 'tier2_enterprise', '80_100l'),
    ('Salesforce', 'salesforce.com', 'tier2_enterprise', '80_100l'),
    ('Adobe', 'adobe.com', 'tier2_enterprise', '80_100l'),
    ('ServiceNow', 'servicenow.com', 'tier2_enterprise', '80_100l'),
    ('Snowflake', 'snowflake.com', 'tier2_enterprise', '100l_plus'),
    ('Databricks', 'databricks.com', 'tier2_enterprise', '100l_plus'),
    ('Booking Holdings', 'booking.com', 'tier4_global_mid', '80_100l'),
    ('Uber', 'uber.com', 'tier2_enterprise', '100l_plus'),
    ('Coinbase', 'coinbase.com', 'tier2_enterprise', '100l_plus'),
    ('Flipkart', 'flipkart.com', 'tier3_india_unicorn', '80_100l'),
    ('Swiggy', 'swiggy.com', 'tier3_india_unicorn', '60_80l'),
    ('Razorpay', 'razorpay.com', 'tier3_india_unicorn', '60_80l'),
    ('Zepto', 'zepto.team', 'tier3_india_unicorn', '60_80l'),
    ('PhonePe', 'phonepe.com', 'tier3_india_unicorn', '60_80l'),
    ('CRED', 'cred.club', 'tier3_india_unicorn', '60_80l'),
    ('Zomato', 'zomato.com', 'tier3_india_unicorn', '60_80l'),
    ('Meesho', 'meesho.com', 'tier3_india_unicorn', '60_80l');

-- ============================================================
-- VIEWS
-- ============================================================

-- Top opportunities view (used by dashboard)
CREATE OR REPLACE VIEW v_top_opportunities AS
SELECT
    jp.id,
    jp.title,
    jp.company,
    jp.location,
    jp.is_remote,
    jp.salary_band,
    jp.salary_min_lpa,
    jp.salary_max_lpa,
    jp.source,
    jp.url,
    jp.posted_at,
    jp.scraped_at,
    jp.company_tier,
    js.total_score,
    js.role_fit,
    js.compensation_probability,
    js.leadership_level,
    js.fit_tags,
    js.notes AS ai_notes,
    CASE WHEN a.id IS NOT NULL THEN a.status ELSE NULL END AS application_status
FROM job_postings jp
LEFT JOIN job_scores js ON jp.id = js.job_id
LEFT JOIN applications a ON jp.id = a.job_id
WHERE jp.is_active = TRUE
  AND jp.ai_scored = TRUE
ORDER BY js.total_score DESC NULLS LAST;

-- ============================================================
-- TRIGGERS
-- ============================================================

-- Auto-update applications.updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_applications_updated_at
    BEFORE UPDATE ON applications
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
