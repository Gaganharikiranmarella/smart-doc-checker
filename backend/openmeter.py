# backend/openmeter.py
import os, time, uuid, httpx

OM_URL = os.getenv("OPENMETER_API_URL", "https://api.cloud.openmeter.io")
OM_KEY = os.getenv("OPENMETER_API_KEY")

# CloudEvents spec headers + JSON body
def _cloudevent(event_type: str, subject: str, user_id: str, data: dict):
    # ce-id must be unique; use stable UUID when dedup desired
    return {
        "specversion": "1.0",
        "id": str(uuid.uuid4()),
        "source": f"smart-doc-checker/{user_id}",
        "type": event_type,                 # e.g., doc.analyzed
        "subject": subject,                 # path or batch id
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "datacontenttype": "application/json",
        "data": data or {}
    }

async def ingest_event(event_type: str, subject: str, user_id: str, units: int = 1, extra: dict = None):
    evt = _cloudevent(event_type, subject, user_id, {"units": units, **(extra or {})})
    headers = {
        "Authorization": f"Bearer {OM_KEY}",   # Bearer token
        "Content-Type": "application/cloudevents+json"
    }
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.post(f"{OM_URL}/api/v1/events", headers=headers, json=evt)
        r.raise_for_status()
        return True
