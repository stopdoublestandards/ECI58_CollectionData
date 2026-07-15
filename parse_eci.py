import urllib.request
import urllib.error
import json
import datetime
import base64
import os

GITHUB_REPO = "stopdoublestandards/ECI58_CollectionData"
FILE_PATH = "eci_signatures.json"
BRANCH = "main"

# Single, unauthenticated source of truth for both the total and the per-country
# breakdown. The old collection app (eci.ec.europa.eu/058/public/api/report/map)
# is a dead end: it returns a hard 403 "Cannot Access" and the site's own SPA
# never calls it. The public register API exposes the Statement of Support (SoS)
# report, whose entries sum exactly to the headline total -- no WAF, no cookies.
DATA_URL = "https://register.eci.ec.europa.eu/core/api/register/details/2025/000006"

# 2-letter code -> country name, matching the public table. Note the API uses the
# geographic code "GR" (not the EU's "EL") for Greece.
COUNTRY_MAP = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "HR": "Croatia",
    "CY": "Cyprus", "CZ": "Czechia", "DK": "Denmark", "EE": "Estonia",
    "FI": "Finland", "FR": "France", "DE": "Germany", "GR": "Greece",
    "HU": "Hungary", "IE": "Ireland", "IT": "Italy", "LV": "Latvia",
    "LT": "Lithuania", "LU": "Luxembourg", "MT": "Malta", "NL": "Netherlands",
    "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SK": "Slovakia",
    "SI": "Slovenia", "ES": "Spain", "SE": "Sweden"
}

# Minimum number of signatories per Member State ("thresholds"). Fixed regulatory
# constants = (country's MEPs) x 720, per Commission Delegated Regulation (EU)
# 2024/1082, applicable to initiatives registered on/after 16 July 2024. This
# initiative was registered on 03/12/2025, so these values apply for the whole
# collection period (until 03/03/2027). Verified against
# https://citizens-initiative.europa.eu/thresholds_en
THRESHOLDS = {
    "AT": 14400, "BE": 15840, "BG": 12240, "HR": 8640, "CY": 4320,
    "CZ": 15120, "DK": 10800, "EE": 5040, "FI": 10800, "FR": 58320,
    "DE": 69120, "GR": 15120, "HU": 15120, "IE": 10080, "IT": 54720,
    "LV": 6480, "LT": 7920, "LU": 4320, "MT": 4320, "NL": 22320,
    "PL": 38160, "PT": 15120, "RO": 23760, "SK": 10800, "SI": 6480,
    "ES": 43920, "SE": 15120
}

# A real browser User-Agent keeps the EU servers happy; no cookies are required.
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_eci_data():
    """Fetch the total and per-country signature counts from the register API.

    Returns (total_signatures, [{code, signatures}, ...]).
    """
    req = urllib.request.Request(DATA_URL, headers=BROWSER_HEADERS)
    try:
        print(f"Fetching signature data from register API...")
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"FATAL: Failed to fetch data from register API: {e}")
        exit(1)

    sos_report = data.get("sosReport") or {}
    total_signatures = sos_report.get("totalSignatures", 0)
    entries = sos_report.get("entry") or []

    countries = [
        {"code": item.get("countryCodeType"), "signatures": item.get("total", 0)}
        for item in entries
        if isinstance(item, dict) and item.get("countryCodeType")
    ]
    return total_signatures, countries


def build_snapshot():
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")

    total_signatures, raw_countries = get_eci_data()

    countries_clean = []
    for item in raw_countries:
        code = item["code"]
        signatures = item["signatures"]
        threshold = THRESHOLDS.get(code, 0)
        percentage = round(signatures / threshold * 100, 2) if threshold else 0.0
        countries_clean.append({
            "country": COUNTRY_MAP.get(code, code),
            "signatures": signatures,
            "threshold": threshold,
            "percentage": percentage,
        })

    # Sort alphabetically by country name, exactly like the public table.
    countries_clean.sort(key=lambda c: c["country"])

    if not countries_clean:
        print("Error: The country array is empty. Aborting to avoid a bad snapshot.")
        exit(1)

    # Sanity check: the per-country totals should reconcile with the headline total.
    country_sum = sum(c["signatures"] for c in countries_clean)
    if country_sum != total_signatures:
        print(f"Warning: sum of country signatures ({country_sum}) != "
              f"total_signatures ({total_signatures}).")

    print(f"Successfully retrieved data for {len(countries_clean)} countries "
          f"({total_signatures} total signatures).")

    return {
        "timestamp": timestamp,
        "total_signatures": total_signatures,
        "countries": countries_clean,
    }


def update_github_file(new_data):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN environment variable is not set.")
        exit(1)

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "TeamCity-CI-Scraper",
    }

    get_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}?ref={BRANCH}"
    existing_data = []
    sha = None

    try:
        with urllib.request.urlopen(urllib.request.Request(get_url, headers=headers)) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            sha = res_data.get("sha")
            content_b64 = res_data.get("content", "")
            if content_b64:
                decoded_content = base64.b64decode(content_b64).decode("utf-8")
                try:
                    existing_data = json.loads(decoded_content)
                    if not isinstance(existing_data, list):
                        existing_data = [existing_data]
                except json.JSONDecodeError:
                    existing_data = []
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"File {FILE_PATH} does not exist yet. It will be created.")
        else:
            print(f"Failed to fetch file from GitHub: {e}")
            exit(1)

    existing_data.append(new_data)

    put_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}"
    new_content_json = json.dumps(existing_data, indent=2, ensure_ascii=False)
    new_content_b64 = base64.b64encode(new_content_json.encode("utf-8")).decode("utf-8")

    payload = {
        "message": f"Update ECI signatures - {new_data.get('timestamp')}",
        "content": new_content_b64,
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha

    put_req = urllib.request.Request(
        put_url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="PUT",
    )

    try:
        with urllib.request.urlopen(put_req):
            print(f"Successfully updated {FILE_PATH} in {GITHUB_REPO}")
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8")
        print(f"Failed to update file on GitHub: {error_msg}")
        exit(1)


def main():
    snapshot = build_snapshot()

    print("\n--- JSON TO BE SAVED ---")
    print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print()

    update_github_file(snapshot)


if __name__ == "__main__":
    main()
