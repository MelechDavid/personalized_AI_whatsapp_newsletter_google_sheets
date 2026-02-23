"""
Streamlit Dashboard for WhatsApp message sending.

Run with: streamlit run execution/dashboard.py
"""

import sys
import time
import threading
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from execution.send_messages import run_send_loop, SessionState
from execution.google_sheets import extract_sheet_id

# Page config
st.set_page_config(
    page_title="WhatsApp Sender",
    layout="wide",
)

st.title("WhatsApp Message Sender")
st.caption("Send personalized WhatsApp messages with image from Google Sheet contacts")

# Initialize session state
if "session" not in st.session_state:
    st.session_state.session = SessionState()
if "thread" not in st.session_state:
    st.session_state.thread = None

session: SessionState = st.session_state.session


# --- Sidebar: Controls ---
with st.sidebar:
    st.header("Configuration")

    sheet_url = st.text_input(
        "Google Sheet URL (optional)",
        value="",
        placeholder="https://docs.google.com/spreadsheets/d/.../edit",
        help="Paste a Google Sheet link to override the default sheet. Leave empty to use the default.",
        disabled=session.is_running,
    )

    override_sheet_id = None
    if sheet_url.strip():
        override_sheet_id = extract_sheet_id(sheet_url.strip())
        if override_sheet_id is None:
            st.error("Invalid Google Sheet URL. Expected format: https://docs.google.com/spreadsheets/d/SHEET_ID/...")

    msg_count = st.number_input(
        "Number of messages to send",
        min_value=1,
        max_value=45,
        value=10,
        step=1,
        help="Maximum 45 per day to avoid WhatsApp restrictions",
    )

    delay = st.slider(
        "Delay between messages (seconds)",
        min_value=15,
        max_value=120,
        value=30,
        step=5,
        help="Longer delays reduce risk of being flagged",
    )

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        start_disabled = session.is_running
        if st.button("Start Sending", disabled=start_disabled, type="primary", use_container_width=True):
            st.session_state.session = SessionState()
            session = st.session_state.session

            def _run():
                run_send_loop(
                    count=msg_count,
                    delay=delay,
                    state=session,
                    sheet_id=override_sheet_id,
                )

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()
            st.session_state.thread = thread
            st.rerun()

    with col2:
        stop_disabled = not session.is_running
        if st.button("Stop", disabled=stop_disabled, type="secondary", use_container_width=True):
            session.should_stop = True
            st.rerun()

    if session.is_running:
        if session.is_paused:
            if st.button("Resume", use_container_width=True):
                session.is_paused = False
                st.rerun()
        else:
            if st.button("Pause", use_container_width=True):
                session.is_paused = True
                st.rerun()

    st.divider()
    st.markdown("**Setup checklist:**")
    st.markdown("1. Google OAuth completed (run `google_sheets.py` first)")
    st.markdown("2. Chrome launches automatically when you click Start")
    st.markdown("3. First run: scan WhatsApp QR code when Chrome opens")


# --- Main area: Progress ---
if session.is_running or session.sent > 0 or session.failed > 0:

    if session.is_running:
        if session.is_paused:
            st.warning("PAUSED")
        else:
            if session.current_contact:
                st.info(f"Sending to: **{session.current_contact}** ({session.current_phone})")
            else:
                st.info("Initializing...")
    else:
        if session.sent > 0 or session.failed > 0:
            st.success("Session complete!")

    # Progress bar
    total = max(session.total, 1)
    progress = (session.sent + session.failed) / total
    st.progress(min(progress, 1.0))

    # Stats
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", session.total)
    c2.metric("Sent", session.sent)
    c3.metric("Failed", session.failed)
    c4.metric("Remaining", session.remaining)

    st.divider()

# --- Activity log ---
st.subheader("Activity Log")

log_container = st.container(height=400)

with log_container:
    if session.log_messages:
        for msg in reversed(session.log_messages):
            if "ERROR" in msg or "FAILED" in msg:
                st.markdown(f":red[{msg}]")
            elif "Sent successfully" in msg:
                st.markdown(f":green[{msg}]")
            elif "Waiting" in msg:
                st.markdown(f":gray[{msg}]")
            else:
                st.text(msg)
    else:
        st.caption("No activity yet. Configure settings in the sidebar and click Start Sending.")

# Auto-refresh while running
if session.is_running:
    time.sleep(2)
    st.rerun()
