"""
errors.py — Centralized error classification for OEM PDF Agent
--------------------------------------------------------------
All pipeline errors flow through this module.
- Users see: friendly_message (plain English)
- Cloud Run sees: full structured log with traceback + context
"""

import logging
import traceback
import json
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

# ── Structured JSON logger (Cloud Run parses this natively) ──────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        # Merge any extra fields passed via record.__dict__
        for key, val in record.__dict__.items():
            if key not in (
                "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "name", "taskName",
            ):
                log_obj[key] = val
        if record.exc_info:
            log_obj["traceback"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


def get_logger(name: str = "brand-agent") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger


logger = get_logger()


# ── Error types ──────────────────────────────────────────────────────────────
class ErrorCode(str, Enum):
    SERP_NO_RESULTS   = "SERP_NO_RESULTS"
    SERP_WRONG_DOMAIN = "SERP_WRONG_DOMAIN"
    SITE_BLOCKED      = "SITE_BLOCKED"
    PDF_NOT_FOUND     = "PDF_NOT_FOUND"
    PDF_INVALID       = "PDF_INVALID"
    GCS_FAILURE       = "GCS_FAILURE"
    AGENT_TIMEOUT     = "AGENT_TIMEOUT"
    NETWORK_ERROR     = "NETWORK_ERROR"
    UNKNOWN           = "UNKNOWN"


# ── User-facing messages (plain English, no jargon) ──────────────────────────
_USER_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.SERP_NO_RESULTS: (
        "We couldn't find that product online. "
        "Please double-check the brand name and SKU, then try again."
    ),
    ErrorCode.SERP_WRONG_DOMAIN: (
        "The search returned a third-party retailer page instead of the "
        "manufacturer's website. Try being more specific with the brand name."
    ),
    ErrorCode.SITE_BLOCKED: (
        "The manufacturer's website blocked the automated search. "
        "This sometimes happens with high-traffic sites — please try again in a few minutes."
    ),
    ErrorCode.PDF_NOT_FOUND: (
        "We reached the product page but couldn't find a downloadable datasheet. "
        "The document may not be available online, or the page layout may have changed."
    ),
    ErrorCode.PDF_INVALID: (
        "A file was downloaded but it doesn't appear to be a valid PDF. "
        "The site may have returned an error page instead."
    ),
    ErrorCode.GCS_FAILURE: (
        "There was a storage error on our end — the document couldn't be saved. "
        "Please try again. If this keeps happening, contact support."
    ),
    ErrorCode.AGENT_TIMEOUT: (
        "The search took too long and was stopped automatically. "
        "The manufacturer's website may be slow or complex. Please try again."
    ),
    ErrorCode.NETWORK_ERROR: (
        "A network error occurred while trying to reach the website. "
        "Please check your connection and try again."
    ),
    ErrorCode.UNKNOWN: (
        "Something unexpected went wrong. "
        "Please try again — if the problem persists, contact support."
    ),
}


# ── The exception class the whole pipeline raises ────────────────────────────
@dataclass
class AgentError(Exception):
    """
    Raised at any stage of the pipeline.
    Carry both the user-friendly message and full technical context.
    """
    code: ErrorCode
    technical_detail: str                    # shown in Streamlit expander
    brand: str = ""
    sku: str = ""
    stage: str = ""                          # e.g. "serp", "playwright", "gcs"
    original_exception: Optional[Exception] = field(default=None, repr=False)

    # ── Human-readable user message (derived from code) ──────────────────
    @property
    def user_message(self) -> str:
        return _USER_MESSAGES.get(self.code, _USER_MESSAGES[ErrorCode.UNKNOWN])

    # ── Log this error to Cloud Run with full context ─────────────────────
    def log(self) -> None:
        extra = {
            "error_code": self.code.value,
            "stage": self.stage,
            "brand": self.brand,
            "sku": self.sku,
            "technical_detail": self.technical_detail,
        }
        if self.original_exception:
            logger.error(
                f"[{self.code.value}] {self.technical_detail}",
                exc_info=(
                    type(self.original_exception),
                    self.original_exception,
                    self.original_exception.__traceback__,
                ),
                extra=extra,
            )
        else:
            logger.error(f"[{self.code.value}] {self.technical_detail}", extra=extra)

    def __str__(self) -> str:
        return f"AgentError({self.code.value}) @ {self.stage}: {self.technical_detail}"


# ── Convenience constructors ─────────────────────────────────────────────────
def serp_no_results(brand: str, sku: str) -> AgentError:
    return AgentError(
        code=ErrorCode.SERP_NO_RESULTS,
        technical_detail=f"SERP returned zero organic results for query: \"{brand}\" \"{sku}\"",
        brand=brand, sku=sku, stage="serp",
    )

def serp_wrong_domain(brand: str, sku: str, url: str) -> AgentError:
    return AgentError(
        code=ErrorCode.SERP_WRONG_DOMAIN,
        technical_detail=f"Top SERP result domain does not match brand. URL: {url}",
        brand=brand, sku=sku, stage="serp",
    )

def site_blocked(brand: str, sku: str, url: str, status_code: int = 0, exc: Exception = None) -> AgentError:
    detail = f"Site returned HTTP {status_code} (bot block suspected). URL: {url}" if status_code else f"Site blocked access. URL: {url}"
    return AgentError(
        code=ErrorCode.SITE_BLOCKED,
        technical_detail=detail,
        brand=brand, sku=sku, stage="download",
        original_exception=exc,
    )

def pdf_not_found(brand: str, sku: str, url: str, exc: Exception = None) -> AgentError:
    return AgentError(
        code=ErrorCode.PDF_NOT_FOUND,
        technical_detail=f"No datasheet link located on page. URL: {url}",
        brand=brand, sku=sku, stage="playwright",
        original_exception=exc,
    )

def pdf_invalid(brand: str, sku: str, size_bytes: int = 0, content_type: str = "") -> AgentError:
    return AgentError(
        code=ErrorCode.PDF_INVALID,
        technical_detail=f"Downloaded file failed PDF validation. Size: {size_bytes}B, Content-Type: {content_type}",
        brand=brand, sku=sku, stage="validation",
    )

def gcs_failure(brand: str, sku: str, exc: Exception) -> AgentError:
    return AgentError(
        code=ErrorCode.GCS_FAILURE,
        technical_detail=f"GCS upload/download failed: {type(exc).__name__}: {exc}",
        brand=brand, sku=sku, stage="gcs",
        original_exception=exc,
    )

def agent_timeout(brand: str, sku: str, exc: Exception = None) -> AgentError:
    return AgentError(
        code=ErrorCode.AGENT_TIMEOUT,
        technical_detail="browser-use agent exceeded timeout limit",
        brand=brand, sku=sku, stage="agent",
        original_exception=exc,
    )

def network_error(brand: str, sku: str, url: str, exc: Exception) -> AgentError:
    return AgentError(
        code=ErrorCode.NETWORK_ERROR,
        technical_detail=f"Network error reaching {url}: {type(exc).__name__}: {exc}",
        brand=brand, sku=sku, stage="download",
        original_exception=exc,
    )

def unknown_error(brand: str, sku: str, stage: str, exc: Exception) -> AgentError:
    return AgentError(
        code=ErrorCode.UNKNOWN,
        technical_detail=f"Unhandled exception in stage '{stage}': {type(exc).__name__}: {exc}",
        brand=brand, sku=sku, stage=stage,
        original_exception=exc,
    )