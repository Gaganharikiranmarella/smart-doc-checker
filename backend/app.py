# backend/app.py
import os, io, uuid
from fastapi import FastAPI, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from storage import init_user, new_batch, add_doc, record_conflicts, get_batch, incr, get_totals
from billing import meter_event
from models import AnalyzeResponse, ReportResponse
from nli import detect_conflicts
from reportlab.pdfgen import canvas

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("SITE_URL", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
REPORT_DIR = "reports"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def save_upload(file: UploadFile) -> str:
    path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}_{file.filename}")
    with open(path, "wb") as f:
        f.write(file.file.read())
    return path

def read_text(path: str) -> str:
    # Simplified: assume text docs for demo; plug in PDF/Docx parsers
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

@app.post("/init")
def init(user_id: str = Form(...)):
    init_user(user_id)
    bid = new_batch(user_id)
    return {"batch_id": bid, "totals": get_totals(user_id)}

@app.post("/upload")
def upload(file: UploadFile, batch_id: str = Form(...), user_id: str = Form(...)):
    path = save_upload(file)
    add_doc(batch_id, path)
    # Bill per document analyzed after successful parsing
    try:
        _ = read_text(path)
        meter_event("doc_analyzed", user_id, subject_id=path)
        incr(user_id, "docs_analyzed", 1)
    except Exception:
        pass
    return {"ok": True}

@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(batch_id: str = Form(...), user_id: str = Form(...)):
    batch = get_batch(batch_id)
    docs = batch["docs"]
    texts = [(os.path.basename(p), read_text(p)) for p in docs]
    conflicts = []
    for i in range(len(texts)):
        for j in range(i+1, len(texts)):
            c = detect_conflicts(texts[i][0], texts[i][1], texts[j][0], texts[j][1])
            conflicts.extend(c)
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
    batch = get_batch(batch_id)
    conflicts = batch["conflicts"]
    report_path = os.path.join(REPORT_DIR, f"{batch_id}.pdf")
    c = canvas.Canvas(report_path)
    c.drawString(30, 800, "Smart Doc Checker - Contradictions Report")
    y = 780
    for k, cf in enumerate(conflicts[:40], start=1):
        line = f"{k}. [{cf['doc_a']}] {cf['span_a']} || [{cf['doc_b']}] {cf['span_b']}"
        for seg in [line[i:i+95] for i in range(0, len(line), 95)]:
            c.drawString(30, y, seg); y -= 14
            if y < 40: c.showPage(); y = 800
    c.save()
    # Bill per report generated
    meter_event("report_generated", user_id, subject_id=batch_id)
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
    path = os.path.join(REPORT_DIR, f"{batch_id}.pdf")
    return FileResponse(path, media_type="application/pdf", filename=f"report_{batch_id}.pdf")

def reanalyze_batch(batch_id: str):
    # Helper used by monitor to re-run analysis; in demo, you’d call /analyze with the stored user_id
    pass
