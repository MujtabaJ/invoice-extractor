"""load -> extract -> validate -> score -> route (auto-approve or human review) -> store."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .extractors import Extractor
from .loaders import load
from .schema import Invoice
from .store import Store
from .validate import Issue, score, validate

# Rough list prices in USD per 1M tokens (input, output), for cost estimates only. Update as needed.
PRICES = {"gpt-4o-mini": (0.15, 0.60), "claude-3-5-haiku-latest": (0.80, 4.00)}


@dataclass
class Result:
    file: str
    invoice: Invoice
    issues: list[Issue] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "needs_review"
    method: str = ""
    ocr_confidence: float | None = None
    model: str = ""
    cost_usd: float = 0.0
    latency_ms: int = 0
    doc_id: int | None = None
    duplicate_of_file: bool = False  # exact same file bytes seen before

    def to_dict(self) -> dict:
        return {"file": self.file, "status": self.status, "confidence": self.confidence, "method": self.method,
                "ocr_confidence": self.ocr_confidence, "model": self.model, "cost_usd": round(self.cost_usd, 6),
                "latency_ms": self.latency_ms, "doc_id": self.doc_id, "issues": [i.__dict__ for i in self.issues],
                "invoice": self.invoice.to_json_dict()}


class Pipeline:
    def __init__(self, extractor: Extractor, store: Store | None = None, *, auto_approve_at: float = 0.85,
                 today: date | None = None):
        self.extractor, self.store = extractor, store or Store()
        self.auto_approve_at, self.today = auto_approve_at, today

    def process(self, path: str | Path, org_id: str = "default") -> Result:
        t0 = time.perf_counter()
        path = Path(path)
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        doc = load(path)
        ex = self.extractor.extract(doc.text)
        issues = validate(ex.invoice, today=self.today, seen_numbers=self.store.seen_numbers(org_id))
        if self.store.by_hash(org_id, sha):
            issues.append(Issue("duplicate_file", "file", "error", "this exact file was already processed"))
        conf = score(ex.confidence, issues, doc.ocr_confidence)
        has_error = any(i.severity == "error" for i in issues)
        status = "auto_approved" if conf >= self.auto_approve_at and not has_error else "needs_review"
        pin, pout = PRICES.get(ex.model, (0.0, 0.0))
        res = Result(path.name, ex.invoice, issues, conf, status, doc.method, doc.ocr_confidence, ex.model,
                     (ex.input_tokens * pin + ex.output_tokens * pout) / 1_000_000,
                     int((time.perf_counter() - t0) * 1000))
        if not any(i.code == "duplicate_file" for i in issues):
            res.doc_id = self.store.save(org_id, path.name, sha, res)
        else:
            res.duplicate_of_file = True
        return res
