# backend/storage.py
import uuid, os, json

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

state = {
    "batches": {},  # batch_id -> {docs: [paths], conflicts: [...], totals: {...}}
    "totals": {}    # user_id -> {docs_analyzed, reports_generated}
}

def init_user(user_id):
    state["totals"].setdefault(user_id, {"docs_analyzed":0, "reports_generated":0})

def new_batch(user_id):
    bid = str(uuid.uuid4())
    state["batches"][bid] = {"user_id": user_id, "docs": [], "conflicts": []}
    return bid

def add_doc(batch_id, path):
    state["batches"][batch_id]["docs"].append(path)

def record_conflicts(batch_id, conflicts):
    state["batches"][batch_id]["conflicts"] = conflicts

def get_batch(batch_id):
    return state["batches"][batch_id]

def incr(user_id, key, n=1):
    state["totals"][user_id][key] += n

def get_totals(user_id):
    return state["totals"][user_id]
