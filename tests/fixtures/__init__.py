"""Synthetic PO/GR/Invoice triples for match-logic tests."""
from decimal import Decimal

from src.models import GoodsReceipt, LineItem, PurchaseOrder, VendorInvoice


def clean_po() -> PurchaseOrder:
    return PurchaseOrder(
        id=1, po_number="P00001", vendor_id=10, vendor_name="Acme Industrial",
        order_date="2026-03-01", currency="USD",
        total=Decimal("1500.00"), state="purchase",
        lines=[
            LineItem(product_code="WIDGET-A", description="Widget A",
                     quantity=Decimal("10"), unit_price=Decimal("100.00"),
                     line_total=Decimal("1000.00")),
            LineItem(product_code="WIDGET-B", description="Widget B",
                     quantity=Decimal("5"), unit_price=Decimal("100.00"),
                     line_total=Decimal("500.00")),
        ],
    )


def clean_gr(po_number: str = "P00001") -> GoodsReceipt:
    return GoodsReceipt(
        id=101, gr_number="WH/IN/00001", po_number=po_number,
        receipt_date="2026-03-05", state="done",
        lines=[
            LineItem(product_code="WIDGET-A", description="Widget A", quantity=Decimal("10")),
            LineItem(product_code="WIDGET-B", description="Widget B", quantity=Decimal("5")),
        ],
    )


def clean_invoice(po_number: str = "P00001") -> VendorInvoice:
    return VendorInvoice(
        id=201, invoice_number="BILL/2026/0001", vendor_id=10, vendor_name="Acme Industrial",
        invoice_date="2026-03-08", po_number=po_number, currency="USD",
        total=Decimal("1500.00"), untaxed_total=Decimal("1500.00"), state="posted",
        lines=[
            LineItem(product_code="WIDGET-A", description="Widget A",
                     quantity=Decimal("10"), unit_price=Decimal("100.00"),
                     line_total=Decimal("1000.00")),
            LineItem(product_code="WIDGET-B", description="Widget B",
                     quantity=Decimal("5"), unit_price=Decimal("100.00"),
                     line_total=Decimal("500.00")),
        ],
    )
