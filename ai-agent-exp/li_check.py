from llama_index.core.settings import Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core import StorageContext, load_index_from_storage

# Set the global embedding model and disable LLM
Settings.embed_model = HuggingFaceEmbedding(model_name="all-MiniLM-L6-v2")
Settings.llm = None

# Load the persisted LlamaIndex
storage_context = StorageContext.from_defaults(persist_dir="/root/livekit.ecommcube.com/ai-agent/llamaindex")
index = load_index_from_storage(storage_context)
query_engine = index.as_query_engine(embed_model=Settings.embed_model, llm=None)

# Query for 'jump start'
query = "jump start"
result = query_engine.query(query)

print(f"Query: {query}\n")
print("Result:")
print(result) 