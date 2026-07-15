import urllib.request
import json
import datetime
import base64
import os
import re
from html.parser import HTMLParser

URL = "https://citizens-initiative.europa.eu/initiatives/details/2025/000006_en"
GITHUB_REPO = "stopdoublestandards/ECI58_CollectionData"
FILE_PATH = "eci_signatures.json"
BRANCH = "main"

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
            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}"
        else:
            print(f"Failed to fetch file from GitHub: {e}")
            exit(1)

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}"
    existing_data.append(new_data)
    new_content_json = json.dumps(existing_data, indent=2, ensure_ascii=False)
    new_content_b64 = base64.b64encode(new_content_json.encode('utf-8')).decode('utf-8')

    payload = {
        "message": f"Update ECI signatures - {new_data['timestamp']}",
        "content": new_content_b64,
        "branch": BRANCH
    }
    if sha:
        payload["sha"] = sha

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
        print(f"Failed to update file on GitHub: {error_msg}")
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
    header_row_index = -1
    
    # 1. More resilient table search: scan every row of every table
    for tbl in parser.tables:
        for i, row in enumerate(tbl):
            # Convert row to lowercase for safe matching
            row_lower = [str(cell).lower() for cell in row]
            if any('country' in c for c in row_lower) and any('signatures' in c for c in row_lower):
                target_table = tbl
                header_row_index = i
                break
        if target_table:
            break
            
    # 2. Built-in TeamCity diagnostics
    if not target_table:
        print("Error: Could not find the signatures table on the page.")
        print(f"\n--- DIAGNOSTICS ---")
        print(f"Total tables found: {len(parser.tables)}")
        for i, tbl in enumerate(parser.tables):
            print(f"Table {i} - First 2 rows:")
            for r in tbl[:2]:
                print(f"  {r}")
        
        if len(parser.tables) == 0:
            print("No tables parsed. The page might require JavaScript to render.")
            print(f"First 300 chars of HTML:\n{html[:300]}")
        exit(1)
        
    data_list = []
    total_signatures = 0
    
    # Start parsing from the row AFTER the headers
    for row in target_table[header_row_index + 1:]:
        if len(row) < 2:
            continue
            
        country = row[0].strip()
        
        # 3. Regex cleaning to strip out non-breaking spaces and formatting
        sig_str = re.sub(r'[^\d]', '', str(row[1]))
        
        if not sig_str:
            continue # Skip empty rows
            
        if "total" in country.lower():
            total_signatures = int(sig_str)
            continue
            
        try:
            signatures = int(sig_str)
            
            # Safely parse threshold (extract only digits)
            threshold_str = re.sub(r'[^\d]', '', str(row[2])) if len(row) > 2 else '0'
            threshold = int(threshold_str) if threshold_str else 0
            
            # Safely parse percentage (extract digits and decimal point)
            pct_str = re.sub(r'[^\d.]', '', str(row[3])) if len(row) > 3 else '0'
            percentage = float(pct_str) if pct_str else 0.0
            
            data_list.append({
                "country": country,
                "signatures": signatures,
                "threshold": threshold,
                "percentage": percentage
            })
        except ValueError as e:
            print(f"Skipping malformed data row {row}: {e}")
            continue

    new_snapshot = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "total_signatures": total_signatures,
        "countries": data_list
    }
    
    print(f"Successfully parsed {len(data_list)} countries. Total: {total_signatures}")
    update_github_file(new_snapshot)

if __name__ == "__main__":
    main()
