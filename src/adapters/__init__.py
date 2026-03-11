# OSS Adapter Layer
# Exposes modular adapters wrapping open-source patterns for job search automation.

from .easy_apply_engine import ApplyResult, EasyApplyConfig, EasyApplyEngine
from .pdf_resume_engine import PDFResumeEngine

__all__ = [
    "EasyApplyEngine",
    "EasyApplyConfig",
    "ApplyResult",
    "PDFResumeEngine",
]
