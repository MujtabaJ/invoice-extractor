"""FastAPI service: upload documents, review the queue, export approved data.

Run:  uvicorn app.api:app --reload      Docs: http://localhost:8000/docs
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import tempfile
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ie.extractors import make_extractor
from ie.pipeline import Pipeline
from ie.store import Store

log = logging.getLogger("ie")
logging.basicConfig(level=logging.INFO, format="%(message)s")

pipeline = Pipeline(
    make_extractor(os.environ.get("IE_PROVIDER", "offline"),
                   os.environ.get("IE_OPENAI_MODEL", "gpt-4o-mini"),
                   os.environ.get("IE_ANTHROPIC_MODEL", "claude-3-5-haiku-latest")),
    Store(os.environ.get("IE_DB", "invoices.db")),
    auto_approve_at=float(os.environ.get("IE_AUTO_APPROVE_AT", "0.85")),
)
app = FastAPI(title="Invoice Extractor", version="0.1.0")

ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
MAX_BYTES = 15 * 1024 * 1024
RATE_LIMIT_PER_MIN = int(os.environ.get("IE_RATE_LIMIT_PER_MIN", "60"))
_calls: dict[str, deque] = defaultdict(deque)


def _keys() -> dict[str, str]:
    """IE_API_KEYS="key1:org1,key2:org2" maps API keys to tenants."""
    pairs = [p.split(":", 1) for p in os.environ.get("IE_API_KEYS", "change-me:default").split(",") if ":" in p]
    return {k.strip(): o.strip() for k, o in pairs}


def tenant(x_api_key: str = Header(default="")) -> str:
    for key, org in _keys().items():
        if x_api_key and hmac.compare_digest(x_api_key, key):
            q, now = _calls[org], time.time()
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= RATE_LIMIT_PER_MIN:
                raise HTTPException(429, "Rate limit exceeded")
            q.append(now)
            return org
    raise HTTPException(401, "Invalid or missing X-API-Key")


class ReviewIn(BaseModel):
    decision: str  # approved | rejected
    reviewer: str
    corrected: dict | None = None  # full corrected invoice JSON, optional


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/documents")
async def upload(files: list[UploadFile] = File(...), org: str = Depends(tenant)) -> list[dict]:
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for f in files:
            name = Path(f.filename or "upload").name
            if Path(name).suffix.lower() not in ALLOWED:
                raise HTTPException(415, f"Unsupported file type: {name}")
            data = await f.read()
            if len(data) > MAX_BYTES:
                raise HTTPException(413, f"File too large: {name}")
            path = Path(tmp) / name
            path.write_bytes(data)
            r = pipeline.process(path, org_id=org)
            log.info(json.dumps({"event": "document", "org": org, "file": name, "status": r.status,
                                 "confidence": r.confidence, "method": r.method, "issues": [i.code for i in r.issues],
                                 "latency_ms": r.latency_ms, "cost_usd": r.cost_usd, "model": r.model}))
            results.append(r.to_dict())
    return results


@app.get("/v1/review")
def review_queue(org: str = Depends(tenant)) -> list[dict]:
    return pipeline.store.queue(org)


@app.post("/v1/review/{doc_id}")
def review(doc_id: int, body: ReviewIn, org: str = Depends(tenant)) -> dict:
    try:
        ok = pipeline.store.review(org, doc_id, body.decision, body.reviewer, body.corrected)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if not ok:
        raise HTTPException(404, "Document not found")
    return {"id": doc_id, "status": body.decision}


@app.get("/v1/export.csv", response_class=PlainTextResponse)
def export(org: str = Depends(tenant)) -> str:
    return pipeline.store.export_csv(org)
