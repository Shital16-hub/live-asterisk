FROM python:3.10-slim

WORKDIR /app

# COPY rag.py rag.py
# COPY rag_server.py rag_server.py
# copy all files in the current directory
COPY . .

RUN pip install fastapi uvicorn qdrant-client sentence-transformers

EXPOSE 8000

CMD ["uvicorn", "rag_server:app", "--host", "0.0.0.0", "--port", "8000"] 


# docker build -t amitgupta4in/qdrant-rag:v1 . && docker push amitgupta4in/qdrant-rag:v1