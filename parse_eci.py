import urllib.request
import json
import datetime
import base64
import os
import re

URL = "https://citizens-initiative.europa.eu/initiatives/details/2025/000006_en"
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

def main():
    print(f"Fetching HTML from {URL}...")
    req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
    except Exception as e:
        print(f"Failed to fetch EU URL: {e}")
        exit(1)

    print("Parsing HTML using Regex...")
    
    # 1. Find all tables in the raw HTML string
    tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.IGNORECASE | re.DOTALL)
    
    target_table_html = None
    for t in tables:
        # Identify the correct table by its headers
        if 'Country' in t and 'Signatures' in t and 'Threshold' in t:
            target_table_html = t
            break
            
    if not target_table_html:
        print("Error: Could not find the signatures table in the HTML.")
        print(f"Diagnostics: Found {len(tables)} tables total.")
        exit(1)
        
    data_list = []
    total_signatures = 0
    
    # 2. Extract every row from the target table
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', target_table_html, re.IGNORECASE | re.DOTALL)
    
    for row in rows:
        # Extract every cell (handling both <th> and <td> tags)
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.IGNORECASE | re.DOTALL)
        
        clean_cells = []
        for c in cells:
            # Strip away any internal HTML tags (like <div> or <span> inside the cell)
            c = re.sub(r'<[^>]+>', '', c)
            # Remove HTML entities like &nbsp; which cause crashes
            c = re.sub(r'&[a-zA-Z0-9#]+;', ' ', c)
            clean_cells.append(c.strip())
            
        # We need at least 2 columns to do anything useful
        if len(clean_cells) < 2:
            continue
            
        country = clean_cells[0]
        
        # Skip the header row itself
        if "Country" in country or "country" in country.lower():
            continue
            
        # Strip everything except digits from the signature count
        sig_str = re.sub(r'[^\d]', '', clean_cells[1])
        if not sig_str:
            continue
            
        # The bottom row usually contains the cumulative total
        if "Total" in country:
            total_signatures = int(sig_str)
            continue
            
        try:
            signatures = int(sig_str)
            
            # Safely parse threshold (extract only digits)
            threshold_str = re.sub(r'[^\d]', '', clean_cells[2]) if len(clean_cells) > 2 else '0'
            threshold = int(threshold_str) if threshold_str else 0
            
            # Safely parse percentage (extract digits and decimal point)
            pct_str = re.sub(r'[^\d.]', '', clean_cells[3]) if len(clean_cells) > 3 else '0'
            percentage = float(pct_str) if pct_str else 0.0
            
            data_list.append({
                "country": country,
                "signatures": signatures,
                "threshold": threshold,
                "percentage": percentage
            })
        except ValueError as e:
            print(f"Skipping row due to error: {e}. Row data: {clean_cells}")
            continue

    if not data_list:
        print("Error: Table was found, but no country data could be extracted.")
        exit(1)

    # Use modern Python timezone logic (fixes the deprecation warning)
    new_snapshot = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_signatures": total_signatures,
        "countries": data_list
    }
    
    print(f"Successfully scraped {len(data_list)} countries. Total: {total_signatures}")
    print("\n--- JSON PREVIEW ---")
    print(json.dumps(new_snapshot, indent=2)[:500] + "\n...\n")
    
    update_github_file(new_snapshot)

if __name__ == "__main__":
    main()
