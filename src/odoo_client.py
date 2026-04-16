"""
Thin Odoo XML-RPC client. Isolates every ERP-specific field name so the rest
of the system speaks in neutral models (see ``models.py``).

Odoo exposes two XML-RPC endpoints: ``/xmlrpc/2/common`` for auth and
``/xmlrpc/2/object`` for search/read. See Odoo's external API docs.
"""
from __future__ import annotations

import os
import re
import xmlrpc.client
from decimal import Decimal
from typing import Any, Optional


def _strip_html(raw: str) -> str:
    """Remove HTML tags and collapse whitespace. Odoo stores narration as HTML."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", text).strip()

from .models import GoodsReceipt, LineItem, PurchaseOrder, VendorInvoice


class OdooClient:
    def __init__(
        self,
        url: Optional[str] = None,
        db: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.url = url or os.environ["ODOO_URL"]
        self.db = db or os.environ["ODOO_DB"]
        self.username = username or os.environ["ODOO_USERNAME"]
        self.password = password or os.environ["ODOO_PASSWORD"]

        self._common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", allow_none=True)
        self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object", allow_none=True)
        self._uid: Optional[int] = None

    # ---- auth ----

    @property
    def uid(self) -> int:
        if self._uid is None:
            uid = self._common.authenticate(self.db, self.username, self.password, {})
            if not uid:
                raise RuntimeError(f"Odoo authentication failed for user {self.username!r}")
            self._uid = uid
        return self._uid

    def _call(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        return self._models.execute_kw(
            self.db, self.uid, self.password, model, method, list(args), kwargs or {}
        )

    # ---- purchase order ----

    def get_purchase_order(self, po_number: str) -> Optional[PurchaseOrder]:
        ids = self._call("purchase.order", "search", [["name", "=", po_number]], limit=1)
        if not ids:
            return None
        po = self._call(
            "purchase.order",
            "read",
            ids,
            fields=["id", "name", "partner_id", "date_order", "currency_id", "amount_total", "state", "order_line"],
        )[0]
        lines = self._call(
            "purchase.order.line",
            "read",
            po["order_line"],
            fields=["product_id", "name", "product_qty", "price_unit", "price_subtotal"],
        )
        return PurchaseOrder(
            id=po["id"],
            po_number=po["name"],
            vendor_id=po["partner_id"][0],
            vendor_name=po["partner_id"][1],
            order_date=str(po["date_order"]),
            currency=po["currency_id"][1] if po.get("currency_id") else "USD",
            total=Decimal(str(po["amount_total"])),
            state=po["state"],
            lines=[
                LineItem(
                    product_code=(ln["product_id"][1].split("]")[0].strip("[").strip() if ln.get("product_id") else "UNKNOWN"),
                    description=ln["name"],
                    quantity=Decimal(str(ln["product_qty"])),
                    unit_price=Decimal(str(ln["price_unit"])),
                    line_total=Decimal(str(ln["price_subtotal"])),
                )
                for ln in lines
            ],
        )

    # ---- goods receipt (stock.picking) ----

    def get_goods_receipt_for_po(self, po_number: str) -> Optional[GoodsReceipt]:
        # Receipts tied to a PO have ``origin = po_number`` and picking_type_code = 'incoming'
        ids = self._call(
            "stock.picking",
            "search",
            [["origin", "=", po_number], ["picking_type_code", "=", "incoming"], ["state", "=", "done"]],
            limit=1,
        )
        if not ids:
            return None
        picking = self._call(
            "stock.picking",
            "read",
            ids,
            fields=["id", "name", "origin", "date_done", "move_ids_without_package"],
        )[0]
        moves = self._call(
            "stock.move",
            "read",
            picking["move_ids_without_package"],
            fields=["product_id", "name", "quantity"],
        )
        return GoodsReceipt(
            id=picking["id"],
            gr_number=picking["name"],
            po_number=picking["origin"],
            receipt_date=str(picking["date_done"]),
            lines=[
                LineItem(
                    product_code=(mv["product_id"][1].split("]")[0].strip("[").strip() if mv.get("product_id") else "UNKNOWN"),
                    description=mv["name"],
                    quantity=Decimal(str(mv["quantity"])),
                )
                for mv in moves
            ],
        )

    # ---- vendor invoice (account.move, type='in_invoice') ----

    def get_vendor_invoice(self, invoice_number: str) -> Optional[VendorInvoice]:
        ids = self._call(
            "account.move",
            "search",
            [["name", "=", invoice_number], ["move_type", "=", "in_invoice"]],
            limit=1,
        )
        if not ids:
            return None
        inv = self._call(
            "account.move",
            "read",
            ids,
            fields=[
                "id", "name", "partner_id", "invoice_date", "invoice_origin",
                "currency_id", "amount_total", "amount_untaxed", "state",
                "invoice_line_ids", "narration",
            ],
        )[0]
        lines = self._call(
            "account.move.line",
            "read",
            inv["invoice_line_ids"],
            fields=["product_id", "name", "quantity", "price_unit", "price_subtotal"],
        )
        raw_narration = inv.get("narration") or ""
        narration = _strip_html(raw_narration) or None
        return VendorInvoice(
            id=inv["id"],
            invoice_number=inv["name"],
            vendor_id=inv["partner_id"][0],
            vendor_name=inv["partner_id"][1],
            invoice_date=str(inv["invoice_date"]),
            po_number=inv.get("invoice_origin"),
            currency=inv["currency_id"][1] if inv.get("currency_id") else "USD",
            total=Decimal(str(inv["amount_total"])),
            untaxed_total=Decimal(str(inv.get("amount_untaxed", inv["amount_total"]))),
            state=inv["state"],
            narration=narration,
            lines=[
                LineItem(
                    product_code=(ln["product_id"][1].split("]")[0].strip("[").strip() if ln.get("product_id") else "UNKNOWN"),
                    description=ln["name"],
                    quantity=Decimal(str(ln["quantity"])),
                    unit_price=Decimal(str(ln["price_unit"])),
                    line_total=Decimal(str(ln["price_subtotal"])),
                )
                for ln in lines
            ],
        )

    def find_duplicate_invoices(
        self, vendor_id: int, invoice_number: str, amount: Decimal
    ) -> list[dict]:
        """Return other vendor invoices with the same vendor and total, excluding the given number."""
        ids = self._call(
            "account.move",
            "search",
            [
                ["partner_id", "=", vendor_id],
                ["move_type", "=", "in_invoice"],
                ["amount_total", "=", float(amount)],
                ["name", "!=", invoice_number],
                ["state", "!=", "cancel"],
            ],
        )
        if not ids:
            return []
        return self._call(
            "account.move", "read", ids,
            fields=["id", "name", "invoice_date", "amount_total", "state"],
        )
