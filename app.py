"""
app.py — Streamlit UI for OEM PDF Fetch Agent
---------------------------------------------
Error display pattern:
  - Users see: friendly plain-English message + icon
  - Internal/demo users can expand "Technical Details" for the classified error
  - Cloud Run logs contain full structured context (written in agent.py / errors.py)
"""

import sys
import asyncio
import streamlit as st
import base64
import io
import fitz  # PyMuPDF

from agent import fetch_oem_pdf
from errors import AgentError, get_logger
from google.cloud import storage

logger = get_logger()

# ── Session state init ────────────────────────────────────────────────────────
if "pdf_data" not in st.session_state:
    st.session_state.pdf_data = None
if "pdf_filename" not in st.session_state:
    st.session_state.pdf_filename = None

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="OEM PDF Fetch Agent", layout="wide")
st.title("🔎 OEM PDF Fetch Agent")

brand = st.text_input("Brand Name (e.g., Trane, Bosch)")
sku   = st.text_input("Product SKU")


# ── Helpers ───────────────────────────────────────────────────────────────────
def run_async_safely(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def show_error(agent_err: AgentError) -> None:
    """
    Show a non-technical error card to the user.
    Collapsible expander reveals technical detail for internal/demo use.
    """
    st.error(f"❌  {agent_err.user_message}")

    with st.expander("🔧 Technical details (for support use)", expanded=False):
        st.markdown(f"""
| Field | Value |
|---|---|
| Error code | `{agent_err.code.value}` |
| Stage | `{agent_err.stage}` |
| Detail | {agent_err.technical_detail} |
""")


def show_generic_error(exc: Exception) -> None:
    """Fallback for truly unexpected errors that weren't classified."""
    st.error(
        "❌  Something unexpected went wrong. Please try again. "
        "If this keeps happening, contact support."
    )
    with st.expander("🔧 Technical details (for support use)", expanded=False):
        st.markdown(f"**Exception:** `{type(exc).__name__}: {exc}`")


def display_pdf_results(pdf_bytes: bytes) -> None:
    st.divider()
    st.subheader("📄 Results")

    col1, col2 = st.columns([1, 2])

    with col1:
        st.info(f"File Size: {len(pdf_bytes) / 1024 / 1024:.2f} MB")
        st.download_button(
            label="📥 Download Full Document",
            data=pdf_bytes,
            file_name=f"{st.session_state.pdf_filename}.pdf",
            mime="application/pdf",
        )

    with st.expander("🔍 Preview (First 2 Pages)", expanded=True):
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            page_count = len(doc)
            st.write(f"Total pages in full document: **{page_count}**")

            preview_doc = fitz.open()
            end_page = min(1, page_count - 1)
            preview_doc.insert_pdf(doc, from_page=0, to_page=end_page)
            preview_bytes = preview_doc.tobytes()  # tobytes() replaces deprecated write()

            b64 = base64.b64encode(preview_bytes).decode("utf-8")
            st.markdown(
                f'<iframe src="data:application/pdf;base64,{b64}" '
                f'width="100%" height="700px" style="border:none;"></iframe>',
                unsafe_allow_html=True,
            )
            doc.close()
            preview_doc.close()
        except Exception as exc:
            st.warning(f"Preview could not be rendered: {exc}")


# ── Main logic ────────────────────────────────────────────────────────────────
if st.button("🚀 Run Agent"):
    if brand and sku:
        # Clear previous result so stale data doesn't linger on error
        st.session_state.pdf_data = None
        st.session_state.pdf_filename = None

        with st.spinner(f"Searching for {brand} — {sku}…"):
            try:
                # ── 1. Run the agent pipeline ──────────────────────────────
                blob_name = run_async_safely(fetch_oem_pdf(brand, sku))

                # ── 2. Pull PDF bytes from GCS ──────────────────────────────
                try:
                    client = storage.Client()
                    bucket = client.bucket("brand-agent-pdfs")
                    blob   = bucket.blob(blob_name)
                    pdf_bytes = blob.download_as_bytes()
                except Exception as exc:
                    from errors import gcs_failure
                    err = gcs_failure(brand, sku, exc)
                    err.log()
                    show_error(err)
                    st.stop()

                # ── 3. Store in session state ───────────────────────────────
                st.session_state.pdf_data     = pdf_bytes
                st.session_state.pdf_filename = f"{brand.replace(' ', '_')}_{sku}"
                st.success("✅  Document found and ready to download!")

            except AgentError as err:
                # Pipeline raised a classified error — show it properly
                err.log()          # ensure it's in Cloud Run logs
                show_error(err)

            except Exception as exc:
                # Truly unexpected — log it and show generic message
                logger.exception(
                    "Unhandled exception in Streamlit run",
                    extra={"brand": brand, "sku": sku},
                )
                show_generic_error(exc)

    else:
        st.warning("⚠️  Please enter both a brand name and a SKU before running.")

# ── Persistent display ────────────────────────────────────────────────────────
if st.session_state.pdf_data:
    display_pdf_results(st.session_state.pdf_data)