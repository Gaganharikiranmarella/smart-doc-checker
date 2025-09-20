# backend/models.py
from pydantic import BaseModel
from typing import List, Optional

class Conflict(BaseModel):
    doc_a: str
    span_a: str
    doc_b: str
    span_b: str
    type: str
    explanation: str

class AnalyzeResponse(BaseModel):
    batch_id: str
    conflicts: List[Conflict]
    docs_analyzed: int
    reports_generated: int

class ReportResponse(BaseModel):
    batch_id: str
    report_url: str
    docs_analyzed: int
    reports_generated: int

class UsageTotals(BaseModel):
    docs_analyzed: int
    reports_generated: int
