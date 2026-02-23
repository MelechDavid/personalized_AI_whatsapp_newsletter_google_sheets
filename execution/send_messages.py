"""
Orchestrator: reads contacts from Google Sheet, sends WhatsApp messages,
and writes results back.

Can be run from CLI or imported by the Streamlit dashboard.
"""

import os
import sys
import time
import json
import random
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from execution.google_sheets import get_pending_contacts, write_status, Contact
from execution.whatsapp_sender import (
    create_driver,
    send_whatsapp_message,
    is_whatsapp_connected,
    ContactNotFoundError,
    SendTimeoutError,
    WhatsAppSendError,
)


@dataclass
class SendResult:
    contact: Contact
    success: bool
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SessionState:
    """Shared state between orchestrator and dashboard."""
    total: int = 0
    sent: int = 0
    failed: int = 0
    remaining: int = 0
    current_contact: Optional[str] = None
    current_phone: Optional[str] = None
    is_running: bool = False
    is_paused: bool = False
    should_stop: bool = False
    log_messages: list = field(default_factory=list)
    results: list = field(default_factory=list)


def _log(state: SessionState, message: str):
    """Add a timestamped log message."""
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {message}"
    state.log_messages.append(entry)
    print(entry)


def _save_log(state: SessionState, results: list[SendResult]):
    """Save session log to .tmp/send_log.json"""
    tmp_dir = PROJECT_ROOT / ".tmp"
    tmp_dir.mkdir(exist_ok=True)

    log_data = {
        "timestamp": datetime.now().isoformat(),
        "sent": state.sent,
        "failed": state.failed,
        "total_attempted": state.sent + state.failed,
        "log": state.log_messages,
        "results": [asdict(r) for r in results],
    }

    log_file = tmp_dir / "send_log.json"
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2, ensure_ascii=False)


def run_send_loop(
    count: int,
    delay: int,
    state: Optional[SessionState] = None,
    on_progress: Optional[Callable] = None,
    sheet_id: Optional[str] = None,
) -> list[SendResult]:
    """
    Main send loop.

    Args:
        count: Number of messages to send (capped at DAILY_MESSAGE_LIMIT)
        delay: Base seconds between messages (jitter added automatically)
        state: Shared SessionState for dashboard integration
        on_progress: Callback after each message attempt
    """
    count = min(count, int(os.getenv("DAILY_MESSAGE_LIMIT", "45")))

    if state is None:
        state = SessionState()

    state.is_running = True
    state.total = count
    state.remaining = count

    template = os.getenv("MESSAGE_TEMPLATE")
    image_path = os.getenv("IMAGE_PATH")

    if not Path(image_path).exists():
        _log(state, f"ERROR: Image not found at {image_path}")
        state.is_running = False
        return []

    results = []
    driver = None

    try:
        # Connect to Chrome (auto-launches if needed)
        _log(state, "Launching Chrome (or connecting to existing)...")
        debug_port = int(os.getenv("CHROME_DEBUG_PORT", "9222"))
        chrome_path = os.getenv("CHROME_PATH")
        profile_dir = str(PROJECT_ROOT / ".tmp" / "chrome-whatsapp")
        driver = create_driver(debug_port, chrome_path=chrome_path, profile_dir=profile_dir)
        _log(state, "Connected to Chrome successfully")

        # Find WhatsApp Web tab
        whatsapp_tab_found = False
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            if "web.whatsapp.com" in driver.current_url:
                whatsapp_tab_found = True
                break

        if not whatsapp_tab_found:
            _log(state, "WhatsApp Web tab not found. Opening it...")
            driver.get("https://web.whatsapp.com")
            time.sleep(5)

        _log(state, "WhatsApp Web is active")

        # Fetch contacts from Google Sheet
        _log(state, f"Fetching {count} pending contacts from Google Sheet...")
        contacts = get_pending_contacts(count, sheet_id=sheet_id)
        actual_count = len(contacts)

        if actual_count == 0:
            _log(state, "No pending contacts found (all rows have status)")
            state.is_running = False
            return []

        if actual_count < count:
            _log(state, f"Found only {actual_count} pending contacts (requested {count})")

        state.total = actual_count
        state.remaining = actual_count
        _log(state, f"Starting to send {actual_count} messages...")

        # Main loop
        for i, contact in enumerate(contacts):
            if state.should_stop:
                _log(state, "Stop requested by user. Halting.")
                break

            while state.is_paused:
                time.sleep(1)
                if state.should_stop:
                    break

            state.current_contact = contact.first_name
            state.current_phone = contact.phone_raw

            _log(state, f"[{i+1}/{actual_count}] Sending to {contact.first_name} ({contact.phone_raw})...")

            caption = template.format(first_name=contact.first_name)

            try:
                success = send_whatsapp_message(
                    driver=driver,
                    phone_clean=contact.phone_clean,
                    caption=caption,
                    image_path=image_path,
                )

                write_status(contact.row_number, True, sheet_id=sheet_id)
                state.sent += 1
                result = SendResult(contact=contact, success=True)
                _log(state, f"  -> Sent successfully to {contact.first_name}")

            except ContactNotFoundError as e:
                write_status(contact.row_number, False, sheet_id=sheet_id)
                state.failed += 1
                result = SendResult(contact=contact, success=False, error=str(e))
                _log(state, f"  -> FAILED: Contact not on WhatsApp ({contact.phone_raw})")

            except (SendTimeoutError, WhatsAppSendError) as e:
                write_status(contact.row_number, False, sheet_id=sheet_id)
                state.failed += 1
                result = SendResult(contact=contact, success=False, error=str(e))
                _log(state, f"  -> FAILED: {str(e)}")

            except Exception as e:
                state.failed += 1
                result = SendResult(contact=contact, success=False, error=str(e))
                _log(state, f"  -> ERROR (unexpected): {str(e)}")

                if not is_whatsapp_connected(driver):
                    _log(state, "WhatsApp Web disconnected! Stopping.")
                    break

            results.append(result)
            state.results.append(asdict(result))
            state.remaining -= 1

            if on_progress:
                on_progress(state)

            # Delay with jitter (skip after last message)
            if i < actual_count - 1 and not state.should_stop:
                jitter = random.uniform(-5, 10)
                actual_delay = max(20, delay + jitter)
                _log(state, f"  Waiting {actual_delay:.0f}s before next message...")
                for _ in range(int(actual_delay)):
                    if state.should_stop:
                        break
                    time.sleep(1)

    except Exception as e:
        _log(state, f"CRITICAL ERROR: {str(e)}")

    finally:
        state.is_running = False
        state.current_contact = None
        state.current_phone = None
        _save_log(state, results)
        _log(state, f"Session complete. Sent: {state.sent}, Failed: {state.failed}")
        # Do NOT quit driver -- it's the user's Chrome session

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Send WhatsApp messages from Google Sheet")
    parser.add_argument("--count", type=int, default=10, help="Number of messages to send")
    parser.add_argument("--delay", type=int, default=60, help="Delay between messages in seconds")
    args = parser.parse_args()

    results = run_send_loop(count=args.count, delay=args.delay)
    print(f"\nDone. Sent: {sum(1 for r in results if r.success)}, "
          f"Failed: {sum(1 for r in results if not r.success)}")
