"""Parse messy money, dates and currencies into clean values."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

CURRENCY_HINTS = [
    (re.compile(r"\bUSD\b|US\$|\$"), "USD"),
    (re.compile(r"\bEUR\b|€"), "EUR"),
    (re.compile(r"\bGBP\b|£"), "GBP"),
    (re.compile(r"\bPKR\b|\bRs\.?(?=\s?\d)"), "PKR"),
    (re.compile(r"\bINR\b|₹"), "INR"),
    (re.compile(r"\bAED\b"), "AED"),
]

# Grouped thousands first ("1.234,56", "85,000.00"), then plain numbers ("4796.30").
# The (?!\d) guards stop a partial match like "479" out of "4796.30".
_MONEY = re.compile(r"-?\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d{1,2})?(?!\d)|-?\d+(?:[.,]\d{1,2})?(?!\d)")


def parse_money(text: str | None) -> Decimal | None:
    """'1.234,56' -> 1234.56, '$ 1,234.56' -> 1234.56, '85,000.00' -> 85000.00."""
    if text is None:
        return None
    s = str(text).strip()
    m = _MONEY.search(s.replace(" ", " "))
    if not m:
        return None
    n = m.group(0).replace(" ", "")
    if "," in n and "." in n:
        # whichever separator comes last is the decimal separator
        n = n.replace(".", "").replace(",", ".") if n.rfind(",") > n.rfind(".") else n.replace(",", "")
    elif "," in n:
        head, _, tail = n.rpartition(",")
        n = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else n.replace(",", "")
    elif n.count(".") > 1:
        head, _, tail = n.rpartition(".")
        n = f"{head.replace('.', '')}.{tail}" if len(tail) in (1, 2) else n.replace(".", "")
    elif "." in n and len(n.rpartition(".")[2]) == 3:
        n = n.replace(".", "")  # 1.890 (EU thousands, no decimals)
    try:
        return Decimal(n).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


_DATE_FORMATS = ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y", "%d %b %Y", "%b %d, %Y",
                 "%B %d, %Y", "%d %B %Y", "%d-%m-%Y", "%Y/%m/%d"]


def parse_date(text: str | None, prefer_day_first: bool = True) -> date | None:
    if not text:
        return None
    s = re.sub(r"(?<=\d)\s+(?=\d)", "", str(text).strip())  # OCR splits like "28/1 1/2026"
    s = s.strip(" .,:;'\"‘’")
    fmts = _DATE_FORMATS if prefer_day_first else ["%m/%d/%Y"] + [f for f in _DATE_FORMATS if f != "%m/%d/%Y"]
    for f in fmts:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def detect_currency(text: str) -> str | None:
    """Prefer an explicit ISO code mention; fall back to symbols."""
    m = re.search(r"Currency:\s*([A-Z]{3})", text)
    if m:
        return m.group(1)
    for rx, code in CURRENCY_HINTS:
        if rx.search(text):
            return code
    return None
