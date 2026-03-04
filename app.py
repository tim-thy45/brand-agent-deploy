import sys
import asyncio
import streamlit as st
from agent import fetch_oem_pdf
import requests
from google.cloud import storage
import base64
import fitz  # PyMuPDF
import io

# Initialize session state so data persists across reruns
if "pdf_data" not in st.session_state:
    st.session_state.pdf_data = None
if "pdf_filename" not in st.session_state:
    st.session_state.pdf_filename = None

st.set_page_config(page_title="OEM PDF Fetch Agent", layout="wide")
st.title("🔎 OEM PDF Fetch Agent")

brand = st.text_input("Brand Name (e.g., Trane, Bosch)")
sku = st.text_input("Product SKU")

def run_async_safely(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

def display_pdf_results(pdf_bytes):
    st.divider()
    st.subheader("📄 Results")
    
    # --- VALIDATION: Check if it's actually a PDF ---
    # If the file starts with <HTML, Trane blocked the bot
    if not pdf_bytes.startswith(b"%PDF"):
        st.error("🚨 ERROR: The captured file is a webpage, not a PDF.")
        st.warning("Trane's firewall likely blocked the direct download. Re-run with Playwright enabled.")
        return

    col1, col2 = st.columns([1, 2])

    with col1:
        st.info(f"File Size: {len(pdf_bytes) / 1024 / 1024:.2f} MB")
        # 1. Provide the Full Download (Guaranteed to work if bytes are valid)
        st.download_button(
            label="📥 Download Full Document",
            data=pdf_bytes,
            file_name=f"{st.session_state.pdf_filename}.pdf",
            mime="application/pdf"
        )

    # 2. Extract First 2 Pages for a Fast Preview
    with st.expander("🔍 View Preview (First 2 Pages Only)", expanded=True):
        try:
            # Open PDF from memory
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            page_count = len(doc)
            st.write(f"Total Pages in Full Document: **{page_count}**")

            # Create a tiny 2-page subset for the browser preview
            preview_doc = fitz.open()
            end_page = min(1, page_count - 1) # Page 0 and Page 1
            preview_doc.insert_pdf(doc, from_page=0, to_page=end_page)
            
            preview_bytes = preview_doc.write()
            
            # Encode tiny preview to Base64
            base64_pdf = base64.b64encode(preview_bytes).decode('utf-8')
            pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="700px" style="border:none;"></iframe>'
            st.markdown(pdf_display, unsafe_allow_html=True)
            
            doc.close()
            preview_doc.close()
            
        except Exception as e:
            st.error(f"Preview rendering failed: {e}")

# --- MAIN LOGIC ---
if st.button("🚀 Run Agent"):
    if brand and sku:
        with st.spinner(f"Agent searching for {brand} {sku}..."):
            try:
                # 1. Get blob name from agent
                blob_name = run_async_safely(fetch_oem_pdf(brand, sku))

                # 2. Pull from GCS
                client = storage.Client()
                bucket = client.bucket("brand-agent-pdfs")
                blob = bucket.blob(blob_name)
                
                pdf_bytes = blob.download_as_bytes()
                
                # 3. Store in session state
                st.session_state.pdf_data = pdf_bytes
                st.session_state.pdf_filename = f"{brand.replace(' ', '_')}_{sku}"
                
                st.success("Document captured successfully!")

            except Exception as e:
                st.error(f"Agent Error: {str(e)}")
    else:
        st.warning("Please enter both Brand and SKU.")

# Persistence: Display if data exists
if st.session_state.pdf_data:
    display_pdf_results(st.session_state.pdf_data)