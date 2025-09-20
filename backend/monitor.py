# backend/monitor.py
import time, hashlib, requests, threading
from storage import get_batch
from app import reanalyze_batch  # ensure function exists

def hash_text(t): return hashlib.sha256(t.encode()).hexdigest()

def watch_url(batch_id: str, url: str, interval=60):
    last = None
    def loop():
        nonlocal last
        while True:
            try:
                html = requests.get(url, timeout=5).text
                h = hash_text(html)
                if last and h != last:
                    reanalyze_batch(batch_id)
                last = h
            except Exception:
                pass
            time.sleep(interval)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
