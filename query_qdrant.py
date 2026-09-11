from qdrant_client import QdrantClient
c = QdrantClient(host="localhost", port=6333)
res, _ = c.scroll(collection_name="person_embeddings", with_payload=True, limit=5)
for r in res:
    print(r.payload.get("person_id"), r.payload.get("snapshot"), r.payload.get("timestamp"))
