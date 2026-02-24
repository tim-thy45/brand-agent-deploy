import sys
import asyncio
import streamlit as st
from agent import fetch_oem_pdf

# Windows compatibility (safe to keep)
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

st.title("OEM PDF Fetch Agent")

brand = st.text_input("Brand Name")
sku = st.text_input("Product SKU")


def run_async_safely(coro):
    """
    Runs async function in a fresh event loop.
    Safe for Streamlit + Cloud Run.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


if st.button("Run Agent"):
    if brand and sku:
        with st.spinner("Running agent..."):
            try:
                file_path = run_async_safely(fetch_oem_pdf(brand, sku))

                st.success("PDF downloaded successfully!")

                with open(file_path, "rb") as f:
                    pdf_bytes = f.read()

                st.download_button(
                    label="Download PDF",
                    data=pdf_bytes,
                    file_name=file_path.split("/")[-1],
                    mime="application/pdf"
                )

            except Exception as e:
                st.error(str(e))