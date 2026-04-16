"""
Pydantic models for the three documents involved in a three-way match.

These are ERP-neutral: the Odoo client maps Odoo's native fields onto these
shapes, which means swapping to NetSuite or Dynamics later is isolated to one
file. The agent only ever sees these models.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    """A single line on a PO, GR, or invoice."""

    product_code: str = Field(..., description="SKU or internal product reference")
    description: str
    quantity: Decimal
    unit_price: Decimal = Decimal("0")
    line_total: Decimal = Decimal("0")

    model_config = {"frozen": False, "arbitrary_types_allowed": True}


class PurchaseOrder(BaseModel):
    id: int
    po_number: str
    vendor_id: int
    vendor_name: str
    order_date: str  # ISO date
    currency: str = "USD"
    lines: list[LineItem] = Field(default_factory=list)
    total: Decimal = Decimal("0")
    state: str = "purchase"  # Odoo states: draft / sent / purchase / done / cancel


class GoodsReceipt(BaseModel):
    id: int
    gr_number: str  # picking name, e.g. WH/IN/00012
    po_number: str
    receipt_date: str
    lines: list[LineItem] = Field(default_factory=list)
    state: str = "done"  # Odoo picking states


class VendorInvoice(BaseModel):
    id: int
    invoice_number: str
    vendor_id: int
    vendor_name: str
    invoice_date: str
    po_number: Optional[str] = None
    currency: str = "USD"
    lines: list[LineItem] = Field(default_factory=list)
    total: Decimal = Decimal("0")  # tax-inclusive — what the vendor wants paid
    untaxed_total: Decimal = Decimal("0")  # pre-tax — for header-vs-lines reconciliation
    state: str = "posted"
    narration: Optional[str] = None  # internal notes / memo field — visible to agent


# --- Match output ---

Severity = Literal["info", "warn", "block"]
Action = Literal["approve", "route_for_review", "block"]


class Discrepancy(BaseModel):
    code: str  # e.g. "QTY_MISMATCH", "PRICE_VARIANCE", "MISSING_GR", "DUPLICATE_INVOICE"
    severity: Severity
    product_code: Optional[str] = None
    description: str
    evidence: dict = Field(default_factory=dict)  # raw numbers that produced the flag


class MatchResult(BaseModel):
    po_number: str
    invoice_number: str
    gr_number: Optional[str]
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    recommended_action: Action
    rationale: str  # one-paragraph plain-English summary for the AP clerk
    audit_trail: list[str] = Field(default_factory=list)  # ordered log of what was checked
