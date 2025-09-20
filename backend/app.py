# backend/app.py
import os
import sys
import uuid
import asyncio
from typing import List

# --- Make imports robust whether launched from root or /backend
HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
for p in [ROOT, HERE]:
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# Use absolute package-style imports that work with sys.path tweak
from backend.storage import init_user, new_batch, add_doc, record_conflicts, get_batch, incr, get_totals
from backend.models import AnalyzeResponse, ReportResponse
from backend.nli import detect_conflicts
from reportlab.pdfgen import canvas
from backend.openmeter import ingest_event

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
SITE_URL = os.getenv("SITE_URL", "http://localhost:5173")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(ROOT, "uploads"))
REPORT_DIR = os.getenv("REPORT_DIR", os.path.join(ROOT, "reports"))
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

# -----------------------------------------------------------------------------
# App + CORS
# -----------------------------------------------------------------------------
app = FastAPI(title="Smart Doc Checker")

origins = [
    SITE_URL,
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,      # allow dev frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)  # CORS configuration per FastAPI guide [web:129].

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def save_upload(file: UploadFile) -> str:
    path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}_{file.filename}")
    with open(path, "wb") as f:
        f.write(file.file.read())
    return path  # Persist file for analysis and reporting [web:113].

def read_text(path: str) -> str:
    # Demo-only: treat as UTF-8 text; replace with PDF/DOCX parser for production
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()  # Minimal ingestion for prototype [web:113].

def run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.create_task(coro)  # Safe when uvicorn already has a loop [web:113].

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.post("/init")
def init(user_id: str = Form(...)):
    init_user(user_id)
    bid = new_batch(user_id)
    return {"batch_id": bid, "totals": get_totals(user_id)}  # Initialize user totals and batch [web:113].

@app.post("/upload")
def upload(file: UploadFile, batch_id: str = Form(...), user_id: str = Form(...)):
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")  # Basic validation for request body [web:113].
    path = save_upload(file)
    add_doc(batch_id, path)
    try:
        _ = read_text(path)  # Parse must succeed before metering
        run_async(ingest_event(
            "doc.analyzed",
            subject=path,
            user_id=user_id,
            units=1,
            extra={"batch_id": batch_id, "filename": os.path.basename(path)}
        ))  # Send CloudEvent with Bearer auth to OpenMeter Cloud [web:76][web:81][web:87].
        incr(user_id, "docs_analyzed", 1)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"parse_failed: {e}"}, status_code=200)  # Don’t meter on failure [web:76].
    return {"ok": True, "path": path}  # Frontend can refresh totals after [web:113].

@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(batch_id: str = Form(...), user_id: str = Form(...)):
    batch = get_batch(batch_id)
    docs: List[str] = batch.get("docs", [])
    if len(docs) < 2:
        raise HTTPException(status_code=400, detail="Upload at least 2 documents before analysis")  # Guardrail for UX [web:113].
    texts = []
    for p in docs:
        try:
            texts.append((os.path.basename(p), read_text(p)))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read {p}: {e}")  # Handle malformed inputs [web:113].
    conflicts = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a_name, a_text = texts[i]
            b_name, b_text = texts[j]
            conflicts.extend(detect_conflicts(a_name, a_text, b_name, b_text))  # Uses OpenRouter per its quickstart/auth docs [web:14][web:22][web:15].
    record_conflicts(batch_id, conflicts)
    totals = get_totals(user_id)
    return AnalyzeResponse(
        batch_id=batch_id,
        conflicts=conflicts,
        docs_analyzed=totals["docs_analyzed"],
        reports_generated=totals["reports_generated"],
    )  # Typed response for frontend [web:113].

@app.post("/report", response_model=ReportResponse)
def report(batch_id: str = Form(...), user_id: str = Form(...)):
    batch = get_batch(batch_id)
    conflicts = batch.get("conflicts", [])
    report_path = os.path.join(REPORT_DIR, f"{batch_id}.pdf")

    c = canvas.Canvas(report_path)
    c.setTitle("Smart Doc Checker - Contradictions Report")
    c.drawString(30, 800, "Smart Doc Checker - Contradictions Report")
    y = 780
    for k, cf in enumerate(conflicts[:300], start=1):
        line = f"{k}. [{cf['doc_a']}] {cf['span_a']} || [{cf['doc_b']}] {cf['span_b']}"
        for seg in [line[i:i+95] for i in range(0, len(line), 95)]:
            c.drawString(30, y, seg); y -= 14
            if y < 40: c.showPage(); y = 800
        expl = f"    -> {cf.get('explanation','')}"
        for seg in [expl[i:i+95] for i in range(0, len(expl), 95)]:
            c.drawString(30, y, seg); y -= 14
            if y < 40: c.showPage(); y = 800
    c.save()  # Simple paginated report for demo [web:113].

    run_async(ingest_event(
        "report.generated",
        subject=batch_id,
        user_id=user_id,
        units=1,
        extra={"conflict_count": len(conflicts)}
    ))  # Meter on success with OpenMeter’s events API [web:76][web:87].
    incr(user_id, "reports_generated", 1)
    totals = get_totals(user_id)
    return ReportResponse(
        batch_id=batch_id,
        report_url=f"/download/{batch_id}",
        docs_analyzed=totals["docs_analyzed"],
        reports_generated=totals["reports_generated"],
    )  # Return download path and counters [web:113].

@app.get("/download/{batch_id}")
def download(batch_id: str):
    path = os.path.join(REPORT_DIR, f"{batch_id}.pdf")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Report not found")  # Standard 404 for missing asset [web:113].
    return FileResponse(path, media_type="application/pdf", filename=f"report_{batch_id}.pdf")  # Static file serving [web:113].

def reanalyze_batch(batch_id: str):
    # Placeholder hook for external monitor integration (e.g., Pathway or polling)
    try:
        _ = get_batch(batch_id)
    except Exception:
        pass  # No-op in demo [web:113].
