import sys
import asyncio
import streamlit as st
from agent import fetch_oem_pdf
import requests
from google.cloud import storage
import base64

# Initialize session state so data persists across reruns
if "pdf_data" not in st.session_state:
    st.session_state.pdf_data = None
if "pdf_filename" not in st.session_state:
    st.session_state.pdf_filename = None

st.title("OEM PDF Fetch Agent")
brand = st.text_input("Brand Name")
sku = st.text_input("Product SKU")

def run_async_safely(coro):
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
                blob_name = run_async_safely(fetch_oem_pdf(brand, sku))

                client = storage.Client()
                bucket = client.bucket("brand-agent-pdfs")
                blob = bucket.blob(blob_name)
                
                # Fetch the bytes
                pdf_bytes = blob.download_as_bytes()
                st.session_state.pdf_data = pdf_bytes
                
                st.success(f"PDF retrieved!")

            except Exception as e:
                st.error(f"Error: {str(e)}")

# DISPLAY THE PDF ON THE WEBSITE
if st.session_state.pdf_data:
    st.subheader("Preview Datasheet")
    
    # Encode bytes to base64 for embedding
    base64_pdf = base64.b64encode(st.session_state.pdf_data).decode('utf-8')
    
    # Create an HTML iframe to display the PDF
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800" type="application/pdf"></iframe>'
    
    # Render the iframe
    st.markdown(pdf_display, unsafe_allow_html=True)