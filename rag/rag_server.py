import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
from rag import sanitize_collection_name
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, Filter, FieldCondition, MatchValue
from sentence_transformers import SentenceTransformer

app = FastAPI()

QDRANT_HOST = os.getenv('QDRANT_HOST', 'localhost')
QDRANT_PORT = int(os.getenv('QDRANT_PORT', '6333'))
MODEL = SentenceTransformer('all-MiniLM-L6-v2')

class RagRequest(BaseModel):
    collection_name: str
    query_string: str
    top_k: Optional[int] = 1
    filter: Optional[Dict[str, Any]] = None
    qdrant_api_key: str

class AddRequest(BaseModel):
    collection_name: str
    text: str
    qdrant_api_key: str

class BatchAddRequest(BaseModel):
    collection_name: str
    texts: List[str]
    qdrant_api_key: str

class DeleteRequest(BaseModel):
    collection_name: str
    qdrant_api_key: str

@app.post("/search")
def rag_search(req: RagRequest):
    client = QdrantClient(
        host=QDRANT_HOST,
        port=QDRANT_PORT,
        api_key=req.qdrant_api_key,
        https=False
    )
    collection = sanitize_collection_name(req.collection_name)
    vec = MODEL.encode(req.query_string).tolist()
    qdrant_filter = None
    if req.filter:
        conditions = [FieldCondition(key=k, match=MatchValue(value=v)) for k, v in req.filter.items()]
        qdrant_filter = Filter(must=conditions)
    resp = client.query_points(
        collection_name=collection,
        query=vec,
        limit=req.top_k,
        with_payload=True,
        query_filter=qdrant_filter
    )
    hits = resp.points
    if not hits:
        return {"result": "No relevant context found."}
    results = []
    for pt in hits:
        results.append(pt.payload)
    return {"result": results}

@app.post("/add")
def add_to_collection(req: AddRequest):
    client = QdrantClient(
        host=QDRANT_HOST,
        port=QDRANT_PORT,
        api_key=req.qdrant_api_key,
        https=False
    )
    collection = sanitize_collection_name(req.collection_name)
    # Check if collection exists
    try:
        exists = client.get_collection(collection_name=collection)
    except Exception:
        # Create collection if not exists
        dim = MODEL.get_sentence_embedding_dimension()
        client.recreate_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE)
        )
    # Upsert the text as a new point
    import uuid
    point_id = str(uuid.uuid4())
    vector = MODEL.encode(req.text).tolist()
    payload = {"text": req.text}
    client.upsert(
        collection_name=collection,
        points=[
            {
                "id": point_id,
                "vector": vector,
                "payload": payload
            }
        ]
    )
    return {"result": f"Text added to collection '{collection}' with id {point_id}"}

@app.post("/batch_add")
def batch_add_to_collection(req: BatchAddRequest):
    client = QdrantClient(
        host=QDRANT_HOST,
        port=QDRANT_PORT,
        api_key=req.qdrant_api_key,
        https=False
    )
    collection = sanitize_collection_name(req.collection_name)
    try:
        exists = client.get_collection(collection_name=collection)
    except Exception:
        dim = MODEL.get_sentence_embedding_dimension()
        client.recreate_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE)
        )
    import uuid
    ids = []
    points = []
    for text in req.texts:
        point_id = str(uuid.uuid4())
        ids.append(point_id)
        vector = MODEL.encode(text).tolist()
        payload = {"text": text}
        points.append({
            "id": point_id,
            "vector": vector,
            "payload": payload
        })
    client.upsert(
        collection_name=collection,
        points=points
    )
    return {"result": f"Batch added {len(ids)} texts to collection '{collection}'", "ids": ids}

@app.post("/delete")
def delete_collection(req: DeleteRequest):
    client = QdrantClient(
        host=QDRANT_HOST,
        port=QDRANT_PORT,
        api_key=req.qdrant_api_key,
        https=False
    )
    collection = sanitize_collection_name(req.collection_name)
    try:
        client.delete_collection(collection_name=collection)
        return {"result": f"Collection '{collection}' deleted."}
    except Exception as e:
        return {"error": str(e)}

@app.get("/list")
def list_collections(request: Request):
    # Accept API key from query param or header
    api_key = request.query_params.get('qdrant_api_key') or request.headers.get('X-Qdrant-Api-Key')
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing qdrant_api_key")
    client = QdrantClient(
        host=QDRANT_HOST,
        port=QDRANT_PORT,
        api_key=api_key,
        https=False
    )
    try:
        resp = client.get_collections()
        names = [c.name for c in resp.collections]
        return {"collections": names}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)