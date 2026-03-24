import asyncio
import os
import requests
from dotenv import load_dotenv
from browser_use import Agent, Browser
from browser_use.llm import ChatGoogle
from playwright.async_api import async_playwright
from google.cloud import storage
import uuid

from errors import (
    AgentError,
    get_logger,
    serp_no_results,
    site_blocked,
    pdf_not_found,
    pdf_invalid,
    gcs_failure,
    agent_timeout,
    network_error,
    unknown_error,
)

load_dotenv()
logger = get_logger()

BLOCK_STATUS_CODES = {403, 429, 503}

# ------------------------------------------------------------
# 🔎 GOOGLE CLOUD BUCKET UPLOAD
# ------------------------------------------------------------

def upload_to_gcs(pdf_bytes: bytes, brand: str = "", sku: str = "") -> str:
    try:
        client = storage.Client()
        bucket = client.bucket("brand-agent-pdfs")
        filename = f"{uuid.uuid4()}.pdf"
        blob = bucket.blob(filename)
        blob.upload_from_string(pdf_bytes, content_type="application/pdf")
        logger.info("GCS upload successful", extra={"brand": brand, "sku": sku, "blob": filename})
        return filename
    except Exception as exc:
        err = gcs_failure(brand, sku, exc)
        err.log()
        raise err from exc


# ------------------------------------------------------------
# 🔎 SERP DISCOVERY (No CAPTCHA Google UI)
# ------------------------------------------------------------
def serp_discover_url(brand: str, sku: str):
    serp_key = os.getenv("SERP_API_KEY")
    if not serp_key:
        return None

    query = f'"{brand}" "{sku}"'

    params = {
        "engine": "google",
        "q": query,
        "api_key": serp_key,
        "num": 5
    }

    try:
        r = requests.get("https://serpapi.com/search.json", params=params, timeout=20)
        data = r.json()

        if "organic_results" in data:
            for result in data["organic_results"]:
                link = result.get("link")
                if link:
                    return link

    except Exception:
        return None

    return None


# ------------------------------------------------------------
# 📥 Direct PDF Download
# ------------------------------------------------------------
async def download_direct_pdf(pdf_url: str, brand: str = "", sku: str = ""):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

    try:
        r = requests.get(pdf_url, headers=headers, timeout=60)
    except requests.ConnectionError as exc:
        err = network_error(brand, sku, pdf_url, exc)
        err.log()
        raise err from exc
    except requests.Timeout as exc:
        err = agent_timeout(brand, sku, exc)
        err.log()
        raise err from exc
    except requests.RequestException as exc:
        err = unknown_error(brand, sku, "direct_download", exc)
        err.log()
        raise err from exc

    # --- ORIGINAL DIAGNOSTIC LOGS (kept exactly as-is) ---
    print(f"DIAGNOSTIC: Status {r.status_code}")
    print(f"DIAGNOSTIC: Type {r.headers.get('Content-Type')}")
    print(f"DIAGNOSTIC: Real Size {len(r.content)} bytes")
    # ------------------------------------------------------

    if r.status_code in BLOCK_STATUS_CODES:
        err = site_blocked(brand, sku, pdf_url, status_code=r.status_code)
        err.log()
        raise err

    if r.status_code == 200:
        pdf_bytes = r.content

        # Validate it's actually a PDF before uploading
        if not pdf_bytes.startswith(b"%PDF"):
            err = pdf_invalid(brand, sku, size_bytes=len(pdf_bytes),
                              content_type=r.headers.get("Content-Type", ""))
            err.log()
            raise err

        return upload_to_gcs(pdf_bytes, brand, sku)

    # Any other non-200 status
    err = unknown_error(brand, sku, "direct_download", Exception(f"HTTP {r.status_code}"))
    err.log()
    raise err


