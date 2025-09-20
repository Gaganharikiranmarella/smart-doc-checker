# backend/app.py
import os
import io
import uuid
import asyncio
from typing import List

from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# Local modules from the scaffold
from storage import init_user, new_batch, add_doc, record_conflicts, get_batch, incr, get_totals  # in-memory demo store
from models import AnalyzeResponse, ReportResponse                                            # pydantic DTOs
from nli import detect_conflicts                                                              # heuristic+LLM adjudication
from reportlab.pdfgen import canvas                                                           # simple PDF generator

# OpenMeter ingestion (CloudEvents over HTTP)
from openmeter import ingest_event                                                            # async event ingest

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
SITE_URL = os.getenv("SITE_URL", "http://localhost:5173")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
REPORT_DIR = os.getenv("REPORT_DIR", "reports")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = FastAPI(title="Smart Doc Checker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[SITE_URL, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def save_upload(file: UploadFile) -> str:
    """Persist uploaded file to disk and return path."""
    # For demo: trust filename; in prod sanitize and scan
    path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}_{file.filename}")
    with open(path, "wb") as f:
        f.write(file.file.read())
    return path

def read_text(path: str) -> str:
    """Very simplified reader: assumes UTF-8 text; swap in PDF/docx parsers for real use."""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def _safe_async(coro):
    """Run an async coroutine from sync path without leaking loop state."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # If already in an event loop (e.g., uvicorn workers), create a task
        loop = asyncio.get_event_loop()
        return loop.create_task(coro)

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.post("/init")
def init(user_id: str = Form(...)):
    """Initialize a user session and create a new analysis batch."""
    init_user(user_id)
    bid = new_batch(user_id)
    totals = get_totals(user_id)
    return {"batch_id": bid, "totals": totals}

@app.post("/upload")
def upload(file: UploadFile, batch_id: str = Form(...), user_id: str = Form(...)):
    """
    Upload a document into the batch.
    Bills via OpenMeter after a successful parse (doc.analyzed, units=1).
    """
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")
    path = save_upload(file)
    add_doc(batch_id, path)
    # Bill per-document only after a successful text read
    try:
        _ = read_text(path)
        _safe_async(ingest_event(
            "doc.analyzed", subject=path, user_id=user_id, units=1,
            extra={"batch_id": batch_id, "filename": os.path.basename(path)}
        ))
        incr(user_id, "docs_analyzed", 1)
    except Exception as e:
        # Parsing failed; do not meter or increment totals
        return JSONResponse({"ok": False, "error": f"parse_failed: {e}"}, status_code=200)
    return {"ok": True, "path": path}

@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(batch_id: str = Form(...), user_id: str = Form(...)):
    """
    Run contradiction detection across all pairs of uploaded docs in the batch.
    Stores conflicts in memory for subsequent report generation.
    """
    batch = get_batch(batch_id)
    docs: List[str] = batch.get("docs", [])
    if len(docs) < 2:
        raise HTTPException(status_code=400, detail="Upload at least 2 documents before analysis")

    # Load texts
    texts = []
    for p in docs:
        try:
            texts.append((os.path.basename(p), read_text(p)))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read {p}: {e}")

    # Pairwise detect conflicts
    conflicts = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a_name, a_text = texts[i]
            b_name, b_text = texts[j]
            conflicts.extend(detect_conflicts(a_name, a_text, b_name, b_text))

    record_conflicts(batch_id, conflicts)
    totals = get_totals(user_id)
    return AnalyzeResponse(
        batch_id=batch_id,
        conflicts=conflicts,
        docs_analyzed=totals["docs_analyzed"],
        reports_generated=totals["reports_generated"]
    )

@app.post("/report", response_model=ReportResponse)
def report(batch_id: str = Form(...), user_id: str = Form(...)):
    """
    Generate a PDF report of detected contradictions for the batch.
    Bills via OpenMeter on successful report creation (report.generated, units=1).
    """
    batch = get_batch(batch_id)
    conflicts = batch.get("conflicts", [])
    report_path = os.path.join(REPORT_DIR, f"{batch_id}.pdf")

    # Create a very simple PDF
    c = canvas.Canvas(report_path)
    c.setTitle("Smart Doc Checker - Contradictions Report")
    c.drawString(30, 800, "Smart Doc Checker - Contradictions Report")
    y = 780
    for k, cf in enumerate(conflicts[:300], start=1):
        line = f"{k}. [{cf['doc_a']}] {cf['span_a']} || [{cf['doc_b']}] {cf['span_b']}"
        # Wrap manually
        for seg in [line[i:i+95] for i in range(0, len(line), 95)]:
            c.drawString(30, y, seg)
            y -= 14
            if y < 40:
                c.showPage()
                y = 800
        # Include explanation on next line
        expl = f"    -> {cf.get('explanation','')}"
        for seg in [expl[i:i+95] for i in range(0, len(expl), 95)]:
            c.drawString(30, y, seg)
            y -= 14
            if y < 40:
                c.showPage()
                y = 800
    c.save()

    # Bill per report (only after save succeeds)
    _safe_async(ingest_event(
        "report.generated", subject=batch_id, user_id=user_id, units=1,
        extra={"conflict_count": len(conflicts)}
    ))
    incr(user_id, "reports_generated", 1)
    totals = get_totals(user_id)

    return ReportResponse(
        batch_id=batch_id,
        report_url=f"/download/{batch_id}",
        docs_analyzed=totals["docs_analyzed"],
        reports_generated=totals["reports_generated"]
    )

@app.get("/download/{batch_id}")
def download(batch_id: str):
    """Download the generated PDF report."""
    path = os.path.join(REPORT_DIR, f"{batch_id}.pdf")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(path, media_type="application/pdf", filename=f"report_{batch_id}.pdf")

# Called by the monitor when an external policy page changes
def reanalyze_batch(batch_id: str):
    """
    Example hook for a monitor to trigger re-analysis.
    In a real system, the monitor would know the user_id; for demo, no-op or resolve from storage.
    """
    try:
        batch = get_batch(batch_id)
        user_id = batch.get("user_id")
        if not user_id:
            return
        # Trigger analysis; callers should POST /analyze for a proper response
        # This placeholder demonstrates where the logic would be invoked.
    except Exception:
        pass
