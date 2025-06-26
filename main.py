import os
import json
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google.cloud import secretmanager
from datetime import date, timedelta

def get_secret(secret_id: str) -> dict:
    client = secretmanager.SecretManagerServiceClient()
    project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    payload = client.access_secret_version(request={"name": name}).payload.data.decode("utf-8")
    return json.loads(payload)

def cj_to_sheets(request):
    # 1) Hämta GSheet-creds från Secret Manager
    creds_info = get_secret(os.environ["SECRET_NAME"])
    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )

    # 2) Datum för gårdagen
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # 3) Hämta CJ-data och logga HTTP-svar
    headers = {"Authorization": f"Bearer {os.environ['CJ_API_KEY']}"}
    url = (
        f"https://commission-detail.api.cj.com/v3/commissions"
        f"?date-type=event&start-date={yesterday}&end-date={yesterday}"
    )
    resp = requests.get(url, headers=headers)

    # --- FELSÖKNINGSUTSKRIFTER ---
    print(f"CJ API status: {resp.status_code}")
    print(f"CJ API body (början 200 tecken): {resp.text[:200]!r}")
    # ------------------------------

    if resp.status_code != 200:
        return f"CJ API fel: {resp.status_code}", 500

    data = resp.json().get("commissions", [])

    # 4) Bygg DataFrame
    rows = []
    for c in data:
        rows.append({
            "Datum": c.get("eventDate"),
            "Marknad": c.get("country"),
            "Annonsör": c.get("advertiserName"),
            "Kostnad": c.get("commissionAmount"),
            "Order ID": c.get("orderId"),
        })
    if not rows:
        return "Inga transaktioner för gårdagen.", 200

    df = pd.DataFrame(rows)

    # 5) Skriv till Google Sheets
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.environ["SHEET_ID"]).sheet1

    if not sh.get_all_records():
        sh.append_row(df.columns.tolist())
    for _, r in df.iterrows():
        sh.append_row(r.astype(str).tolist())

    return f"{len(df)} rader inskrivna.", 200
