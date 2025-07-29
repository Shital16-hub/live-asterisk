import os
import requests

RAG_SERVER = "http://localhost:8000"
BASE_DIR = "/root/livekit.ecommcube.com/rag_knowledge_docs/towing_services_doc"
COLLECTION_NAME = os.path.basename(BASE_DIR)
QDRANT_API_KEY = "2123tt"  # Set your API key here

# 1. Read all .txt files
texts = []
for fname in os.listdir(BASE_DIR):
    if fname.endswith(".txt"):
        with open(os.path.join(BASE_DIR, fname), "r") as f:
            texts.append(f.read())

print(f"Found {len(texts)} documents in {BASE_DIR}")

# 2. Delete the collection
print(f"Deleting collection '{COLLECTION_NAME}'...")
delete_payload = {
    "collection_name": COLLECTION_NAME,
    "qdrant_api_key": QDRANT_API_KEY
}
resp = requests.post(f"{RAG_SERVER}/delete", json=delete_payload)
try:
    print("Delete response:", resp.json())
except Exception:
    print("Delete raw response:", resp.text)

# 3. Upsert all docs
if texts:
    print(f"Upserting {len(texts)} documents to '{COLLECTION_NAME}'...")
    batch_payload = {
        "collection_name": COLLECTION_NAME,
        "texts": texts,
        "qdrant_api_key": QDRANT_API_KEY
    }
    resp = requests.post(f"{RAG_SERVER}/batch_add", json=batch_payload)
    try:
        print("Batch add response:", resp.json())
    except Exception:
        print("Batch add raw response:", resp.text)
else:
    print("No documents to upsert.") 