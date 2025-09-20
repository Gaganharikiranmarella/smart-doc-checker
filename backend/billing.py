# backend/billing.py
import os, time, hashlib, requests

FLEX_URL = os.getenv("FLEXPRICE_API_URL", "http://localhost:9000")
FLEX_KEY = os.getenv("FLEXPRICE_API_KEY", "dev-demo-key")

def _idempotency(event_name, user_id, subject_id):
    raw = f"{event_name}:{user_id}:{subject_id}"
    return hashlib.sha256(raw.encode()).hexdigest()

def meter_event(event_name, user_id, subject_id, units=1):
    idem = _idempotency(event_name, user_id, subject_id)
    payload = {
        "event": event_name,
        "user_id": user_id,
        "subject_id": subject_id,
        "units": units,
        "idempotency_key": idem,
        "timestamp": int(time.time())
    }
    try:
        r = requests.post(f"{FLEX_URL}/meter", json=payload, headers={"Authorization": f"Bearer {FLEX_KEY}"}, timeout=3)
        r.raise_for_status()
        return True
    except Exception:
        # For demo, fail-open
        return False
