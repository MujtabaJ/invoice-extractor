import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ie.evals import run_eval
from ie.extractors import RuleExtractor, raw_to_invoice
from ie.loaders import load
from ie.normalize import detect_currency, parse_date, parse_money
from ie.pipeline import Pipeline
from ie.schema import Invoice, LineItem, llm_json_schema
from ie.store import Store
from ie.validate import validate

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
TODAY = date(2026, 11, 5)
HAS_OCR = shutil.which("tesseract") and shutil.which("pdftoppm")


def pipeline() -> Pipeline:
    return Pipeline(RuleExtractor(), Store(":memory:"), today=TODAY)


# ------------------------------------------------------------------ normalize
@pytest.mark.parametrize("raw,expected", [
    ("1.234,56", "1234.56"), ("$ 1,234.56", "1234.56"), ("€ 4.796,30", "4796.30"), ("4796.30", "4796.30"),
    ("Rs. 220,400.00", "220400.00"), ("765,80", "765.80"), ("0.09", "0.09"), ("1,000", "1000.00"),
])
def test_parse_money(raw, expected):
    assert parse_money(raw) == Decimal(expected)


@pytest.mark.parametrize("raw,expected", [
    ("Oct 03, 2026", date(2026, 10, 3)), ("15.09.2026", date(2026, 9, 15)),
    ("28/1 1/2026", date(2026, 11, 28)), ("28-Oct-2026", date(2026, 10, 28)),
])
def test_parse_date_handles_formats_and_ocr_splits(raw, expected):
    assert parse_date(raw) == expected


def test_currency_detection_prefers_iso_code():
    assert detect_currency("Total £ 10. Currency: GBP") == "GBP"
    assert detect_currency("Grand Total Rs. 1,000") == "PKR"


# ------------------------------------------------------------------- schema
def test_llm_schema_is_strict_and_money_is_string():
    s = llm_json_schema()
    assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])
    assert "string" in s["properties"]["total"]["type"]


def test_raw_to_invoice_parses_strings_to_decimal():
    inv, conf = raw_to_invoice({"total": "1,575.00", "invoice_date": "2026-11-04", "line_items": [
        {"description": "QA", "quantity": "1", "unit_price": "300", "amount": "300.00"}], "field_confidence": {"total": 0.9}})
    assert inv.total == Decimal("1575.00") and inv.line_items[0].amount == Decimal("300.00") and conf["total"] == 0.9


# ----------------------------------------------------------------- validate
def _inv(**kw) -> Invoice:
    base = dict(vendor_name="V Ltd", invoice_number="1", invoice_date=date(2026, 10, 1), currency="USD",
                line_items=[LineItem(description="a", quantity=Decimal(2), unit_price=Decimal("5"), amount=Decimal("10"))],
                subtotal=Decimal("10"), tax=Decimal("1"), total=Decimal("11"))
    base.update(kw)
    return Invoice(**base)


def test_valid_invoice_has_no_issues():
    assert validate(_inv(), today=TODAY) == []


def test_validation_catches_math_dates_and_missing_fields():
    codes = {i.code for i in validate(_inv(total=Decimal("12"), due_date=date(2026, 9, 1), vendor_name=None), today=TODAY)}
    assert {"total_mismatch", "due_before_issue", "missing_field"} <= codes


def test_duplicate_detection():
    issues = validate(_inv(), today=TODAY, seen_numbers={("v ltd", "1")})
    assert any(i.code == "duplicate" for i in issues)


# ----------------------------------------------------------------- pipeline
def test_text_pdf_extracts_eu_format():
    r = pipeline().process(SAMPLES / "brightlane-RE-2026-0312.pdf")
    assert r.method == "text-layer" and r.status == "auto_approved"
    assert r.invoice.total == Decimal("4796.30") and r.invoice.currency == "EUR" and len(r.invoice.line_items) == 3


@pytest.mark.skipif(not HAS_OCR, reason="tesseract/poppler not installed")
def test_scanned_pdf_goes_through_ocr():
    doc = load(SAMPLES / "harbour-print-HP-5602-scan.pdf")
    assert doc.method == "ocr" and doc.ocr_confidence > 0.6
    r = pipeline().process(SAMPLES / "harbour-print-HP-5602-scan.pdf")
    assert r.invoice.total == Decimal("308.40") and r.invoice.invoice_number == "HP-5602"


def test_wrong_total_is_routed_to_review():
    r = pipeline().process(SAMPLES / "acme-cloud-INV-10612.pdf")
    assert r.status == "needs_review" and any(i.code == "total_mismatch" for i in r.issues)


def test_duplicate_invoice_is_routed_to_review():
    p = pipeline()
    assert p.process(SAMPLES / "acme-cloud-INV-10421.pdf").status == "auto_approved"
    second = p.process(SAMPLES / "acme-cloud-INV-10421_resent.pdf")
    assert second.status == "needs_review" and any(i.code in ("duplicate", "duplicate_file") for i in second.issues)


def test_review_queue_approve_and_export():
    p = pipeline()
    bad = p.process(SAMPLES / "acme-cloud-INV-10612.pdf")
    p.process(SAMPLES / "harbour-print-HP-5531.pdf")
    queue = p.store.queue("default")
    assert [d["id"] for d in queue] == [bad.doc_id]
    assert p.store.review("default", bad.doc_id, "approved", "tester")
    csv = p.store.export_csv("default")
    assert "HP-5531" in csv and "INV-10612" in csv and p.store.queue("default") == []


def test_tenants_are_isolated():
    p = pipeline()
    p.process(SAMPLES / "harbour-print-HP-5531.pdf", org_id="a")
    assert p.store.export_csv("b").count("\n") == 1  # header only


# -------------------------------------------------------------------- evals
@pytest.mark.skipif(not HAS_OCR, reason="tesseract/poppler not installed")
def test_eval_on_labeled_samples():
    m = run_eval(pipeline(), ROOT / "evals" / "labels.jsonl", SAMPLES).metrics
    assert m["unsafe_auto_approvals"] == 0 and m["field_accuracy"] >= 0.95 and m["routing_accuracy"] == 1.0


def test_unfamiliar_layout_is_never_auto_approved():
    m = run_eval(pipeline(), ROOT / "evals" / "labels_holdout.jsonl", ROOT / "samples_holdout").metrics
    assert m["unsafe_auto_approvals"] == 0
