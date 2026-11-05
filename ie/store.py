"""SQLite persistence: processed documents, the review queue and exports.

SQLite keeps the demo dependency-free. db/schema.sql has the PostgreSQL version for production.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  org_id TEXT NOT NULL,
  file_name TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  method TEXT NOT NULL,
  ocr_confidence REAL,
  data TEXT NOT NULL,            -- extracted invoice JSON (corrected after review)
  issues TEXT NOT NULL,          -- validation issues JSON
  confidence REAL NOT NULL,
  status TEXT NOT NULL,          -- auto_approved | needs_review | approved | rejected
  vendor_key TEXT, number_key TEXT,
  model TEXT, cost_usd REAL, latency_ms INTEGER,
  reviewed_by TEXT, reviewed_at TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (org_id, sha256)
);
CREATE INDEX IF NOT EXISTS docs_status ON documents (org_id, status);
CREATE INDEX IF NOT EXISTS docs_dupe ON documents (org_id, vendor_key, number_key);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def seen_numbers(self, org_id: str) -> set[tuple[str, str]]:
        rows = self.db.execute(
            "SELECT vendor_key, number_key FROM documents WHERE org_id=? AND status != 'rejected' AND number_key IS NOT NULL",
            (org_id,)).fetchall()
        return {(r[0], r[1]) for r in rows}

    def by_hash(self, org_id: str, sha: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM documents WHERE org_id=? AND sha256=?", (org_id, sha)).fetchone()

    def save(self, org_id: str, file_name: str, sha: str, result) -> int:
        inv = result.invoice
        cur = self.db.execute(
            """INSERT INTO documents (org_id, file_name, sha256, method, ocr_confidence, data, issues, confidence, status,
               vendor_key, number_key, model, cost_usd, latency_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (org_id, file_name, sha, result.method, result.ocr_confidence, json.dumps(inv.to_json_dict()),
             json.dumps([i.__dict__ for i in result.issues]), result.confidence, result.status,
             (inv.vendor_name or "").lower() or None, (inv.invoice_number or "").lower() or None,
             result.model, result.cost_usd, result.latency_ms, datetime.now(timezone.utc).isoformat()))
        self.db.commit()
        return int(cur.lastrowid)

    def queue(self, org_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, file_name, confidence, issues, data FROM documents WHERE org_id=? AND status='needs_review' ORDER BY confidence",
            (org_id,)).fetchall()
        return [{"id": r["id"], "file": r["file_name"], "confidence": r["confidence"],
                 "issues": json.loads(r["issues"]), "data": json.loads(r["data"])} for r in rows]

    def review(self, org_id: str, doc_id: int, decision: str, reviewer: str, corrected: dict | None = None) -> bool:
        if decision not in ("approved", "rejected"):
            raise ValueError("decision must be approved or rejected")
        sets, args = ["status=?", "reviewed_by=?", "reviewed_at=?"], [decision, reviewer, datetime.now(timezone.utc).isoformat()]
        if corrected is not None:
            sets.append("data=?")
            args.append(json.dumps(corrected))
        cur = self.db.execute(f"UPDATE documents SET {', '.join(sets)} WHERE org_id=? AND id=?", (*args, org_id, doc_id))
        self.db.commit()
        return cur.rowcount == 1

    def export_csv(self, org_id: str, statuses=("auto_approved", "approved")) -> str:
        q = f"SELECT file_name, data, status, confidence FROM documents WHERE org_id=? AND status IN ({','.join('?' * len(statuses))}) ORDER BY id"
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["file", "vendor", "invoice_number", "invoice_date", "due_date", "currency", "subtotal", "tax", "total", "status", "confidence"])
        for r in self.db.execute(q, (org_id, *statuses)):
            d = json.loads(r["data"])
            w.writerow([r["file_name"], d.get("vendor_name"), d.get("invoice_number"), d.get("invoice_date"), d.get("due_date"),
                        d.get("currency"), d.get("subtotal"), d.get("tax"), d.get("total"), r["status"], r["confidence"]])
        return out.getvalue()
