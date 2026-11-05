"""Generate fictional sample invoices (PDFs) plus ground-truth labels.

Every vendor, person and number here is invented. Layouts deliberately differ
(US, EU with comma decimals and VAT, UK, Pakistan), one invoice is a noisy
"scan" (image only, so it needs OCR), one has an arithmetic error and one is
a duplicate. That lets the eval check extraction AND review routing.

    python scripts/make_samples.py
"""

from __future__ import annotations

import io
import json
import random
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples"
LABELS = ROOT / "evals" / "labels.jsonl"
D = Decimal


def money(v: Decimal, style: str) -> str:
    q = f"{v:,.2f}"
    if style == "eu":  # 1.234,56
        return q.replace(",", "X").replace(".", ",").replace("X", ".")
    return q


INVOICES = [
    # ---- US layout -------------------------------------------------------
    dict(file="acme-cloud-INV-10421.pdf", layout="us", vendor="Acme Cloud Services LLC", tax_id="EIN 84-1234567",
         number="INV-10421", date="2026-10-03", date_fmt="%b %d, %Y", due="2026-11-02", currency="USD", sym="$",
         po="PO-7781", bill_to="Northwind Desk Inc.",
         items=[("Cloud hosting - Pro plan (Oct)", 1, D("249.00")), ("Additional storage 500 GB", 2, D("35.00")),
                ("Priority support", 1, D("99.00"))], tax_rate=D("0.08")),
    dict(file="acme-cloud-INV-10587.pdf", layout="us", vendor="Acme Cloud Services LLC", tax_id="EIN 84-1234567",
         number="INV-10587", date="2026-11-01", date_fmt="%b %d, %Y", due="2026-12-01", currency="USD", sym="$",
         po=None, bill_to="Northwind Desk Inc.",
         items=[("Cloud hosting - Pro plan (Nov)", 1, D("249.00")), ("Bandwidth overage 120 GB", 120, D("0.09"))],
         tax_rate=D("0.08")),
    # ---- EU layout: comma decimals, VAT, DD.MM.YYYY -------------------------
    dict(file="brightlane-RE-2026-0312.pdf", layout="eu", vendor="Brightlane Software GmbH", tax_id="USt-IdNr. DE298765432",
         number="RE-2026-0312", date="2026-09-15", date_fmt="%d.%m.%Y", due="2026-09-29", currency="EUR", sym="€",
         po="NW-2291", bill_to="Northwind Desk Inc.",
         items=[("Lizenz Analytics Suite (12 Monate)", 1, D("1890.00")), ("Onboarding-Workshop", 2, D("450.00")),
                ("Datenmigration", 1, D("1240.50"))], tax_rate=D("0.19")),
    dict(file="brightlane-RE-2026-0398.pdf", layout="eu", vendor="Brightlane Software GmbH", tax_id="USt-IdNr. DE298765432",
         number="RE-2026-0398", date="2026-10-20", date_fmt="%d.%m.%Y", due="2026-11-03", currency="EUR", sym="€",
         po=None, bill_to="Northwind Desk Inc.",
         items=[("Zusatzmodul Reporting", 1, D("320.00")), ("Support-Stunden", 6, D("85.00"))], tax_rate=D("0.19")),
    # ---- UK layout ---------------------------------------------------------
    dict(file="harbour-print-HP-5531.pdf", layout="uk", vendor="Harbour Print & Design Ltd", tax_id="VAT Reg No GB 123 4567 89",
         number="HP-5531", date="2026-10-07", date_fmt="%d/%m/%Y", due="2026-11-06", currency="GBP", sym="£",
         po="PO-1180", bill_to="Northwind Desk Ltd (UK)",
         items=[("Business cards, 500 qty", 4, D("38.50")), ("Trade show banner 2m", 1, D("185.00")),
                ("Design hours", 3, D("55.00"))], tax_rate=D("0.20")),
    # ---- Pakistan layout ---------------------------------------------------
    dict(file="indus-it-INV-2026-118.pdf", layout="pk", vendor="Indus IT Solutions (Pvt) Ltd", tax_id="NTN 1234567-8",
         number="INV-2026-118", date="2026-10-28", date_fmt="%d-%b-%Y", due="2026-11-12", currency="PKR", sym="Rs.",
         po=None, bill_to="Northwind Desk Inc.",
         items=[("Network setup - Karachi office", 1, D("85000.00")), ("Cat6 cabling (per point)", 24, D("2500.00")),
                ("Firewall configuration", 1, D("45000.00"))], tax_rate=D("0.16")),
    # ---- "Scanned" copy (image-only PDF, needs OCR) --------------------------
    dict(file="harbour-print-HP-5602-scan.pdf", layout="uk", scan=True, vendor="Harbour Print & Design Ltd",
         tax_id="VAT Reg No GB 123 4567 89", number="HP-5602", date="2026-10-29", date_fmt="%d/%m/%Y", due="2026-11-28",
         currency="GBP", sym="£", po=None, bill_to="Northwind Desk Ltd (UK)",
         items=[("Flyers A5, 1000 qty", 2, D("64.00")), ("Roller banner", 1, D("129.00"))], tax_rate=D("0.20")),
    # ---- Arithmetic error: printed total is wrong -> must go to review -------
    dict(file="acme-cloud-INV-10612.pdf", layout="us", vendor="Acme Cloud Services LLC", tax_id="EIN 84-1234567",
         number="INV-10612", date="2026-11-03", date_fmt="%b %d, %Y", due="2026-12-03", currency="USD", sym="$",
         po=None, bill_to="Northwind Desk Inc.",
         items=[("Dedicated GPU node (Nov)", 1, D("1100.00")), ("Setup fee", 1, D("150.00"))], tax_rate=D("0.08"),
         wrong_total=D("1450.00"), expect_review=True),
    # ---- Duplicate of an earlier invoice -> must go to review ----------------
    dict(file="acme-cloud-INV-10421_resent.pdf", layout="us", vendor="Acme Cloud Services LLC", tax_id="EIN 84-1234567",
         number="INV-10421", date="2026-10-03", date_fmt="%b %d, %Y", due="2026-11-02", currency="USD", sym="$",
         po="PO-7781", bill_to="Northwind Desk Inc.",
         items=[("Cloud hosting - Pro plan (Oct)", 1, D("249.00")), ("Additional storage 500 GB", 2, D("35.00")),
                ("Priority support", 1, D("99.00"))], tax_rate=D("0.08"), expect_review=True, duplicate=True),
]

