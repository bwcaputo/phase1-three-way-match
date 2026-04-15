"""
Tool definitions exposed to Claude via the Messages API tool-use protocol.

Design note: the LLM's job is orchestration and narration. Every tool here
returns either structured data from Odoo or the result of a deterministic
Python function. The LLM does not compute dollar amounts, compare quantities,
or decide the final action — it calls ``run_three_way_match``, which does.

This is the hallucination control in one sentence: the model cannot make up
numbers it never sees, and cannot override a decision made by the code.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Optional

from .match import three_way_match
from .models import MatchResult
from .odoo_client import OdooClient


# --- JSON helpers ---

def _jsonable(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, list):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    return obj


def _dumps(obj: Any) -> str:
    return json.dumps(_jsonable(obj), default=str, indent=2)


# --- Tool schemas for the Anthropic Messages API ---

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "fetch_purchase_order",
        "description": (
            "Fetch a purchase order from Odoo by its PO number (e.g. 'P00012'). "
            "Returns vendor, order date, line items with ordered quantity and unit price, and total."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "po_number": {"type": "string", "description": "Odoo PO name, e.g. 'P00012'"},
            },
            "required": ["po_number"],
        },
    },
    {
        "name": "fetch_goods_receipt",
        "description": (
            "Fetch the goods receipt (stock picking) tied to a given PO number. "
            "Returns the receipt date and received quantities by SKU. "
            "Returns null if no completed receipt exists (a blocking condition)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "po_number": {"type": "string"},
            },
            "required": ["po_number"],
        },
    },
    {
        "name": "fetch_vendor_invoice",
        "description": (
            "Fetch a vendor invoice from Odoo by invoice number. Returns vendor, invoice date, "
            "referenced PO, line items with billed quantity and unit price, and total."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_number": {"type": "string"},
            },
            "required": ["invoice_number"],
        },
    },
    {
        "name": "check_for_duplicate_invoices",
        "description": (
            "Check if the vendor has any other invoices with the same total amount. "
            "Used to catch duplicate submissions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "vendor_id": {"type": "integer"},
                "invoice_number": {"type": "string"},
                "amount": {"type": "string", "description": "Decimal string, e.g. '1250.00'"},
            },
            "required": ["vendor_id", "invoice_number", "amount"],
        },
    },
    {
        "name": "run_three_way_match",
        "description": (
            "Run the deterministic three-way match over a PO, goods receipt, and invoice that "
            "were previously fetched in this conversation. This is the authoritative decision: "
            "it returns the list of discrepancies, the recommended action (approve / "
            "route_for_review / block), and a complete audit trail. "
            "You MUST use this tool — do not decide the action yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "po_number": {"type": "string"},
                "invoice_number": {"type": "string"},
            },
            "required": ["po_number", "invoice_number"],
        },
    },
]


# --- Dispatcher ---

class ToolDispatcher:
    """Stateful tool handler — caches fetched docs so run_three_way_match has them."""

    def __init__(self, client: OdooClient) -> None:
        self.client = client
        self._po_cache: dict[str, Any] = {}
        self._gr_cache: dict[str, Any] = {}
        self._inv_cache: dict[str, Any] = {}
        self._dup_cache: dict[str, list[dict]] = {}
        self.last_result: Optional[MatchResult] = None

    def dispatch(self, name: str, args: dict) -> str:
        if name == "fetch_purchase_order":
            po = self.client.get_purchase_order(args["po_number"])
            if po is None:
                return _dumps({"error": f"PO {args['po_number']} not found"})
            self._po_cache[po.po_number] = po
            return _dumps(po)

        if name == "fetch_goods_receipt":
            gr = self.client.get_goods_receipt_for_po(args["po_number"])
            self._gr_cache[args["po_number"]] = gr  # may be None
            if gr is None:
                return _dumps({"result": None, "note": "No completed goods receipt for this PO."})
            return _dumps(gr)

        if name == "fetch_vendor_invoice":
            inv = self.client.get_vendor_invoice(args["invoice_number"])
            if inv is None:
                return _dumps({"error": f"Invoice {args['invoice_number']} not found"})
            self._inv_cache[inv.invoice_number] = inv
            return _dumps(inv)

        if name == "check_for_duplicate_invoices":
            dups = self.client.find_duplicate_invoices(
                vendor_id=args["vendor_id"],
                invoice_number=args["invoice_number"],
                amount=Decimal(args["amount"]),
            )
            self._dup_cache[args["invoice_number"]] = dups
            return _dumps({"duplicates_found": len(dups), "invoices": dups})

        if name == "run_three_way_match":
            po = self._po_cache.get(args["po_number"])
            inv = self._inv_cache.get(args["invoice_number"])
            if po is None or inv is None:
                return _dumps({
                    "error": "You must fetch the PO and invoice first via "
                             "fetch_purchase_order and fetch_vendor_invoice."
                })
            gr = self._gr_cache.get(args["po_number"])
            dups = self._dup_cache.get(args["invoice_number"])
            result = three_way_match(po=po, gr=gr, invoice=inv, duplicate_candidates=dups)
            self.last_result = result
            return _dumps(result)

        return _dumps({"error": f"Unknown tool: {name}"})
