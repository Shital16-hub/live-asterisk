import requests

def search_collection(collection_name, query_string, top_k=3, server_url="http://localhost:8000"):
    payload = {
        "collection_name": collection_name,
        "query_string": query_string,
        "top_k": top_k,
        "qdrant_api_key": "2123tt"
    }
    print(f"Searching '{collection_name}' for: {query_string}")
    resp = requests.post(f"{server_url}/search", json=payload)
    print("Status:", resp.status_code)
    try:
        data = resp.json()
        results = data.get("result", [])
        if not results:
            return "No relevant context found."
            
        # Format results into a single string
        formatted_results = []
        for idx, res in enumerate(results, 1):
            text = res.get("text", str(res))
            formatted_results.append(f"Result {idx}: {text}")
            
        return "\n".join(formatted_results)
    except Exception as e:
        print(f"Error: {str(e)}")
        print("Raw response:", resp.text)
        return "Error processing search results"

if __name__ == "__main__":
    # Example usage
    results = search_collection("towing_services_doc", "jump start")
    print("\nSearch Results:")
    print(results) 