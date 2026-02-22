# Send WhatsApp Messages from Google Sheet

## Goal
Send personalized WhatsApp messages with an image attachment (Exec Learning Summer 2026.jpg) to contacts listed in a Google Sheet. Track success/failure back to the sheet.

## Inputs
- Google Sheet ID (in `.env`)
- Number of messages to send (user-specified via dashboard, max 45/day)
- Delay between messages (user-specified, 30-120 seconds)

## Process
1. Run `streamlit run execution/dashboard.py` to open the control panel
2. Set the number of messages and delay, then click "Start Sending"
3. Chrome launches automatically with a dedicated profile (no manual Chrome needed)
4. First run only: scan the WhatsApp QR code when Chrome opens
5. The system will:
   a. Fetch N rows from Google Sheet where column A is empty
   b. Extract first name from column C ("Last, First" format)
   c. Navigate to `web.whatsapp.com/send?phone=XXXXX` for each contact
   d. Attach the image and type the personalized caption
   e. Send the message
   f. Write 1 (success) or 0 (failure) to column A

## Tools
- `execution/google_sheets.py` - Read/write Google Sheets via OAuth + gspread
- `execution/whatsapp_sender.py` - Selenium WhatsApp Web automation
- `execution/send_messages.py` - Orchestrator (main loop with error handling)
- `execution/dashboard.py` - Streamlit UI with start/stop/pause controls

## Setup (one-time)
1. Copy OAuth credentials to `credentials.json` in project root
2. Run `python execution/google_sheets.py` to complete OAuth flow (opens browser)
3. Chrome is auto-launched by the script — no manual shortcut needed
4. On first run, scan the WhatsApp QR code when Chrome opens (session persists in `.tmp/chrome-whatsapp/`)

## Edge Cases
- Phone numbers: stripped to digits only; all include country codes
- Name parsing: split on comma, take second part; fallback to "there" if empty
- Contact not found: detected via error popup, writes 0 to sheet
- WhatsApp disconnected: detected via QR code/banner, halts the loop
- Anti-ban: configurable delay with random jitter, daily cap of 45
- Mid-crash: rows without status retried on next run (idempotent)

## Learned Constraints
- Chrome must be launched with a **dedicated** user-data-dir (`.tmp/chrome-whatsapp/`) to prevent merging into an already-running Chrome instance. The script handles this automatically via `ensure_chrome_ready()` in `whatsapp_sender.py`.
- If user's regular Chrome is open, the automation Chrome still works because it uses a separate profile directory.
