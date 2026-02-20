import asyncio
import os
import requests
from dotenv import load_dotenv
from browser_use import Agent, Browser
from browser_use.llm import ChatGoogle
from playwright.async_api import async_playwright

load_dotenv()

async def download_direct_pdf(pdf_url: str):
    filename = pdf_url.split("/")[-1]
    save_path = os.path.join(os.getcwd(), filename)

    r = requests.get(pdf_url)

    if r.status_code == 200:
        with open(save_path, "wb") as f:
            f.write(r.content)
        return save_path
    else:
        raise Exception(f"Failed to download PDF: {r.status_code}")


async def download_pdf_from_product_page(product_url: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)  # IMPORTANT: True for cloud
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(product_url)

        try:
            await page.click("text=Accept all", timeout=5000)
        except:
            pass

        await page.wait_for_timeout(3000)

        link = page.locator("a:has-text('Product data sheet')")
        await link.first.scroll_into_view_if_needed()

        pdf_response_holder = {"response": None}

        def handle_response(response):
            if "application/pdf" in response.headers.get("content-type", ""):
                pdf_response_holder["response"] = response

        context.on("response", handle_response)

        async with page.expect_popup():
            await link.first.click(force=True)

        await page.wait_for_timeout(5000)

        pdf_response = pdf_response_holder["response"]

        if pdf_response is None:
            await browser.close()
            raise Exception("Could not capture PDF")

        pdf_bytes = await pdf_response.body()
        filename = "datasheet_REAL.pdf"
        save_path = os.path.join(os.getcwd(), filename)

        with open(save_path, "wb") as f:
            f.write(pdf_bytes)

        await browser.close()
        return save_path


async def fetch_oem_pdf(brand: str, sku: str):

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

    if product_url.lower().endswith(".pdf"):
        return await download_direct_pdf(product_url)
    else:
        return await download_pdf_from_product_page(product_url)

if __name__ == "__main__": 
    print(asyncio.run(fetch_oem_pdf("Trane", "cvhe")))