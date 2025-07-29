import requests

# Configurable parameters
SERVER_URL = "http://localhost:8000"
COLLECTION_NAME = "test_collection"
QDRANT_API_KEY = "2123tt"  # Change as needed
TEST_TEXT = "This is a test document for RAG upsert."
SEARCH_QUERY = "test document"
BATCH_TEXTS = [
    "Batch doc 1 for RAG.",
    "Batch doc 2 for RAG.",
    "Batch doc 3 for RAG."
]

# Test /add endpoint
add_payload = {
    "collection_name": COLLECTION_NAME,
    "text": TEST_TEXT,
    "qdrant_api_key": QDRANT_API_KEY
}
print(f"\nTesting /add endpoint...")
add_resp = requests.post(f"{SERVER_URL}/add", json=add_payload)
print("Status:", add_resp.status_code)
try:
    print("Response:", add_resp.json())
except Exception:
    print("Raw response:", add_resp.text)

# Test /batch_add endpoint
batch_payload = {
    "collection_name": COLLECTION_NAME,
    "texts": BATCH_TEXTS,
    "qdrant_api_key": QDRANT_API_KEY
}
print(f"\nTesting /batch_add endpoint...")
batch_resp = requests.post(f"{SERVER_URL}/batch_add", json=batch_payload)
print("Status:", batch_resp.status_code)
try:
    print("Response:", batch_resp.json())
except Exception:
    print("Raw response:", batch_resp.text)

# Test /search endpoint with top_k=3
search_payload = {
    "collection_name": COLLECTION_NAME,
    "query_string": "RAG",
    "top_k": 3,
    "qdrant_api_key": QDRANT_API_KEY
}
print(f"\nTesting /search endpoint with top_k=3...")
search_resp = requests.post(f"{SERVER_URL}/search", json=search_payload)
print("Status:", search_resp.status_code)
try:
    print("Response:", search_resp.json())
except Exception:
    print("Raw response:", search_resp.text)

# Test /search endpoint with filter
search_filter_payload = {
    "collection_name": COLLECTION_NAME,
    "query_string": "RAG",
    "top_k": 3,
    "filter": {"text": "Batch doc 2 for RAG."},
    "qdrant_api_key": QDRANT_API_KEY
}
print(f"\nTesting /search endpoint with filter...")
search_filter_resp = requests.post(f"{SERVER_URL}/search", json=search_filter_payload)
print("Status:", search_filter_resp.status_code)
try:
    print("Response:", search_filter_resp.json())
except Exception:
    print("Raw response:", search_filter_resp.text) 