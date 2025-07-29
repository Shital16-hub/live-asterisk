import re
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

class RAGManager:
    _instance = None
    _model = None
    _client = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        if RAGManager._instance is not None:
            raise Exception("This class is a singleton!")
        RAGManager._instance = self
    
    def get_model(self):
        if self._model is None:
            print("Loading SentenceTransformer model...")
            self._model = SentenceTransformer('all-MiniLM-L6-v2')
            print("Model loaded successfully")
        return self._model
    
    def get_client(self):
        if self._client is None:
            print("Initializing Qdrant client...")
            self._client = QdrantClient(
                host=QDRANT_HOST,
                port=QDRANT_PORT,
                api_key=QDRANT_API_KEY,
                https=False
            )
            print("Qdrant client initialized")
        return self._client

def sanitize_collection_name(name: str) -> str:
    """Only alphanumerics and underscores, can't start with digit, lowercase."""
    clean = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in name)
    if clean and clean[0].isdigit():
        clean = "_" + clean
    return clean.lower()

def parse_text_payload(text: str) -> dict:
    """
    Parse a single 'text' field into a dict:
      SERVICE: Bus Towing
      BASE_PRICE: 400
      ...
      PRICING_RULES:
      - Base price: $400
      - Distance: $4.00 per mile
    → {
        'service': 'Bus Towing',
        'base_price': '400',
        ...,
        'pricing_rules': ['Base price: $400', ...]
      }
    """
    parsed = {}
    lines  = [ln.strip() for ln in text.splitlines() if ln.strip()]
    key_re = re.compile(r'^([A-Z_]+):\s*(.*)$')
    current = None

    for ln in lines:
        if ln.startswith('- ') and current:
            parsed.setdefault(current, []).append(ln[2:].strip())
            continue

        m = key_re.match(ln)
        if m:
            raw_key, val = m.groups()
            key = raw_key.lower()
            if key == 'pricing_rules':
                parsed[key] = []
                current = key
            else:
                parsed[key] = val
                current = key
        else:
            # continuation of previous key
            if current:
                if isinstance(parsed[current], list):
                    parsed[current].append(ln)
                else:
                    parsed[current] += ' ' + ln
    return parsed

# ——— Configuration ———
RAW_NAME        = 'towing-services'
COLLECTION_NAME = sanitize_collection_name(RAW_NAME)

QDRANT_HOST = 'localhost'
QDRANT_PORT = 6333
QDRANT_API_KEY = '2123tt'

def get_rag_context(history, top_k=1):
    """
    Return the single best match for the last user utterance.
    """
    if not history:
        return "No conversation history provided."

    # Get the RAG manager instance
    rag = RAGManager.get_instance()
    
    # Get model and client (they will be loaded only when first needed)
    model = rag.get_model()
    client = rag.get_client()

    vec = model.encode(history[-1]).tolist()
    resp = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vec,
        limit=top_k,
        with_payload=True
    )
    hits = resp.points
    if not hits:
        return "No relevant context found."

    raw = hits[0].payload.get('text')
    data = parse_text_payload(raw) if isinstance(raw, str) else hits[0].payload

    parts = []
    if 'service'     in data: parts.append(f"Service: {data['service']}")
    if 'description' in data: parts.append(f"Description: {data['description']}")
    if 'base_price'  in data: parts.append(f"Base price: ${data['base_price']}")
    if 'requirements'in data:
        reqs = data['requirements']
        if isinstance(reqs, list): reqs = ", ".join(reqs)
        parts.append(f"Requirements: {reqs}")
    if 'time' in data: parts.append(f"Time: {data['time']}")
    if 'pricing_rules' in data and data['pricing_rules']:
        parts.append("Pricing rules:")
        for rule in data['pricing_rules']:
            parts.append(f"  - {rule}")

    return "\n\n**Retrival Augmented Generation Response. USE THESE RESULTS TO ANSWER THE USER'S QUESTION IF APPLICABLE AND RELEVANT.**:\n```" +"\n".join(parts) + "```"

def get_rag_contexts(history, top_k=1):
    """
    Return the top_k matches for the last user utterance, each formatted.
    """
    if not history:
        return "No conversation history provided."

    # Get the RAG manager instance
    rag = RAGManager.get_instance()
    
    # Get model and client (they will be loaded only when first needed)
    model = rag.get_model()
    client = rag.get_client()

    vec = model.encode(history[-1]).tolist()
    resp = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vec,
        limit=top_k,
        with_payload=True
    )
    hits = resp.points
    if not hits:
        return "No relevant contexts found."

    lines = []
    
    for idx, pt in enumerate(hits, start=1):
        raw = pt.payload.get('text')
        data = parse_text_payload(raw) if isinstance(raw, str) else pt.payload
        lines.append(f"Result #{idx} (score={pt.score:.3f}):")
        if 'service' in data:     lines.append(f"  • Service: {data['service']}")
        if 'description' in data: lines.append(f"  • Description: {data['description']}")
        if 'base_price' in data:  lines.append(f"  • Base price: ${data['base_price']}")
        if 'requirements' in data:
            reqs = data['requirements']
            if isinstance(reqs, list): reqs = ", ".join(reqs)
            lines.append(f"  • Requirements: {reqs}")
        if 'time' in data:        lines.append(f"  • Time: {data['time']}")
        if 'pricing_rules' in data and data['pricing_rules']:
            lines.append("  • Pricing rules:")
            for rule in data['pricing_rules']:
                lines.append(f"    - {rule}")
        lines.append("")  # blank line

    res = "\n\n**USE THESE RAG RESULTS TO ANSWER THE USER'S QUESTION IF APPLICABLE AND RELEVANT.Consider score of the results and use the most relevant and applicable results.**:\n```" + f"User Question: {history[-1]}\nRAG Results: " + "\n".join(lines) + "```"
    return res

# if __name__ == "__main__":
#     print(f"Using Qdrant collection: {COLLECTION_NAME}\n")

#     # # Single best match:
#     # hist = ["jump start service"]
#     hist = ["girlfriend"]
#     # print("=== Single best match ===")
#     # print(get_rag_context(hist, top_k=1), "\n")

#     # Top 2 matches:
#     # print("=== Top 2 matches ===")
#     # print(get_rag_contexts(hist, top_k=2), "\n")

#     # cnt = client.count(collection_name=COLLECTION_NAME, exact=True)
#     # print(f"Total points in collection: {cnt}")

#     context = get_rag_contexts(hist, top_k=1)
#     print(context)