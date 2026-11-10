"""Small, self-contained document RAG service for the manufacturing copilot."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import certifi
from pydantic import BaseModel, Field
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
DOCS = ROOT / "documents"
STATIC = Path(__file__).parent / "static"
TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-./][a-z0-9]+)*", re.I)
DIM = 384
STOP_WORDS = {"what", "which", "when", "where", "who", "why", "how", "the", "and", "for", "from", "with", "that", "this", "does", "do", "should", "can", "could", "would", "is", "are", "was", "were", "be", "it", "its", "a", "an", "of", "to", "in", "on", "by", "my", "i", "or", "mean", "operator", "recommended", "many", "pieces", "inspect"}


@dataclass
class Chunk:
    text: str
    document_id: str
    revision: str
    page: int
    title: str
    vector: list[float]


def embed(text: str) -> list[float]:
    """Deterministic signed feature-hashing embedding (no model download/API needed)."""
    tokens = [t.lower() for t in TOKEN_RE.findall(text)]
    features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    v = [0.0] * DIM
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        n = int.from_bytes(digest, "little")
        v[n % DIM] += 1.0 if (n >> 10) & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def normalize_term(term: str) -> str:
    term = term.lower()
    if len(term) > 5 and term.endswith("ed"):
        return term[:-1] if term[:-1].endswith("e") else term[:-2]
    if len(term) > 5 and term.endswith("ing"):
        return term[:-3]
    if len(term) > 4 and term.endswith("s") and not term.endswith("ss"):
        return term[:-1]
    return term


def terms(text: str) -> set[str]:
    return {normalize_term(t) for t in TOKEN_RE.findall(text)}


def numeric_range_match(question: str, text: str) -> bool:
    """Match a queried quantity to a numeric interval in a document table."""
    values = [int(value.replace(",", "")) for value in re.findall(r"(?<![\w.])\d[\d,]*(?![\w.])", question)]
    ranges = [
        (int(low.replace(",", "")), int(high.replace(",", "")))
        for low, high in re.findall(r"(?<![\w.])(\d[\d,]*)\s*[-–—]\s*(\d[\d,]*)(?![\w.])", text)
    ]
    return any(low <= value <= high for value in values for low, high in ranges)


def metadata(path: Path) -> tuple[str, str, str]:
    name = path.name
    if name.startswith("MNT-MAN-CNC-02"):
        return "MNT-MAN-CNC-02", "02", "TX-200 Preventive Maintenance Manual"
    if name.startswith("SAF-SOP-003"):
        return "SAF-SOP-003", "05", "Lockout / Tagout Safety Procedure"
    if name.startswith("QC-SOP-014_Rev03"):
        return "QC-SOP-014", "03", "Incoming Material Inspection SOP"
    if name.startswith("QC-SOP-014_Rev04"):
        return "QC-SOP-014", "04", "Incoming Material Inspection SOP"
    return path.stem, "", path.stem


def split_chunks(text: str, max_chars: int = 1050, overlap: int = 140) -> list[str]:
    # Keep PDF lines intact so table labels and their values remain retrievable together.
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines() if line.strip()]
    chunks: list[str] = []
    current: list[str] = []
    for line in lines:
        if len(line) > max_chars:
            if current:
                chunks.append("\n".join(current))
                current = []
            start = 0
            while start < len(line):
                end = min(start + max_chars, len(line))
                chunks.append(line[start:end])
                if end == len(line):
                    break
                start = end - overlap
            continue
        candidate = "\n".join(current + [line])
        if len(candidate) > max_chars and current:
            chunks.append("\n".join(current))
            tail: list[str] = []
            for prior in reversed(current):
                if len("\n".join([prior] + tail)) > overlap:
                    break
                tail.insert(0, prior)
            current = tail + [line]
        else:
            current.append(line)
    if current:
        chunks.append("\n".join(current))
    return chunks


def ingest() -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(DOCS.glob("*.pdf")):
        if path.name == "Sample_Questions.pdf":
            continue
        doc_id, revision, title = metadata(path)
        reader = PdfReader(str(path))
        for page_no, page in enumerate(reader.pages, 1):
            body = page.extract_text(extraction_mode="layout") or ""
            for piece in split_chunks(body):
                chunks.append(Chunk(piece, doc_id, revision, page_no, title, embed(piece)))
    return chunks


INDEX = ingest()
app = FastAPI(title="Manufacturing AI Copilot", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class GeminiUnavailableError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def current_revision(chunks: list[Chunk]) -> dict[str, str]:
    revisions: dict[str, str] = {}
    for chunk in chunks:
        if chunk.revision and (chunk.document_id not in revisions or chunk.revision > revisions[chunk.document_id]):
            revisions[chunk.document_id] = chunk.revision
    return revisions


def retrieve(question: str, limit: int = 5) -> list[tuple[Chunk, float]]:
    q = embed(question)
    focus = {normalize_term(t) for t in TOKEN_RE.findall(question) if len(t) > 2 and t.lower() not in STOP_WORDS}
    latest = current_revision(INDEX)
    scored = []
    for chunk in INDEX:
        # Rev 04 explicitly supersedes Rev 03. Do not expose the superseded SOP as
        # a source for operational answers; it remains indexed only for inventory.
        if chunk.document_id == "QC-SOP-014" and chunk.revision != latest.get("QC-SOP-014"):
            continue
        score = cosine(q, chunk.vector)
        # Blend the hashed vector similarity with exact term coverage. This reduces
        # collisions in a tiny, local corpus while retaining word/bigram retrieval.
        chunk_terms = terms(chunk.text)
        coverage = len(focus & chunk_terms) / max(len(focus), 1)
        score += 0.8 * coverage
        if numeric_range_match(question, chunk.text):
            score += 0.55
        scored.append((chunk, score))
    return sorted(scored, key=lambda x: x[1], reverse=True)[:max(limit, 10)]


def llm_answer(question: str, evidence: list[tuple[Chunk, float]]) -> str | None:
    """Call Gemini's native Interactions REST API when configured."""
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    if not api_key:
        raise GeminiUnavailableError("Gemini is not configured. Copy .env.example to .env, add GEMINI_API_KEY, and restart the app.", 503)
    context = "\n\n".join(f"[{c.document_id}, Rev {c.revision}, p. {c.page}] {c.text}" for c, _ in evidence)
    prompt = (
        "Answer using only the supplied excerpts. Be concise and preserve safety steps. "
        "If evidence is insufficient, say the documents do not provide the answer. "
        "Never infer missing values. Cite each factual claim using the exact bracketed source citation "
        "shown with its excerpt, including document ID, revision, and page.\n\n"
        f"Question: {question}\n\nEvidence:\n{context}"
    )
    payload = {
        "model": model,
        "input": prompt,
        "generation_config": {"temperature": 0},
    }
    url = "https://generativelanguage.googleapis.com/v1beta/interactions"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"x-goog-api-key": api_key, "Content-Type": "application/json"}, method="POST")
    try:
        tls_context = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(req, timeout=25, context=tls_context) as response:
            data = json.loads(response.read())
            text = "".join(
                item.get("text", "")
                for step in data["steps"]
                if step.get("type") == "model_output"
                for item in step.get("content", [])
                if item.get("type") == "text"
            ).strip()
            if not text:
                raise GeminiUnavailableError("Gemini returned an empty answer. Please retry.")
            return text
    except urllib.error.HTTPError as exc:
        # Keep any API detail useful, but never echo request headers or the key.
        try:
            error_data = json.loads(exc.read())
            message = error_data.get("error", {}).get("message", "")
        except (json.JSONDecodeError, AttributeError):
            message = ""
        detail = f": {message}" if message else ""
        raise GeminiUnavailableError(f"Gemini API request failed (HTTP {exc.code}){detail}") from None
    except urllib.error.URLError as exc:
        reason = str(exc.reason).replace(api_key, "[redacted]")[:180]
        raise GeminiUnavailableError(f"Could not connect to Gemini ({reason}). Check internet access, VPN/proxy, or firewall settings and retry.") from None
    except (TimeoutError, OSError) as exc:
        reason = str(exc).replace(api_key, "[redacted]")[:180]
        raise GeminiUnavailableError(f"Could not connect to Gemini ({reason}). Check internet access, VPN/proxy, or firewall settings and retry.") from None
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise GeminiUnavailableError("Gemini returned an unexpected response. Check the model setting and try again.") from None


