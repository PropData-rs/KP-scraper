"""Wipe all data rows from the Listings tab, keeping the header row.
Run on a schedule (e.g. every 2 days) by the clear-sheet workflow."""

import json
import os

SHEET_NAME = "Listings"
SCOPES     = ["https://www.googleapis.com/auth/spreadsheets"]


def main():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info  = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    svc   = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet_id = os.environ["SPREADSHEET_ID"]

    # Clear everything from row 2 down; header (row 1) stays.
    svc.spreadsheets().values().clear(
        spreadsheetId=sheet_id,
        range=f"{SHEET_NAME}!A2:Z",
    ).execute()
    print("✓ Cleared all data rows (header kept).")


if __name__ == "__main__":
    main()