LABELS_TEXT = {
    "us": dict(title="INVOICE", num="Invoice #", date="Invoice Date", due="Due Date", po="PO Number", bill="Bill To",
               cols=("Description", "Qty", "Unit Price", "Amount"), sub="Subtotal", tax="Sales Tax ({r}%)", total="Total Due"),
    "eu": dict(title="RECHNUNG / INVOICE", num="Rechnungsnummer", date="Rechnungsdatum", due="Fällig am", po="Bestellnummer",
               bill="Rechnung an", cols=("Beschreibung", "Menge", "Einzelpreis", "Betrag"), sub="Zwischensumme",
               tax="MwSt. {r}%", total="Gesamtbetrag"),
    "uk": dict(title="TAX INVOICE", num="Invoice No.", date="Date", due="Payment due", po="Your ref", bill="Invoice to",
               cols=("Item", "Qty", "Price", "Line total"), sub="Net total", tax="VAT @ {r}%", total="Total payable"),
    "pk": dict(title="SALES TAX INVOICE", num="Invoice No", date="Invoice Date", due="Due Date", po="PO #", bill="Customer",
               cols=("Description", "Qty", "Rate", "Amount"), sub="Amount (excl. tax)", tax="Sales Tax {r}%", total="Grand Total"),
}


def compute(inv: dict) -> dict:
    lines = [dict(description=d, quantity=q, unit_price=p, amount=(p * q).quantize(D("0.01"))) for d, q, p in inv["items"]]
    sub = sum((l["amount"] for l in lines), D("0"))
    tax = (sub * inv["tax_rate"]).quantize(D("0.01"))
    return dict(lines=lines, subtotal=sub, tax=tax, total=sub + tax)


def draw(inv: dict, c: canvas.Canvas) -> None:
    from datetime import date

    L = LABELS_TEXT[inv["layout"]]
    style = "eu" if inv["layout"] == "eu" else "us"
    calc = compute(inv)
    fmt = lambda s: date.fromisoformat(s).strftime(inv["date_fmt"])  # noqa: E731
    w, h = A4
    y = h - 25 * mm
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, inv["vendor"])
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(w - 20 * mm, y, L["title"])
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, y - 6 * mm, inv["tax_id"])
    c.drawString(20 * mm, y - 11 * mm, "12 Example Street, Demo City (fictional)")

    y -= 26 * mm
    c.setFont("Helvetica", 10)
    meta = [(L["num"], inv["number"]), (L["date"], fmt(inv["date"])), (L["due"], fmt(inv["due"]))]
    if inv.get("po"):
        meta.append((L["po"], inv["po"]))
    for k, v in meta:
        c.drawString(115 * mm, y, f"{k}:")
        c.drawString(150 * mm, y, v)
        y -= 5.5 * mm
    c.drawString(20 * mm, y + 5.5 * mm * len(meta), f"{L['bill']}:")
    c.drawString(20 * mm, y + 5.5 * mm * (len(meta) - 1), inv["bill_to"])

    y -= 10 * mm
    c.setFont("Helvetica-Bold", 10)
    xs = (20 * mm, 120 * mm, 145 * mm, w - 20 * mm)
    c.drawString(xs[0], y, L["cols"][0])
    c.drawRightString(xs[1] + 10 * mm, y, L["cols"][1])
    c.drawRightString(xs[2] + 15 * mm, y, L["cols"][2])
    c.drawRightString(xs[3], y, L["cols"][3])
    c.line(20 * mm, y - 2 * mm, w - 20 * mm, y - 2 * mm)
    c.setFont("Helvetica", 10)
    for l in calc["lines"]:
        y -= 7 * mm
        c.drawString(xs[0], y, l["description"])
        c.drawRightString(xs[1] + 10 * mm, y, str(l["quantity"]))
        c.drawRightString(xs[2] + 15 * mm, y, money(l["unit_price"], style))
        c.drawRightString(xs[3], y, money(l["amount"], style))
    c.line(20 * mm, y - 3 * mm, w - 20 * mm, y - 3 * mm)

    total = inv.get("wrong_total", calc["total"])
    pct = inv["tax_rate"] * 100
    rate = str(int(pct)) if pct == pct.to_integral_value() else f"{pct:f}".rstrip("0")
    rows = [(L["sub"], calc["subtotal"]), (L["tax"].format(r=rate), calc["tax"]), (L["total"], total)]
    for i, (k, v) in enumerate(rows):
        y -= 7 * mm
        c.setFont("Helvetica-Bold" if i == 2 else "Helvetica", 10)
        c.drawString(120 * mm, y, k)
        c.drawRightString(xs[3], y, f"{inv['sym']} {money(v, style)}" if i == 2 else money(v, style))
    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, 20 * mm, f"Currency: {inv['currency']}. This is a fictional invoice generated for a software demo.")


