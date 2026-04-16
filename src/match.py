"""
Deterministic three-way match logic.

This runs as plain Python — no LLM. The agent in ``agent.py`` calls this via a
tool and then narrates the result. Keeping the math outside the model is how we
eliminate hallucinated dollar amounts: the LLM never does arithmetic on money.
"""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Optional

from .models import (
    Action,
    Discrepancy,
    GoodsReceipt,
    MatchResult,
    PurchaseOrder,
    VendorInvoice,
)


def _tolerances() -> tuple[Decimal, Decimal, Decimal]:
    price_usd = Decimal(os.getenv("PRICE_VARIANCE_TOLERANCE_USD", "5.00"))
    price_pct = Decimal(os.getenv("PRICE_VARIANCE_TOLERANCE_PCT", "0.02"))
    qty = Decimal(os.getenv("QUANTITY_VARIANCE_TOLERANCE", "0"))
    return price_usd, price_pct, qty


def _index_lines(lines) -> dict:
    out: dict = {}
    for ln in lines:
        out.setdefault(ln.product_code, []).append(ln)
    return out


def three_way_match(
    po: PurchaseOrder,
    gr: Optional[GoodsReceipt],
    invoice: VendorInvoice,
    duplicate_candidates: Optional[list[dict]] = None,
) -> MatchResult:
    """Run the match. Pure function — no I/O, no randomness."""
    price_tol_usd, price_tol_pct, qty_tol = _tolerances()
    discrepancies: list[Discrepancy] = []
    audit: list[str] = []

    # --- Reference integrity ---
    audit.append(f"Invoice {invoice.invoice_number} references PO {invoice.po_number!r}; PO found: {po.po_number}")
    if invoice.po_number and invoice.po_number != po.po_number:
        discrepancies.append(Discrepancy(
            code="PO_REF_MISMATCH",
            severity="block",
            description=(
                f"Invoice cites PO {invoice.po_number!r} but fetched PO {po.po_number!r}."
            ),
            evidence={"invoice_po_ref": invoice.po_number, "fetched_po": po.po_number},
        ))

    if invoice.vendor_id != po.vendor_id:
        discrepancies.append(Discrepancy(
            code="VENDOR_MISMATCH",
            severity="block",
            description=(
                f"Invoice vendor {invoice.vendor_name!r} does not match PO vendor {po.vendor_name!r}."
            ),
            evidence={"invoice_vendor_id": invoice.vendor_id, "po_vendor_id": po.vendor_id},
        ))

    # --- Goods receipt existence ---
    if gr is None:
        discrepancies.append(Discrepancy(
            code="MISSING_GR",
            severity="block",
            description=f"No completed goods receipt found for PO {po.po_number}. Cannot confirm goods received.",
            evidence={"po_number": po.po_number},
        ))
        audit.append("Missing goods receipt — downstream quantity checks skipped")

    # --- Line-level checks ---
    po_lines = _index_lines(po.lines)
    gr_lines = _index_lines(gr.lines) if gr else {}
    inv_lines = _index_lines(invoice.lines)

    all_skus = set(po_lines) | set(gr_lines) | set(inv_lines)
    for sku in sorted(all_skus):
        po_qty = sum((ln.quantity for ln in po_lines.get(sku, [])), Decimal("0"))
        gr_qty = sum((ln.quantity for ln in gr_lines.get(sku, [])), Decimal("0"))
        inv_qty = sum((ln.quantity for ln in inv_lines.get(sku, [])), Decimal("0"))

        po_price = po_lines.get(sku, [None])[0].unit_price if po_lines.get(sku) else Decimal("0")
        inv_price = inv_lines.get(sku, [None])[0].unit_price if inv_lines.get(sku) else Decimal("0")

        audit.append(
            f"  sku={sku}: po_qty={po_qty} gr_qty={gr_qty} inv_qty={inv_qty} "
            f"po_price={po_price} inv_price={inv_price}"
        )

        # Invoice for something not on PO
        if sku not in po_lines and inv_qty > 0:
            discrepancies.append(Discrepancy(
                code="INVOICED_NOT_ORDERED",
                severity="block",
                product_code=sku,
                description=f"SKU {sku} invoiced (qty {inv_qty}) but not on PO.",
                evidence={"invoice_qty": str(inv_qty)},
            ))
            continue

        # Quantity variance: invoice vs. goods received (or vs. PO if no GR)
        reference_qty = gr_qty if gr is not None else po_qty
        reference_label = "received" if gr is not None else "ordered"
        qty_delta = inv_qty - reference_qty
        if abs(qty_delta) > qty_tol:
            discrepancies.append(Discrepancy(
                code="QTY_MISMATCH",
                severity="block" if gr is not None else "warn",
                product_code=sku,
                description=(
                    f"SKU {sku}: invoiced {inv_qty} vs. {reference_label} {reference_qty} "
                    f"(delta {qty_delta:+})."
                ),
                evidence={
                    "invoice_qty": str(inv_qty),
                    f"{reference_label}_qty": str(reference_qty),
                    "delta": str(qty_delta),
                },
            ))

        # Price variance: invoice vs. PO
        if po_price > 0 and inv_price > 0:
            price_delta = inv_price - po_price
            price_pct_delta = (price_delta / po_price) if po_price else Decimal("0")
            price_logic = os.getenv("PRICE_VARIANCE_LOGIC", "and").lower()
            price_flag = (
                abs(price_delta) > price_tol_usd or abs(price_pct_delta) > price_tol_pct
                if price_logic == "or"
                else abs(price_delta) > price_tol_usd and abs(price_pct_delta) > price_tol_pct
            )
            if price_flag:
                discrepancies.append(Discrepancy(
                    code="PRICE_VARIANCE",
                    severity="warn",
                    product_code=sku,
                    description=(
                        f"SKU {sku}: invoice unit price ${inv_price} vs. PO ${po_price} "
                        f"(delta ${price_delta:+}, {price_pct_delta:+.2%}). Outside tolerance."
                    ),
                    evidence={
                        "invoice_unit_price": str(inv_price),
                        "po_unit_price": str(po_price),
                        "delta_usd": str(price_delta),
                        "delta_pct": str(price_pct_delta),
                        "tolerance_usd": str(price_tol_usd),
                        "tolerance_pct": str(price_tol_pct),
                    },
                ))

    # --- Invoice total sanity ---
    # Line totals are pre-tax (Odoo's price_subtotal), so we compare against
    # the pre-tax header (amount_untaxed), not the tax-inclusive amount_total.
    # Tax is a separate GL posting and outside the AP three-way match.
    calculated_total = sum((ln.line_total for ln in invoice.lines), Decimal("0"))
    if abs(calculated_total - invoice.untaxed_total) > Decimal("0.02"):
        discrepancies.append(Discrepancy(
            code="INVOICE_TOTAL_MISMATCH",
            severity="warn",
            description=(
                f"Invoice pre-tax total ${invoice.untaxed_total} does not match sum of line totals ${calculated_total}."
            ),
            evidence={
                "untaxed_header_total": str(invoice.untaxed_total),
                "calculated_total": str(calculated_total),
                "tax_inclusive_total": str(invoice.total),
            },
        ))

    # --- Duplicate invoice check ---
    if duplicate_candidates:
        for dup in duplicate_candidates:
            discrepancies.append(Discrepancy(
                code="DUPLICATE_INVOICE",
                severity="block",
                description=(
                    f"Possible duplicate: vendor already has invoice {dup['name']} "
                    f"dated {dup['invoice_date']} for ${dup['amount_total']} (state {dup['state']})."
                ),
                evidence=dup,
            ))

    # --- Decide the action ---
    severities = {d.severity for d in discrepancies}
    if "block" in severities:
        action: Action = "block"
        rationale = _rationale_for("block", discrepancies, po, invoice)
    elif "warn" in severities:
        action = "route_for_review"
        rationale = _rationale_for("route_for_review", discrepancies, po, invoice)
    else:
        action = "approve"
        rationale = (
            f"All three documents agree: PO {po.po_number}, invoice {invoice.invoice_number}, "
            f"and goods receipt reconcile on vendor, quantities, and unit prices within tolerance. "
            f"Safe to approve for ${invoice.total}."
        )

    audit.append(f"Final action: {action} ({len(discrepancies)} discrepancies)")

    return MatchResult(
        po_number=po.po_number,
        invoice_number=invoice.invoice_number,
        gr_number=gr.gr_number if gr else None,
        discrepancies=discrepancies,
        recommended_action=action,
        rationale=rationale,
        audit_trail=audit,
    )


def _rationale_for(
    action: Action, discrepancies: list[Discrepancy],
    po: PurchaseOrder, invoice: VendorInvoice,
) -> str:
    blocks = [d for d in discrepancies if d.severity == "block"]
    warns = [d for d in discrepancies if d.severity == "warn"]
    if action == "block":
        reason = blocks[0].description if blocks else "critical discrepancy"
        extra = f" plus {len(discrepancies) - 1} other flag(s)" if len(discrepancies) > 1 else ""
        return (
            f"Blocking payment on invoice {invoice.invoice_number} for ${invoice.total}. "
            f"Primary reason: {reason}{extra}. Route to AP manager with the attached audit trail."
        )
    if action == "route_for_review":
        reason = warns[0].description if warns else "variance outside tolerance"
        return (
            f"Routing invoice {invoice.invoice_number} to AP lead for human approval. "
            f"Primary reason: {reason}. Dollar exposure if approved as-is: ${invoice.total}."
        )
    return f"Approve invoice {invoice.invoice_number} for ${invoice.total}."
