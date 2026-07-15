import urllib.request
import json
import datetime
import base64
import os
from html.parser import HTMLParser

URL = "https://citizens-initiative.europa.eu/initiatives/details/2025/000006_en"
GITHUB_REPO = "stopdoublestandards/ECI58_CollectionData"
FILE_PATH = "eci_signatures.json"
BRANCH = "main" # Adjust if your default branch is 'master'

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_tr = False
        self.in_cell = False
        self.current_cell = []
        self.current_row = []
        self.tables = []
        self.current_table = []
        
    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.in_table = True
            self.current_table = []
        elif tag == 'tr' and self.in_table:
            self.in_tr = True
            self.current_row = []
        elif tag in ('td', 'th') and self.in_tr:
            self.in_cell = True
            self.current_cell = []

    def handle_endtag(self, tag):
        if tag == 'table':
            self.in_table = False
            self.tables.append(self.current_table)
        elif tag == 'tr' and self.in_table:
            self.in_tr = False
            if self.current_row:
                self.current_table.append(self.current_row)
        elif tag in ('td', 'th') and self.in_tr:
            self.in_cell = False
            self.current_row.append("".join(self.current_cell).strip())

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell.append(data)

def update_github_file(new_data):
    # The token must be provided securely via TeamCity environment variables
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

    # 1. Fetch the existing file to get its SHA and current content
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
                    # Ensure it's a list for historical appending
                    if not isinstance(existing_data, list):
                        existing_data = [existing_data] 
                except json.JSONDecodeError:
                    existing_data = []
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"File {FILE_PATH} does not exist yet. It will be created.")
            # Remove branch ref for the PUT request URL
            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}"
        else:
            print(f"Failed to fetch file from GitHub: {e}")
            exit(1)

    # Re-assign URL without the ref parameter for the PUT request
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}"

    # 2. Append the new snapshot to the historical data
    existing_data.append(new_data)

    # 3. Prepare the payload
    new_content_json = json.dumps(existing_data, indent=2, ensure_ascii=False)
    new_content_b64 = base64.b64encode(new_content_json.encode('utf-8')).decode('utf-8')

    payload = {
        "message": f"Update ECI signatures - {new_data['timestamp']}",
        "content": new_content_b64,
        "branch": BRANCH
    }
    if sha:
        payload["sha"] = sha

    # 4. Push the update via PUT request
    put_req = urllib.request.Request(
        api_url, 
        data=json.dumps(payload).encode('utf-8'), 
        headers=headers, 
        method="PUT"
    )
    
    try:
        with urllib.request.urlopen(put_req) as response:
            print(f"Successfully updated {FILE_PATH} in {GITHUB_REPO}")
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode('utf-8')
        print(f"Failed to update file: {error_msg}")
        exit(1)

def main():
    req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
    except Exception as e:
        print(f"Failed to fetch EU URL: {e}")
        exit(1)

    parser = TableParser()
    parser.feed(html)
    
    target_table = None
    for tbl in parser.tables:
        if tbl and len(tbl) > 0 and 'Country' in tbl[0] and 'Signatures' in tbl[0]:
            target_table = tbl
            break
            
    if not target_table:
        print("Error: Could not find the signatures table on the page.")
        exit(1)
        
    data_list = []
    total_signatures = 0
    
    for row in target_table[1:]:
        if len(row) < 2:
            continue
            
        country = row[0]
        if "Total" in country:
            total_signatures = int(row[1].replace(',', ''))
            continue
            
        try:
            signatures = int(row[1].replace(',', ''))
            threshold = int(row[2].replace(',', '')) if len(row) > 2 else 0
            percentage = float(row[3].replace('%', '')) if len(row) > 3 else 0.0
            
            data_list.append({
                "country": country,
                "signatures": signatures,
                "threshold": threshold,
                "percentage": percentage
            })
        except ValueError:
            continue

    new_snapshot = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "total_signatures": total_signatures,
        "countries": data_list
    }
    
    update_github_file(new_snapshot)

if __name__ == "__main__":
    main()