def to_scan(pdf_bytes: bytes, path: Path) -> None:
    """Rasterize, rotate slightly, add blur and noise: a realistic phone/scanner copy with no text layer."""
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        src.write_bytes(pdf_bytes)
        subprocess.run(["pdftoppm", "-r", "200", "-png", str(src), str(Path(tmp) / "p")], check=True)
        img = Image.open(next(Path(tmp).glob("p*.png"))).convert("L")
    rnd = random.Random(7)
    img = img.rotate(0.8, expand=True, fillcolor=255).filter(ImageFilter.GaussianBlur(0.6))
    px = img.load()
    for _ in range(img.size[0] * img.size[1] // 400):
        x, y = rnd.randrange(img.size[0]), rnd.randrange(img.size[1])
        px[x, y] = rnd.choice((0, 90, 200))
    img.convert("RGB").save(path, "PDF", resolution=200)


def make_holdout() -> None:
    """An unfamiliar layout: different labels, amount column first, no 'Total' keyword spelled the usual way.

    The offline rule extractor was not tuned on this. The test checks that whatever it
    gets wrong is routed to human review instead of being auto-approved.
    """
    out = ROOT / "samples_holdout"
    out.mkdir(exist_ok=True)
    c = canvas.Canvas(str(out / "kestrel-labs-statement-77.pdf"), pagesize=A4)
    w, h = A4
    y = h - 25 * mm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, y, "KESTREL DATA LABS")
    c.setFont("Helvetica", 10)
    rows = ["Billing statement", "", "Reference      KDL/77/2026", "Issued on      4 November 2026",
            "Settle within  21 days", "Client         Northwind Desk Inc.", "",
            "USD 1,200.00   Data labelling sprint (2 weeks)", "USD   300.00   QA review",
            "", "Charges        1,500.00", "Levy (5%)      75.00", "Amount payable USD 1,575.00"]
    for r in rows:
        y -= 7 * mm
        c.drawString(20 * mm, y, r)
    c.save()
    (ROOT / "evals" / "labels_holdout.jsonl").write_text(json.dumps({
        "file": "kestrel-labs-statement-77.pdf", "expect_review": True,
        "expected": {"vendor_name": "Kestrel Data Labs", "invoice_number": "KDL/77/2026", "invoice_date": "2026-11-04",
                     "due_date": "2026-11-25", "currency": "USD", "po_number": None, "subtotal": "1500.00",
                     "tax": "75.00", "total": "1575.00",
                     "line_items": [{"description": "Data labelling sprint (2 weeks)", "quantity": "1", "unit_price": "1200.00", "amount": "1200.00"},
                                    {"description": "QA review", "quantity": "1", "unit_price": "300.00", "amount": "300.00"}]},
    }) + "\n")


def main() -> None:
    make_holdout()
    OUT.mkdir(exist_ok=True)
    LABELS.parent.mkdir(exist_ok=True)
    labels = []
    for inv in INVOICES:
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        draw(inv, c)
        c.save()
        path = OUT / inv["file"]
        if inv.get("scan"):
            to_scan(buf.getvalue(), path)
        else:
            path.write_bytes(buf.getvalue())
        calc = compute(inv)
        labels.append({
            "file": inv["file"],
            "expect_review": bool(inv.get("expect_review")),
            "expected": {
                "vendor_name": inv["vendor"], "invoice_number": inv["number"], "invoice_date": inv["date"],
                "due_date": inv["due"], "currency": inv["currency"], "po_number": inv.get("po"),
                "subtotal": str(calc["subtotal"]), "tax": str(calc["tax"]),
                "total": str(inv.get("wrong_total", calc["total"])),
                "line_items": [{"description": l["description"], "quantity": str(l["quantity"]),
                                "unit_price": str(l["unit_price"]), "amount": str(l["amount"])} for l in calc["lines"]],
            },
        })
    LABELS.write_text("\n".join(json.dumps(l) for l in labels) + "\n")
    print(f"Wrote {len(INVOICES)} invoices to {OUT} and labels to {LABELS}")


if __name__ == "__main__":
    main()
