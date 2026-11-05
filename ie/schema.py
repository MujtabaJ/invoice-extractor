"""The target schema. Money is Decimal end to end: never float."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Optional[Decimal] = None
    amount: Decimal


class Invoice(BaseModel):
    vendor_name: Optional[str] = None
    vendor_tax_id: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    currency: Optional[str] = Field(default=None, description="ISO 4217 code, e.g. USD, EUR, GBP, PKR")
    po_number: Optional[str] = None
    bill_to: Optional[str] = None
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    total: Optional[Decimal] = None

    def to_json_dict(self) -> dict:
        return self.model_dump(mode="json")


HEADER_FIELDS = ["vendor_name", "invoice_number", "invoice_date", "due_date", "currency", "po_number",
                 "subtotal", "tax", "total"]
REQUIRED_FIELDS = ["vendor_name", "invoice_number", "invoice_date", "currency", "total"]


def llm_json_schema() -> dict:
    """A strict JSON schema for LLM structured output.

    Money is a string such as "1234.56" so the model never emits binary floats.
    We parse it to Decimal ourselves.
    """
    s = {"type": ["string", "null"]}
    money = {"type": ["string", "null"], "description": "Plain decimal, dot separator, no symbols, e.g. 1234.56"}
    day = {"type": ["string", "null"], "description": "ISO date YYYY-MM-DD"}
    item = {
        "type": "object",
        "additionalProperties": False,
        "required": ["description", "quantity", "unit_price", "amount"],
        "properties": {"description": {"type": "string"}, "quantity": money, "unit_price": money, "amount": money},
    }
    props = {
        "vendor_name": s, "vendor_tax_id": s, "invoice_number": s, "invoice_date": day, "due_date": day,
        "currency": {"type": ["string", "null"], "description": "ISO 4217 code"}, "po_number": s, "bill_to": s,
        "line_items": {"type": "array", "items": item}, "subtotal": money, "tax": money, "total": money,
        "field_confidence": {
            "type": "object", "additionalProperties": False,
            "required": HEADER_FIELDS,
            "properties": {f: {"type": "number", "description": "0-1 confidence"} for f in HEADER_FIELDS},
        },
    }
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}
