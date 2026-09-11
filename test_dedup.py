import asyncio
from app.qdrant_client.qdrant_service import QdrantService
qs = QdrantService()
persons = qs.get_all_persons()
for p in persons:
    print(p.get("person_id"), p.get("snapshot"), p.get("person_label"))
