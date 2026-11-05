"""Command-line demo.

  python -m ie.cli process samples/            # extract every document, print a summary
  python -m ie.cli queue                       # documents waiting for human review
  python -m ie.cli approve 3                   # approve document 3 after checking it
  python -m ie.cli export > invoices.csv       # approved data as CSV
  python -m ie.cli eval                        # accuracy report against evals/labels.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from .evals import run_eval
from .extractors import make_extractor
from .pipeline import Pipeline
from .store import Store

DB = os.environ.get("IE_DB", "invoices.db")
ORG = "default"
SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".txt"}


def _pipeline(db: str = DB, today: date | None = None) -> Pipeline:
    return Pipeline(make_extractor(os.environ.get("IE_PROVIDER", "offline")), Store(db),
                    auto_approve_at=float(os.environ.get("IE_AUTO_APPROVE_AT", "0.85")), today=today)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ie")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("process")
    pr.add_argument("path")
    pr.add_argument("--json", action="store_true")
    sub.add_parser("queue")
    for name in ("approve", "reject"):
        sub.add_parser(name).add_argument("doc_id", type=int)
    sub.add_parser("export")
    ev = sub.add_parser("eval")
    ev.add_argument("--labels", default="evals/labels.jsonl")
    ev.add_argument("--docs", default="samples")
    ev.add_argument("--min-accuracy", type=float, default=0.9, help="fail below this field accuracy (0 = safety check only)")
    args = p.parse_args(argv)

    if args.cmd == "eval":
        # fresh in-memory store and a fixed "today" so results are reproducible
        report = run_eval(_pipeline(":memory:", today=date(2026, 11, 5)), args.labels, args.docs)
        print(report.summary())
        ok = report.metrics["unsafe_auto_approvals"] == 0 and report.metrics["field_accuracy"] >= args.min_accuracy
        return 0 if ok else 1

    store_pipeline = _pipeline()
    if args.cmd == "process":
        path = Path(args.path)
        files = sorted(f for f in path.iterdir() if f.suffix.lower() in SUPPORTED) if path.is_dir() else [path]
        for f in files:
            r = store_pipeline.process(f, ORG)
            if args.json:
                print(json.dumps(r.to_dict()))
            else:
                i = r.invoice
                print(f"[{r.doc_id or '-'}] {f.name:<34} {r.status:<13} conf={r.confidence:<5} {r.method:<10} "
                      f"{i.vendor_name} | {i.invoice_number} | {i.invoice_date} | {i.currency} {i.total}"
                      + (f"  !! {', '.join(x.code for x in r.issues)}" if r.issues else ""))
        return 0
    store = store_pipeline.store
    if args.cmd == "queue":
        for d in store.queue(ORG):
            print(f"[{d['id']}] {d['file']} conf={d['confidence']}")
            for i in d["issues"]:
                print(f"      {i['severity']}: {i['message']}")
        return 0
    if args.cmd in ("approve", "reject"):
        ok = store.review(ORG, args.doc_id, "approved" if args.cmd == "approve" else "rejected", reviewer=os.environ.get("USER", "cli"))
        print("updated" if ok else "not found")
        return 0 if ok else 1
    if args.cmd == "export":
        sys.stdout.write(store.export_csv(ORG))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
