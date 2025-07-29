from llama_index.core import SimpleDirectoryReader, VectorStoreIndex, StorageContext
from llama_index.embeddings.openai import OpenAIEmbedding
import os

# Directory containing your text files
doc_dir = os.path.join(os.path.dirname(__file__), "towing_services_doc")
# Output directory for the index
persist_dir = os.path.join(os.path.dirname(__file__), "llamaindex")

# Read all .txt files as documents
documents = SimpleDirectoryReader(input_dir=doc_dir, recursive=False).load_data()

# Use OpenAI embedding if API key is set, else fallback to default
openai_api_key = os.getenv("OPENAI_API_KEY")
if openai_api_key:
    embed_model = OpenAIEmbedding()
else:
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    embed_model = HuggingFaceEmbedding(model_name="all-MiniLM-L6-v2")

# Build the index
index = VectorStoreIndex.from_documents(documents, embed_model=embed_model)

# Persist the index
global_storage_context = StorageContext.from_defaults()
index.storage_context.persist(persist_dir=persist_dir)

print(f"LlamaIndex built and saved to {persist_dir} with {len(documents)} documents.") 