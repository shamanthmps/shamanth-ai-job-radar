from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator


class SalaryBand(str, Enum):
    UNKNOWN = "unknown"
    BELOW_40L = "below_40l"
    BAND_40_60L = "40_60l"
    BAND_60_80L = "60_80l"
    BAND_80_100L = "80_100l"
    ABOVE_100L = "100l_plus"


class ApplicationStatus(str, Enum):
    DISCOVERED = "discovered"
    SHORTLISTED = "shortlisted"
    APPLIED = "applied"
    PHONE_SCREEN = "phone_screen"
    TECHNICAL_INTERVIEW = "technical_interview"
    FINAL_INTERVIEW = "final_interview"
    OFFER_RECEIVED = "offer_received"
    OFFER_ACCEPTED = "offer_accepted"
    OFFER_DECLINED = "offer_declined"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class JobSource(str, Enum):
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    NAUKRI = "naukri"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    WELLFOUND = "wellfound"
    WORKDAY = "workday"
    ASHBY = "ashby"
    GOOGLE_JOBS = "google_jobs"
    DIRECT = "direct"


class CompanyTier(str, Enum):
    TIER1_FAANG = "tier1_faang"
    TIER2_ENTERPRISE = "tier2_enterprise"
    TIER3_INDIA_UNICORN = "tier3_india_unicorn"
    TIER4_GLOBAL_MID = "tier4_global_mid"
    TIER5_OTHER = "tier5_other"


class JobPosting(BaseModel):
    """Unified job posting schema used by all scrapers."""

    id: UUID = Field(default_factory=uuid4)
    content_hash: str = ""                     # Populated by aggregator

    # Core
    title: str
    company: str
    location: Optional[str] = None
    is_remote: bool = False
    country: str = "India"

    # Description
    description: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    experience_years: Optional[int] = None

    # Compensation
    salary_raw: Optional[str] = None
    salary_min_lpa: Optional[float] = None
    salary_max_lpa: Optional[float] = None
    salary_band: SalaryBand = SalaryBand.UNKNOWN

    # Meta
    source: JobSource
    url: str
    apply_url: Optional[str] = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    posted_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool = True

    # Company
    company_tier: CompanyTier = CompanyTier.TIER5_OTHER
    company_size: Optional[str] = None
    company_domain: Optional[str] = None

    @field_validator("title", "company")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()

    def to_db_dict(self) -> dict:
        """Convert to dict suitable for asyncpg DB insert."""
        data = self.model_dump()
        data["id"] = str(data["id"])
        data["source"] = data["source"].value if data["source"] else None
        data["salary_band"] = data["salary_band"].value if data["salary_band"] else None
        data["company_tier"] = data["company_tier"].value if data["company_tier"] else None
        # Keep datetimes as datetime objects — asyncpg requires them, not ISO strings
        return data


class AIJobScore(BaseModel):
    """Output from the AI scoring engine."""

    job_id: UUID
    total_score: int = Field(ge=0, le=100)

    # Dimension scores
    score_role_seniority: Optional[int] = Field(None, ge=0, le=100)
    score_pm_scope: Optional[int] = Field(None, ge=0, le=100)
    score_domain_match: Optional[int] = Field(None, ge=0, le=100)
    score_leadership: Optional[int] = Field(None, ge=0, le=100)
    score_comp_signal: Optional[int] = Field(None, ge=0, le=100)

    # Qualitative
    role_fit: Optional[str] = None               # 'excellent' | 'good' | 'fair' | 'poor'
    compensation_probability: Optional[str] = None
    leadership_level: Optional[str] = None
    estimated_salary_band: Optional[SalaryBand] = None

    # Reasoning
    notes: Optional[str] = None
    fit_tags: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    keywords_matched: list[str] = Field(default_factory=list)

    # Meta
    scored_at: datetime = Field(default_factory=datetime.utcnow)
    model_used: Optional[str] = None
    prompt_version: str = "v1"


class ResumeArtifact(BaseModel):
    """Generated resume and application materials for a specific job."""

    job_id: UUID
    resume_markdown: Optional[str] = None
    resume_pdf_path: Optional[str] = None
    cover_letter: Optional[str] = None
    recruiter_message: Optional[str] = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    model_used: Optional[str] = None


class Application(BaseModel):
    """Job application lifecycle tracking."""

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    status: ApplicationStatus = ApplicationStatus.SHORTLISTED
    priority: int = Field(default=3, ge=1, le=5)
    resume_version: Optional[str] = None
    cover_letter_path: Optional[str] = None
    applied_at: Optional[datetime] = None
    applied_via: Optional[str] = None
    referral_contact: Optional[str] = None
    recruiter_name: Optional[str] = None
    recruiter_email: Optional[str] = None
    recruiter_linkedin: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class OpportunityView(BaseModel):
    """Joined view used by the dashboard — job + score + application status."""

    id: UUID
    title: str
    company: str
    location: Optional[str]
    is_remote: bool
    salary_band: SalaryBand
    salary_min_lpa: Optional[float]
    salary_max_lpa: Optional[float]
    source: JobSource
    url: str
    posted_at: Optional[datetime]
    scraped_at: datetime
    company_tier: CompanyTier

    # Score
    total_score: Optional[int]
    role_fit: Optional[str]
    compensation_probability: Optional[str]
    leadership_level: Optional[str]
    fit_tags: list[str] = Field(default_factory=list)
    ai_notes: Optional[str]

    # Application
    application_status: Optional[ApplicationStatus] = None

    @property
    def score_label(self) -> str:
        if self.total_score is None:
            return "Unscored"
        if self.total_score >= 85:
            return "Excellent"
        if self.total_score >= 70:
            return "Good"
        if self.total_score >= 55:
            return "Fair"
        return "Low"
