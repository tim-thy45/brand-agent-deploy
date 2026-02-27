import asyncio
import os
import requests
from dotenv import load_dotenv
from browser_use import Agent, Browser
from browser_use.llm import ChatGoogle
from playwright.async_api import async_playwright
from google.cloud import storage
import uuid
load_dotenv()

# ------------------------------------------------------------
# 🔎 GOOGLE CLOUD BUCKET UPLOAD
# ------------------------------------------------------------

def upload_to_gcs(pdf_bytes: bytes) -> str:
    client = storage.Client()
    bucket = client.bucket("brand-agent-pdfs")
    filename = f"{uuid.uuid4()}.pdf"
    blob = bucket.blob(filename)

    blob.upload_from_string(pdf_bytes, content_type="application/pdf")
    
    # Just return the filename so the app knows what to download
    return filename
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
async def download_direct_pdf(pdf_url: str):
    r = requests.get(pdf_url, timeout=30)
    if r.status_code == 200:
        pdf_bytes = r.content
        # CHANGE: Rename variable to blob_name for clarity
        blob_name = upload_to_gcs(pdf_bytes) 
        return blob_name
    else:
        raise Exception(f"Failed to download PDF: {r.status_code}")


# ------------------------------------------------------------
# 🌐 Playwright PDF Interception (Bosch-proof)
# ------------------------------------------------------------
async def download_pdf_from_product_page(product_url: str):
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
        await link.first.scroll_into_view_if_needed()

        async with page.expect_download() as download_info:
            await link.first.click(force=True)

        download = await download_info.value

        # Read downloaded file into memory
        download_path = await download.path()
        with open(download_path, "rb") as f:
            pdf_bytes = f.read()

        await browser.close()

        # CHANGE: Rename variable to blob_name and return it
        blob_name = upload_to_gcs(pdf_bytes)
        return blob_name

# ------------------------------------------------------------
# 🚀 MAIN FETCH FUNCTION
# ------------------------------------------------------------
async def fetch_oem_pdf(brand: str, sku: str):

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

        agent = Agent(task=task, llm=llm, browser=browser)
        history = await agent.run()
        product_url = history.final_result().strip()

    # Step 2 — Use your existing download logic

    if product_url.lower().endswith(".pdf"):
        return await download_direct_pdf(product_url)

    return await download_pdf_from_product_page(product_url)


if __name__ == "__main__":
    print(asyncio.run(fetch_oem_pdf("Bosch Professional", "PRO GCL 12V-50-22 CG")))
    #print(asyncio.run(fetch_oem_pdf("Trane", "cvhe")))