# ------------------------------------------------------------
# 🌐 Playwright PDF Interception (Bosch-proof)
# ------------------------------------------------------------
async def download_pdf_from_product_page(product_url: str, brand: str = "", sku: str = ""):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()

            await page.goto(product_url)

            try:
                await page.click("text=Accept all", timeout=5000)
            except:
                pass

            await page.wait_for_timeout(3000)

            link = page.locator("a:has-text('Product data sheet')")

            # Check the link actually exists before clicking
            count = await link.count()
            if count == 0:
                await browser.close()
                err = pdf_not_found(brand, sku, product_url)
                err.log()
                raise err

            await link.first.scroll_into_view_if_needed()

            async with page.expect_download() as download_info:
                await link.first.click(force=True)

            download = await download_info.value

            # Read downloaded file into memory
            download_path = await download.path()
            with open(download_path, "rb") as f:
                pdf_bytes = f.read()

            await browser.close()

            blob_name = upload_to_gcs(pdf_bytes, brand, sku)
            return blob_name

    except AgentError:
        raise  # Already classified — don't double-wrap

    except asyncio.TimeoutError as exc:
        err = agent_timeout(brand, sku, exc)
        err.log()
        raise err from exc

    except Exception as exc:
        # Heuristic classification from Playwright exception messages
        msg = str(exc).lower()
        if "timeout" in msg:
            err = pdf_not_found(brand, sku, product_url, exc)
        elif "net::" in msg or "connection" in msg:
            err = network_error(brand, sku, product_url, exc)
        elif "403" in msg or "blocked" in msg:
            err = site_blocked(brand, sku, product_url, exc=exc)
        else:
            err = unknown_error(brand, sku, "playwright", exc)
        err.log()
        raise err from exc


# ------------------------------------------------------------
# 🚀 MAIN FETCH FUNCTION
# ------------------------------------------------------------
async def fetch_oem_pdf(brand: str, sku: str):
    logger.info("Pipeline started", extra={"brand": brand, "sku": sku})

    try:
        # Step 1 — Try SERP discovery first
        discovered_url = serp_discover_url(brand, sku)

        if discovered_url:
            product_url = discovered_url.strip()
        else:
            # Fallback to browser-use agent if SERP fails
            api_key = os.getenv("GOOGLE_API_KEY")

            llm = ChatGoogle(
                model="gemini-2.0-flash",
                api_key=api_key
            )

            browser = Browser()

            task = f"""
            Go to {brand} website.

            Search for this product SKU: {sku}

            If you find a direct PDF datasheet link (ends with .pdf),
            return ONLY that PDF URL immediately.

            Otherwise, open the correct product page.

            Once you are on the product page, copy the full product page URL
            and return ONLY the URL in the final answer.
            """

            try:
                agent = Agent(task=task, llm=llm, browser=browser)
                history = await agent.run()
                result = history.final_result()

                if not result:
                    err = serp_no_results(brand, sku)
                    err.log()
                    raise err

                product_url = result.strip()

            except AgentError:
                raise

            except asyncio.TimeoutError as exc:
                err = agent_timeout(brand, sku, exc)
                err.log()
                raise err from exc

            except Exception as exc:
                err = unknown_error(brand, sku, "browser_agent", exc)
                err.log()
                raise err from exc

        # Step 2 — Use your existing download logic
        if product_url.lower().endswith(".pdf"):
            return await download_direct_pdf(product_url, brand, sku)

        return await download_pdf_from_product_page(product_url, brand, sku)

    except AgentError:
        raise  # Already classified — let it propagate

    except Exception as exc:
        # Catch anything that slipped through (e.g. crash in serp_discover_url)
        err = unknown_error(brand, sku, "pipeline", exc)
        err.log()
        raise err from exc


if __name__ == "__main__":
    print(asyncio.run(fetch_oem_pdf("Bosch Professional", "PRO GCL 12V-50-22 CG")))
    #print(asyncio.run(fetch_oem_pdf("Trane", "cvhe")))