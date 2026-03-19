import requests
import json

def check_acl_keys():
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": "transformer",
        "limit": 5,
        "fields": "title,venue,externalIds",
        "venue": "ACL"
    }
    resp = requests.get(url, params=params)
    data = resp.json()
    for paper in data.get("data", []):
        print(f"Title: {paper['title']}")
        print(f"ExternalIds: {paper.get('externalIds')}")
        print("-" * 20)

if __name__ == "__main__":
    check_acl_keys()