@app.get("/")
def home() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/documents")
def documents() -> dict[str, Any]:
    docs = {}
    for chunk in INDEX:
        key = (chunk.document_id, chunk.revision)
        docs[key] = {"document_id": chunk.document_id, "revision": chunk.revision, "title": chunk.title}
    latest = current_revision(INDEX)
    return {"documents": [{**entry, "current": latest.get(entry["document_id"]) == entry["revision"]} for entry in docs.values()]}


@app.post("/api/ask")
def ask(body: AskRequest) -> dict[str, Any]:
    matches = retrieve(body.question)
    best = matches[0][1] if matches else -1
    focus_terms = {normalize_term(t) for t in TOKEN_RE.findall(body.question) if len(t) > 2 and t.lower() not in STOP_WORDS}
    evidence_text = terms(" ".join(c.text for c, _ in matches))
    missing_focus = [term for term in focus_terms if term not in evidence_text]
    if numeric_range_match(body.question, " ".join(c.text for c, _ in matches)):
        missing_focus = [term for term in missing_focus if not term.isdigit()]
    # A high vector score caused by a generic word (for example, "supervisor") is not enough.
    # If a third or more of the question's meaningful terms have no textual support, abstain.
    if not matches or best < 0.12 or (focus_terms and len(missing_focus) / len(focus_terms) >= 1 / 3):
        return {"answer": "I couldn't find enough information in the provided manufacturing documents to answer that reliably.", "abstained": True, "mode": "retrieval abstention", "sources": []}
    best_chunk = matches[0][0]
    # Keep neighboring evidence from the same source page too. Long PDF tables can
    # put a label and its numeric value in adjacent chunks.
    matches = [
        (chunk, score) for chunk, score in matches
        if score >= best * 0.8
        or (chunk.document_id, chunk.revision, chunk.page)
        == (best_chunk.document_id, best_chunk.revision, best_chunk.page)
    ]
    try:
        answer = llm_answer(body.question, matches)
    except GeminiUnavailableError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    mode = "Gemini answer"
    # Keep sources in the response as independently verifiable citations.
    source_pages: dict[tuple[str, str, int], dict[str, Any]] = {}
    for chunk, score in matches:
        key = (chunk.document_id, chunk.revision, chunk.page)
        entry = source_pages.setdefault(key, {
            "document_id": chunk.document_id, "revision": chunk.revision,
            "page": chunk.page, "title": chunk.title, "excerpts": [], "score": round(score, 3),
        })
        if chunk.text not in entry["excerpts"]:
            entry["excerpts"].append(chunk.text)
    sources = [
        # Later neighboring chunks often contain the table value just after its label.
        {**entry, "excerpt": "\n…\n".join(reversed(entry.pop("excerpts")))[:1200]}
        for entry in source_pages.values()
    ]
    return {"answer": answer, "abstained": False, "mode": mode, "sources": sources}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "chunks": len(INDEX), "llm_configured": bool(os.getenv("GEMINI_API_KEY"))}
