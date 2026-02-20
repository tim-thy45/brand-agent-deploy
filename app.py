import asyncio
import sys

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


import streamlit as st
import asyncio
from agent import fetch_oem_pdf

st.title("OEM PDF Fetch Agent")

brand = st.text_input("Brand Name")
sku = st.text_input("Product SKU")

if st.button("Run Agent"):
    if brand and sku:
        with st.spinner("Running agent..."):
            try:
                file_path = asyncio.run(fetch_oem_pdf(brand, sku))
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
