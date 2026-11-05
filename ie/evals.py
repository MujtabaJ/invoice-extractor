"""Measure extraction accuracy and review routing against labeled documents.

labels.jsonl rows: {"file": ..., "expect_review": bool, "expected": {field: value, "line_items": [...]}}

Metrics
- field_accuracy: header fields exactly right (after normalization)
- line_item_accuracy: line items whose description, quantity, unit price and amount all match
- doc_exact: documents where every header field and line item is right
- routing_accuracy: auto-approve vs needs-review matches what a careful human would do
- unsafe_auto_approvals: documents that should have been reviewed but were auto-approved (must be 0)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .pipeline import Pipeline
from .schema import HEADER_FIELDS


def _norm(v):
    if v is None:
        return None
    try:
        return str(Decimal(str(v)).quantize(Decimal("0.01")))
    except Exception:
        return " ".join(str(v).split()).lower()


@dataclass
class EvalReport:
    metrics: dict
    rows: list[dict]

    def summary(self) -> str:
        m = self.metrics
        out = [f"Documents: {m['documents']}"]
        for k in ("field_accuracy", "line_item_accuracy", "doc_exact", "routing_accuracy"):
            out.append(f"  {k:<22} {m[k]:.0%}")
        out.append(f"  unsafe_auto_approvals  {m['unsafe_auto_approvals']}")
        out.append(f"  auto_approved          {m['auto_approved']} / {m['documents']}")
        for r in self.rows:
            flag = "OK " if r["ok"] else "ERR"
            out.append(f"  {flag} {r['file']:<34} {r['status']:<13} conf={r['confidence']:<5} wrong={r['wrong_fields']}")
        return "\n".join(out)


def run_eval(pipeline: Pipeline, labels_path: str | Path, docs_dir: str | Path, org_id: str = "eval") -> EvalReport:
    labels = [json.loads(l) for l in Path(labels_path).read_text().splitlines() if l.strip()]
    f_ok = f_n = li_ok = li_n = exact = route_ok = unsafe = auto = 0
    rows = []
    for lab in labels:
        res = pipeline.process(Path(docs_dir) / lab["file"], org_id=org_id)
        got = res.invoice.to_json_dict()
        exp = lab["expected"]
        wrong = [f for f in HEADER_FIELDS if f in exp and _norm(got.get(f)) != _norm(exp[f])]
        f_n += sum(1 for f in HEADER_FIELDS if f in exp)
        f_ok += sum(1 for f in HEADER_FIELDS if f in exp) - len(wrong)

        exp_items = exp.get("line_items", [])
        got_items = got.get("line_items", [])
        for i, e in enumerate(exp_items):
            li_n += 1
            g = got_items[i] if i < len(got_items) else {}
            if all(_norm(g.get(k)) == _norm(e[k]) for k in ("description", "quantity", "unit_price", "amount")):
                li_ok += 1
            else:
                wrong.append(f"line_items[{i}]")
        if len(got_items) > len(exp_items):
            wrong.append("extra_line_items")
        exact += not wrong

        reviewed = res.status == "needs_review"
        auto += not reviewed
        route_ok += reviewed == lab["expect_review"]
        unsafe += lab["expect_review"] and not reviewed
        rows.append({"file": lab["file"], "status": res.status, "confidence": res.confidence,
                     "wrong_fields": wrong, "issues": [i.code for i in res.issues],
                     "ok": not wrong and reviewed == lab["expect_review"]})

    n = len(labels)
    metrics = {"documents": n, "field_accuracy": f_ok / max(1, f_n), "line_item_accuracy": li_ok / max(1, li_n),
               "doc_exact": exact / max(1, n), "routing_accuracy": route_ok / max(1, n),
               "unsafe_auto_approvals": unsafe, "auto_approved": auto}
    return EvalReport(metrics, rows)
