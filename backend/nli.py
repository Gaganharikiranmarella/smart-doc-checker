# backend/nli.py
import re
from typing import List, Tuple
from ai import ask_model

def extract_sentences(text: str) -> List[str]:
    return re.split(r'(?<=[.!?])\s+', text.strip())

def heuristic_pairs(sentences_a: List[str], sentences_b: List[str]) -> List[Tuple[str,str]]:
    # Simple overlap by shared key phrases and numbers
    pairs = []
    for sa in sentences_a:
        for sb in sentences_b:
            if any(tok in sb for tok in re.findall(r'\b\d+%?\b', sa)) or len(set(sa.lower().split()) & set(sb.lower().split())) > 3:
                pairs.append((sa, sb))
    return pairs[:50]

PROMPT = """You compare two policy sentences for contradiction.
Return JSON with fields: type (contradiction/overlap/neutral), explanation (1-2 sentences).
Keep it concise and precise for compliance review."""

def adjudicate(sa: str, sb: str):
    res = ask_model(
        "You are a compliance reviewer expert at contradictions.",
        f"{PROMPT}\nA: {sa}\nB: {sb}"
    )
    return res

def detect_conflicts(doc_a_name, a_text, doc_b_name, b_text):
    a_sents, b_sents = extract_sentences(a_text), extract_sentences(b_text)
    pairs = heuristic_pairs(a_sents, b_sents)
    conflicts = []
    for sa, sb in pairs:
        out = adjudicate(sa, sb)
        if '"contradiction"' in out or 'contradiction' in out.lower():
            conflicts.append({
                "doc_a": doc_a_name, "span_a": sa,
                "doc_b": doc_b_name, "span_b": sb,
                "type": "contradiction",
                "explanation": out
            })
    return conflicts
