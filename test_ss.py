import requests
import json

def test_ss():
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": "transformers",
        "limit": 5,
        "fields": "title,venue,year"
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        print(f"Status: {resp.status_code}")
        print(f"Response: {json.dumps(resp.json(), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_ss()
