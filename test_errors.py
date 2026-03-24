"""
test_errors.py — Local error handling tests
Run with: python test_errors.py
No deployment needed.
"""

import sys
from unittest.mock import MagicMock, AsyncMock

# ── Stub out packages that aren't installed locally ──────────────────────────
# Must happen BEFORE agent.py is imported, otherwise Python fails at the
# top-level imports inside agent.py
sys.modules["browser_use"]          = MagicMock()
sys.modules["browser_use.llm"]      = MagicMock()
sys.modules["playwright"]           = MagicMock()
sys.modules["playwright.async_api"] = MagicMock()
sys.modules["google.cloud"]         = MagicMock()
sys.modules["google.cloud.storage"] = MagicMock()
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
from unittest.mock import patch
from errors import AgentError, ErrorCode

# ── Helpers ──────────────────────────────────────────────────────────────────

PASS = "✅ PASS"
FAIL = "❌ FAIL"

def check(test_name: str, code: ErrorCode, expected_code: ErrorCode, user_message: str):
    status = PASS if code == expected_code else FAIL
    print(f"{status} | {test_name}")
    print(f"       Error code    : {code.value}")
    print(f"       User message  : {user_message}")
    print()

# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_pdf_invalid():
    """Site returns HTML instead of a real PDF."""
    from agent import download_direct_pdf

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"<html>This is not a PDF</html>"
    mock_response.headers = {"Content-Type": "text/html"}

    with patch("agent.requests.get", return_value=mock_response):
        try:
            await download_direct_pdf("https://fake.com/fake.pdf", "TestBrand", "SKU123")
            print(f"{FAIL} | PDF_INVALID — no error was raised\n")
        except AgentError as e:
            check("PDF_INVALID", e.code, ErrorCode.PDF_INVALID, e.user_message)


async def test_site_blocked_403():
    """Site returns 403 — bot block."""
    from agent import download_direct_pdf

    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.content = b""
    mock_response.headers = {"Content-Type": "text/html"}

    with patch("agent.requests.get", return_value=mock_response):
        try:
            await download_direct_pdf("https://fake.com/fake.pdf", "TestBrand", "SKU123")
            print(f"{FAIL} | SITE_BLOCKED — no error was raised\n")
        except AgentError as e:
            check("SITE_BLOCKED (403)", e.code, ErrorCode.SITE_BLOCKED, e.user_message)


async def test_site_blocked_429():
    """Site returns 429 — rate limited."""
    from agent import download_direct_pdf

    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.content = b""
    mock_response.headers = {"Content-Type": "text/html"}

    with patch("agent.requests.get", return_value=mock_response):
        try:
            await download_direct_pdf("https://fake.com/fake.pdf", "TestBrand", "SKU123")
            print(f"{FAIL} | SITE_BLOCKED (429) — no error was raised\n")
        except AgentError as e:
            check("SITE_BLOCKED (429)", e.code, ErrorCode.SITE_BLOCKED, e.user_message)


async def test_network_error():
    """DNS failure / unreachable host."""
    import requests as req
    from agent import download_direct_pdf

    with patch("agent.requests.get", side_effect=req.ConnectionError("Name resolution failed")):
        try:
            await download_direct_pdf("https://this-does-not-exist.xyz/file.pdf", "TestBrand", "SKU123")
            print(f"{FAIL} | NETWORK_ERROR — no error was raised\n")
        except AgentError as e:
            check("NETWORK_ERROR", e.code, ErrorCode.NETWORK_ERROR, e.user_message)


async def test_agent_timeout():
    """Request times out."""
    import requests as req
    from agent import download_direct_pdf

    with patch("agent.requests.get", side_effect=req.Timeout("Read timed out")):
        try:
            await download_direct_pdf("https://fake.com/fake.pdf", "TestBrand", "SKU123")
            print(f"{FAIL} | AGENT_TIMEOUT — no error was raised\n")
        except AgentError as e:
            check("AGENT_TIMEOUT", e.code, ErrorCode.AGENT_TIMEOUT, e.user_message)


async def test_pdf_not_found():
    """Playwright finds zero matching links on the page."""
    from agent import download_pdf_from_product_page

    # Mock the entire Playwright chain
    mock_link = AsyncMock()
    mock_link.count = AsyncMock(return_value=0)  # <-- no links found

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.click = AsyncMock(side_effect=Exception("not found"))
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.locator = MagicMock(return_value=mock_link)

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_chromium = AsyncMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_playwright = AsyncMock()
    mock_playwright.chromium = mock_chromium
    mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.__aexit__ = AsyncMock(return_value=False)

    with patch("agent.async_playwright", return_value=mock_playwright):
        try:
            await download_pdf_from_product_page("https://fake.com/product", "TestBrand", "SKU123")
            print(f"{FAIL} | PDF_NOT_FOUND — no error was raised\n")
        except AgentError as e:
            check("PDF_NOT_FOUND", e.code, ErrorCode.PDF_NOT_FOUND, e.user_message)


async def test_gcs_failure():
    """GCS upload fails."""
    from agent import upload_to_gcs

    with patch("agent.storage.Client", side_effect=Exception("GCS credentials missing")):
        try:
            upload_to_gcs(b"%PDF-fake", "TestBrand", "SKU123")
            print(f"{FAIL} | GCS_FAILURE — no error was raised\n")
        except AgentError as e:
            check("GCS_FAILURE", e.code, ErrorCode.GCS_FAILURE, e.user_message)


async def test_serp_no_results():
    """Browser-use agent returns an empty result."""
    from agent import fetch_oem_pdf

    # Skip SERP (returns None) so we fall into browser-use agent path
    mock_history = MagicMock()
    mock_history.final_result = MagicMock(return_value="")  # empty result

    mock_agent = AsyncMock()
    mock_agent.run = AsyncMock(return_value=mock_history)

    with patch("agent.serp_discover_url", return_value=None), \
         patch("agent.Agent", return_value=mock_agent):
        try:
            await fetch_oem_pdf("UnknownBrand", "BADSKU999")
            print(f"{FAIL} | SERP_NO_RESULTS — no error was raised\n")
        except AgentError as e:
            check("SERP_NO_RESULTS", e.code, ErrorCode.SERP_NO_RESULTS, e.user_message)


async def test_unknown_error():
    """Completely unexpected exception bubbles up correctly."""
    from agent import fetch_oem_pdf

    with patch("agent.serp_discover_url", side_effect=RuntimeError("something totally unexpected")):
        try:
            await fetch_oem_pdf("TestBrand", "SKU123")
            print(f"{FAIL} | UNKNOWN — no error was raised\n")
        except AgentError as e:
            check("UNKNOWN", e.code, ErrorCode.UNKNOWN, e.user_message)
        except Exception as e:
            print(f"{FAIL} | UNKNOWN — got raw exception instead of AgentError: {e}\n")


# ── Runner ────────────────────────────────────────────────────────────────────

async def run_all():
    print("\n" + "="*60)
    print(" ERROR HANDLING TEST SUITE")
    print("="*60 + "\n")

    tests = [
        test_pdf_invalid,
        test_site_blocked_403,
        test_site_blocked_429,
        test_network_error,
        test_agent_timeout,
        test_pdf_not_found,
        test_gcs_failure,
        test_serp_no_results,
        test_unknown_error,
    ]

    for test in tests:
        try:
            await test()
        except Exception as e:
            print(f"❌ FAIL | {test.__name__} — test itself crashed: {e}\n")

    print("="*60)
    print(" DONE")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(run_all())