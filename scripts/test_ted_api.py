import requests
import json

def main():
    """
    TED (Tenders Electronic Daily) - Search API Test Script
    This endpoint allows us to query EU public tender/contract notices.
    No API Key is required for basic queries.
    """
    
    # TED Search API Endpoint (Note: TED frequently updates API versions, using the most common search format here)
    # The official API URL should point to api.ted.europa.eu or a specific private-search path
    url = "https://tedweb.api.ted.europa.eu/private-search/api/v1/notices/search"
    
    # 1. Set query conditions (modify this to "Play around")
    # Based on the real TED v3/v1-private API Payload structure
    payload = {
        "query": "(FT ~ (software)) SORT BY publication-number DESC",
        "language": "EN",
        "limit": 5,
        "onlyLatestVersions": False,
        "page": 1,
        "scope": "ALL",
        "validation": False,
        "facets": {
            "business-opportunity": [],
            "cpv": [],
            "contract-nature": [],
            "place-of-performance": [],
            "procedure-type": []
        },
        # Based on previous errors, 'fields' is required and must not contain unsupported fields
        "fields": [
            "publication-number" 
        ]
    }

    print(f"Sending search request to {url}...")
    print(f"Query condition: {payload['query']}")
    
    try:
        # Send POST request to API
        headers = {
            # Add User-Agent to prevent being blocked by the firewall as a simple bot
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        response = requests.post(url, json=payload, headers=headers)
        
        # If it returns 200, it is successful
        if response.status_code == 200:
            data = response.json()
            # According to the latest API structure, results might be in the 'notices' array
            results = data.get("notices", [])
            total = data.get("total", 0)
            
            print(f"\n✅ Request successful! Matched {total} total results, returning {len(results)} on this page.")
            
            # 2. Extract and display the most useful fields
            print("\n--- 🎟️ Extracted useful information examples ---")
            for item in results:
                # Extract returned fields (Note: v3 field names have changed to publication-number, etc.)
                notice_id = item.get("publication-number", "N/A")
                title = item.get("BT-21-Procedure", "N/A")
                buyer = item.get("BT-11-Procedure", "N/A")
                
                # Real access link on TED updated
                link = f"https://ted.europa.eu/en/notice/-/detail/{notice_id}"
                
                print(f"📌 Notice ID: {notice_id}")
                print(f"   Buyer/Org: {buyer}")
                print(f"   Title: {title}")
                print(f"   Link: {link}\n")
                
        else:
            print(f"❌ Request failed, HTTP Status Code: {response.status_code}")
            print("Response content:", response.text)
            
    except Exception as e:
        print(f"Request exception occurred: {str(e)}")

if __name__ == "__main__":
    main()
