import requests
resp = requests.post("http://localhost:8000/search", json={
    "collection_name": "towing_services_doc",
    "query_string": "Jumpstart service",
    "top_k": 3,
    "qdrant_api_key": "2123tt"
})
print(resp.json())