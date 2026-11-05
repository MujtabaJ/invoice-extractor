"""Business-rule validation. Errors send a document to human review; warnings lower confidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .schema import REQUIRED_FIELDS, Invoice

TOL = Decimal("0.02")  # rounding tolerance per comparison


@dataclass
class Issue:
    code: str
    field: str
    severity: str  # "error" | "warning"
    message: str


def validate(inv: Invoice, *, today: date | None = None, seen_numbers: set[tuple[str, str]] | None = None) -> list[Issue]:
    issues: list[Issue] = []
    today = today or date.today()

    for f in REQUIRED_FIELDS:
        if getattr(inv, f) in (None, ""):
            issues.append(Issue("missing_field", f, "error", f"{f} not found"))

    if inv.line_items:
        for i, li in enumerate(inv.line_items):
            if li.unit_price is not None and abs(li.quantity * li.unit_price - li.amount) > TOL:
                issues.append(Issue("line_math", f"line_items[{i}]", "error",
                                    f"{li.quantity} x {li.unit_price} != {li.amount}"))
        lines_sum = sum((li.amount for li in inv.line_items), Decimal("0"))
        if inv.subtotal is not None and abs(lines_sum - inv.subtotal) > TOL:
            issues.append(Issue("subtotal_mismatch", "subtotal", "error", f"line items sum to {lines_sum}, subtotal is {inv.subtotal}"))
    else:
        issues.append(Issue("no_line_items", "line_items", "warning", "no line items found"))

    if inv.total is not None:
        base = inv.subtotal if inv.subtotal is not None else (sum((li.amount for li in inv.line_items), Decimal("0")) or None)
        if base is not None:
            expected = base + (inv.tax or Decimal("0"))
            if abs(expected - inv.total) > TOL:
                issues.append(Issue("total_mismatch", "total", "error", f"subtotal + tax = {expected}, total is {inv.total}"))
        if inv.total <= 0:
            issues.append(Issue("non_positive_total", "total", "warning", "total is zero or negative (credit note?)"))

    if inv.subtotal and inv.tax is not None and inv.subtotal > 0:
        rate = inv.tax / inv.subtotal
        if rate > Decimal("0.30"):
            issues.append(Issue("tax_rate_unusual", "tax", "warning", f"tax rate {rate:.1%} looks unusually high"))

    if inv.invoice_date:
        if inv.invoice_date > today:
            issues.append(Issue("future_date", "invoice_date", "warning", "invoice date is in the future"))
        if inv.due_date and inv.due_date < inv.invoice_date:
            issues.append(Issue("due_before_issue", "due_date", "error", "due date is before invoice date"))

    if seen_numbers is not None and inv.vendor_name and inv.invoice_number:
        if (inv.vendor_name.lower(), inv.invoice_number.lower()) in seen_numbers:
            issues.append(Issue("duplicate", "invoice_number", "error", "this vendor already sent this invoice number"))

    if inv.currency and len(inv.currency) != 3:
        issues.append(Issue("bad_currency", "currency", "warning", f"unexpected currency code {inv.currency}"))
    return issues


def score(field_conf: dict[str, float], issues: list[Issue], ocr_conf: float | None) -> float:
    """Overall 0-1 confidence: weakest required field, scaled by OCR quality, minus a penalty per issue."""
    base = min((field_conf.get(f, 0.0) for f in REQUIRED_FIELDS), default=0.0)
    if ocr_conf is not None:
        base *= min(1.0, 0.5 + ocr_conf / 2)  # 0.9 OCR -> x0.95; 0.6 OCR -> x0.8
    base -= 0.25 * sum(i.severity == "error" for i in issues) + 0.05 * sum(i.severity == "warning" for i in issues)
    return round(max(0.0, min(1.0, base)), 3)
