import urllib.request
import json
import datetime
import base64
import os

API_URL = "https://eci.ec.europa.eu/058/public/api/report/progression"
GITHUB_REPO = "stopdoublestandards/ECI58_CollectionData"
FILE_PATH = "eci_signatures.json"
BRANCH = "main" 

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

def extract_clean_data(eu_data):
    """Attempts to find the country list and total signatures in the unknown API schema."""
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"
    
    # Best-effort extraction based on common ECI API formats
    countries = []
    total_signatures = eu_data.get("total", eu_data.get("signatureCount", 0))
    
    # The API might return a list directly, or a dictionary containing a list
    raw_list = eu_data if isinstance(eu_data, list) else eu_data.get("countries", eu_data.get("distribution", []))
    
    for item in raw_list:
        if isinstance(item, dict):
            # Try to grab the country name or code
            country_name = item.get("country", item.get("countryLabel", item.get("name", "Unknown")))
            if isinstance(country_name, dict): 
                # Sometimes it's nested like {"country": {"code": "AT", "label": "Austria"}}
                country_name = country_name.get("label", country_name.get("code", "Unknown"))
                
            # Try to grab the signature count
            count = item.get("count", item.get("signatures", item.get("amount", 0)))
            
            countries.append({
                "country": country_name,
                "signatures": count
            })
            
    return {
        "timestamp": timestamp,
        "total_signatures": total_signatures,
        "countries": countries
    }

def main():
    print("Fetching live JSON data from EU API...")
    req = urllib.request.Request(API_URL, headers={
        'User-Agent': 'TeamCity-CI-Scraper',
        'Accept': 'application/json'
    })
    
    try:
        with urllib.request.urlopen(req) as response:
            eu_data = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Failed to fetch from EU API: {e}")
        exit(1)
        
    # Print a preview of the RAW data so we can map it perfectly if the extraction fails
    print("\n--- RAW API PAYLOAD PREVIEW ---")
    print(json.dumps(eu_data, indent=2)[:500] + "\n... (truncated)\n")

    # Extract the clean structure you requested
    clean_snapshot = extract_clean_data(eu_data)
    
    print("\n--- CLEAN DATA TO BE SAVED ---")
    print(json.dumps(clean_snapshot, indent=2))
    
    update_github_file(clean_snapshot)

if __name__ == "__main__":
    main()
