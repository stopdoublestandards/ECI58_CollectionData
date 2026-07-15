import urllib.request
import http.cookiejar
import json
import datetime
import base64
import os

GITHUB_REPO = "stopdoublestandards/ECI58_CollectionData"
FILE_PATH = "eci_signatures.json"
BRANCH = "main"

# The API returns 2-letter codes. This maps them back to the table format.
COUNTRY_MAP = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "HR": "Croatia",
    "CY": "Cyprus", "CZ": "Czechia", "DK": "Denmark", "EE": "Estonia",
    "FI": "Finland", "FR": "France", "DE": "Germany", "GR": "Greece",
    "HU": "Hungary", "IE": "Ireland", "IT": "Italy", "LV": "Latvia",
    "LT": "Lithuania", "LU": "Luxembourg", "MT": "Malta", "NL": "Netherlands",
    "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SK": "Slovakia",
    "SI": "Slovenia", "ES": "Spain", "SE": "Sweden"
}

def update_github_file(new_data):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN environment variable is not set.")
        exit(1)

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}?ref={BRANCH}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "TeamCity-CI-Scraper"
    }

    req = urllib.request.Request(api_url, headers=headers)
    existing_data = []
    sha = None

    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            sha = res_data.get("sha")
            content_b64 = res_data.get("content", "")
            if content_b64:
                decoded_content = base64.b64decode(content_b64).decode('utf-8')
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
    new_content_b64 = base64.b64encode(new_content_json.encode('utf-8')).decode('utf-8')

    payload = {
        "message": f"Update ECI signatures - {new_data.get('timestamp')}",
        "content": new_content_b64,
        "branch": BRANCH
    }
    if sha:
        payload["sha"] = sha

    put_req = urllib.request.Request(
        put_url, 
        data=json.dumps(payload).encode('utf-8'), 
        headers=headers, 
        method="PUT"
    )
    
    try:
        with urllib.request.urlopen(put_req) as response:
            print(f"Successfully updated {FILE_PATH} in {GITHUB_REPO}")
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode('utf-8')
        print(f"Failed to update file on GitHub: {error_msg}")
        exit(1)

def get_eci_data():
    """Fetches data from the EU APIs using a Session Cookie to bypass the WAF."""
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    
    # Full browser headers required by the EU firewall
    opener.addheaders = [
        ('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'),
        ('Accept', 'application/json, text/plain, */*'),
        ('Accept-Language', 'en-US,en;q=0.9'),
        ('Referer', 'https://eci.ec.europa.eu/058/public/'),
        ('Origin', 'https://eci.ec.europa.eu'),
        ('Connection', 'keep-alive')
    ]
    
    try:
        # 1. Visit the main page to establish the session cookie
        print("Establishing session with EU server to bypass firewall...")
        opener.open("https://eci.ec.europa.eu/058/public/")
        
        # 2. Fetch the totals
        print("Fetching progression totals...")
        resp_prog = opener.open("https://eci.ec.europa.eu/058/public/api/report/progression")
        prog_data = json.loads(resp_prog.read().decode('utf-8'))
        total_signatures = prog_data.get("signatureCount", 0)
        
        # 3. Fetch the geographic map data using the active session
        print("Fetching country distribution...")
        resp_map = opener.open("https://eci.ec.europa.eu/058/public/api/report/map")
        map_data = json.loads(resp_map.read().decode('utf-8'))
        
        return total_signatures, map_data
    except Exception as e:
        print(f"FATAL: Failed to fetch data from EU API: {e}")
        exit(1)

def main():
    # Use modern Python timezone logic
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    
    total_signatures, map_data = get_eci_data()
    countries_clean = []
    
    for item in map_data:
        if isinstance(item, dict):
            code = item.get("countryCode", "Unknown")
            count = item.get("signatureCount", 0)
            threshold = item.get("threshold", 0)
            percentage = item.get("percentage", 0.0)
            
            countries_clean.append({
                "country": COUNTRY_MAP.get(code, code),
                "signatures": count,
                "threshold": threshold,
                "percentage": percentage
            })
            
    # Sort alphabetically by country name exactly like the public table
    countries_clean = sorted(countries_clean, key=lambda x: x["country"])

    clean_snapshot = {
        "timestamp": timestamp,
        "total_signatures": total_signatures,
        "countries": countries_clean
    }
    
    if not countries_clean:
        print("Error: The country array is still empty.")
        exit(1)
    else:
        print(f"Successfully retrieved data for {len(countries_clean)} countries.")
        
    print("\n--- JSON TO BE SAVED ---")
    print(json.dumps(clean_snapshot, indent=2)[:500] + "\n...\n")
    
    update_github_file(clean_snapshot)

if __name__ == "__main__":
    main()
