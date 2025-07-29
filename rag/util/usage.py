import requests

SERVER_URL = "http://localhost:8000"
COLLECTION_NAME = "test_collection"
QDRANT_API_KEY = "2123tt"

# 1. /add
add_payload = {
    "collection_name": COLLECTION_NAME,
    "text": "Single doc for /add endpoint.",
    "qdrant_api_key": QDRANT_API_KEY
}
print("\n/add usage:")
resp = requests.post(f"{SERVER_URL}/add", json=add_payload)
print("Status:", resp.status_code)
print("Response:", resp.json())

# 2. /batch_add
batch_payload = {
    "collection_name": COLLECTION_NAME,
    "texts": ["Batch doc 1", "Batch doc 2", "Batch doc 3"],
    "qdrant_api_key": QDRANT_API_KEY
}
print("\n/batch_add usage:")
resp = requests.post(f"{SERVER_URL}/batch_add", json=batch_payload)
print("Status:", resp.status_code)
print("Response:", resp.json())

# 3. /search
search_payload = {
    "collection_name": COLLECTION_NAME,
    "query_string": "Batch doc",
    "top_k": 2,
    "qdrant_api_key": QDRANT_API_KEY
}
print("\n/search usage:")
resp = requests.post(f"{SERVER_URL}/search", json=search_payload)
print("Status:", resp.status_code)
print("Response:", resp.json())

# 4. /search with filter
search_filter_payload = {
    "collection_name": COLLECTION_NAME,
    "query_string": "Batch doc",
    "top_k": 2,
    "filter": {"text": "Batch doc 2"},
    "qdrant_api_key": QDRANT_API_KEY
}
print("\n/search with filter usage:")
resp = requests.post(f"{SERVER_URL}/search", json=search_filter_payload)
print("Status:", resp.status_code)
print("Response:", resp.json())

# 5. /delete
delete_payload = {
    "collection_name": COLLECTION_NAME,
    "qdrant_api_key": QDRANT_API_KEY
}
print("\n/delete usage:")
resp = requests.post(f"{SERVER_URL}/delete", json=delete_payload)
print("Status:", resp.status_code)
print("Response:", resp.json())

# 6. /list (API key as query param)
print("\n/list usage (query param):")
resp = requests.get(f"{SERVER_URL}/list?qdrant_api_key={QDRANT_API_KEY}")
print("Status:", resp.status_code)
print("Response:", resp.json())

# 7. /list (API key as header)
print("\n/list usage (header):")
resp = requests.get(f"{SERVER_URL}/list", headers={"X-Qdrant-Api-Key": QDRANT_API_KEY})
print("Status:", resp.status_code)
print("Response:", resp.json()) 