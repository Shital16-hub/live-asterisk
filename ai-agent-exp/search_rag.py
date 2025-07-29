import requests

def search_collection(collection_name, query_string, api_key, top_k=3, server_url="http://localhost:8000"):
    payload = {
        "collection_name": collection_name,
        "query_string": query_string,
        "top_k": top_k,
        "qdrant_api_key": api_key
    }
    print(f"Searching '{collection_name}' for: {query_string}")
    resp = requests.post(f"{server_url}/search", json=payload)
    print("Status:", resp.status_code)
    try:
        data = resp.json()
        # print("Response:", data)
        return data.get("result", [])
    except Exception:
        print("Raw response:", resp.text)
        return []

if __name__ == "__main__":
    # Example usage
    api_key = "2123tt"  # Set your API key here
    results = search_collection("towing_services_doc", "jump start", api_key)
    for idx, res in enumerate(results, 1):
        print(f"\nResult {idx}:")
        print(res.get("text", res)) 