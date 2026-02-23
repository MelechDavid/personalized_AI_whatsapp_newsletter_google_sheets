"""
Google Sheets interface for reading contacts and writing send status.

Uses the Google Sheets API v4 directly (not gspread) to support
uploaded .xlsx files hosted in Google Sheets.
"""

import os
import re
from pathlib import Path
from dataclasses import dataclass

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
PROJECT_ROOT = Path(__file__).parent.parent
CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
TOKEN_FILE = PROJECT_ROOT / "token.json"


def extract_sheet_id(url: str) -> str | None:
    """Extract Google Sheet ID from a URL like:
    https://docs.google.com/spreadsheets/d/SHEET_ID/edit#gid=0
    Returns None if the URL doesn't match the expected format.
    """
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    return match.group(1) if match else None


@dataclass
class Contact:
    row_number: int      # 1-indexed sheet row (for writing back)
    sort_name: str       # Raw value from column C
    first_name: str      # Extracted first name
    phone_raw: str       # Raw value from column D
    phone_clean: str     # Normalized digits only (with country code)


def get_credentials() -> Credentials:
    """Load or create OAuth credentials. First run opens browser for login."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json())

    return creds


def get_sheets_service():
    """Build and return the Google Sheets API service."""
    creds = get_credentials()
    return build("sheets", "v4", credentials=creds)


def extract_first_name(sort_name: str) -> str:
    """
    Extract first name from 'Last, First' format.
    'Lauren, David' -> 'David'
    'Lorenzo Nourafchan, Moshe' -> 'Moshe'
    'David' -> 'David'
    '' -> 'there'
    """
    if not sort_name or not sort_name.strip():
        return "there"
    if "," in sort_name:
        parts = sort_name.split(",", 1)
        first = parts[1].strip()
        return first if first else "there"
    return sort_name.strip()


def normalize_phone(phone_raw: str) -> str:
    """
    Normalize phone number for WhatsApp URL (digits only with country code).
    '+1 347 551-1532' -> '13475511532'
    '+972 52 599-7530' -> '972525997530'
    '16145541758' -> '16145541758'
    """
    if not phone_raw:
        return ""
    return "".join(c for c in phone_raw if c.isdigit())


def get_pending_contacts(limit: int, sheet_id: str | None = None) -> list[Contact]:
    """
    Fetch up to `limit` contacts where column A is empty.
    Columns: A=status, B=ID, C=Sort Name, D=Phone
    """
    service = get_sheets_service()
    sheet_id = sheet_id or os.getenv("GOOGLE_SHEET_ID")
    sheet_name = os.getenv("SHEET_NAME", "Good Version")

    # Read columns A through D
    range_name = f"'{sheet_name}'!A:D"
    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=range_name,
    ).execute()

    all_rows = result.get("values", [])

    contacts = []
    # Skip header (index 0 = row 1); data rows start at index 1 = row 2
    for idx, row in enumerate(all_rows[1:], start=2):
        if len(contacts) >= limit:
            break

        # Pad row to 4 columns if short
        while len(row) < 4:
            row.append("")

        status = row[0].strip()
        if status != "":
            continue

        sort_name = row[2].strip()
        phone_raw = row[3].strip()

        if not phone_raw:
            continue

        first_name = extract_first_name(sort_name)
        phone_clean = normalize_phone(phone_raw)

        if not phone_clean:
            continue

        contacts.append(Contact(
            row_number=idx,
            sort_name=sort_name,
            first_name=first_name,
            phone_raw=phone_raw,
            phone_clean=phone_clean,
        ))

    return contacts


def write_status(row_number: int, success: bool, sheet_id: str | None = None) -> None:
    """Write send status to column A: 1=success, 0=failure."""
    service = get_sheets_service()
    sheet_id = sheet_id or os.getenv("GOOGLE_SHEET_ID")
    sheet_name = os.getenv("SHEET_NAME", "Good Version")

    value = 1 if success else 0
    range_name = f"'{sheet_name}'!A{row_number}"

    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=range_name,
        valueInputOption="RAW",
        body={"values": [[value]]},
    ).execute()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    print("Testing Google Sheets connection...")
    contacts = get_pending_contacts(5)
    print(f"Found {len(contacts)} pending contacts:")
    for c in contacts:
        print(f"  Row {c.row_number}: {c.first_name} ({c.phone_raw} -> {c.phone_clean})")
