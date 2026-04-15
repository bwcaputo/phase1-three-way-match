"""
Tests for the deterministic match logic.

These tests hit every recommended_action branch (approve / route / block) and
every discrepancy code the system can emit. They are how we prove the LLM
never has to be trusted with math.
"""
from __future__ import annotations

from decimal import Decimal

from src.match import three_way_match
from src.models import LineItem
from tests.fixtures import clean_gr, clean_invoice, clean_po


def test_clean_match_approves() -> None:
    result = three_way_match(clean_po(), clean_gr(), clean_invoice())
    assert result.recommended_action == "approve"
    assert result.discrepancies == []


def test_missing_gr_blocks() -> None:
    result = three_way_match(clean_po(), None, clean_invoice())
    assert result.recommended_action == "block"
    codes = [d.code for d in result.discrepancies]
    assert "MISSING_GR" in codes


def test_quantity_over_invoiced_blocks() -> None:
    inv = clean_invoice()
    inv.lines[0].quantity = Decimal("12")  # billed 12, received 10
    inv.lines[0].line_total = Decimal("1200.00")
    inv.total = Decimal("1700.00")
    inv.untaxed_total = Decimal("1700.00")
    result = three_way_match(clean_po(), clean_gr(), inv)
    assert result.recommended_action == "block"
    assert any(d.code == "QTY_MISMATCH" for d in result.discrepancies)


def test_price_variance_routes_for_review() -> None:
    inv = clean_invoice()
    inv.lines[0].unit_price = Decimal("115.00")  # 15% over PO
    inv.lines[0].line_total = Decimal("1150.00")
    inv.total = Decimal("1650.00")
    inv.untaxed_total = Decimal("1650.00")
    result = three_way_match(clean_po(), clean_gr(), inv)
    assert result.recommended_action == "route_for_review"
    assert any(d.code == "PRICE_VARIANCE" for d in result.discrepancies)


def test_price_variance_within_tolerance_approves() -> None:
    inv = clean_invoice()
    inv.lines[0].unit_price = Decimal("101.00")  # 1% over — inside default tolerance
    inv.lines[0].line_total = Decimal("1010.00")
    inv.total = Decimal("1510.00")
    inv.untaxed_total = Decimal("1510.00")
    result = three_way_match(clean_po(), clean_gr(), inv)
    assert result.recommended_action == "approve"


def test_invoiced_not_ordered_blocks() -> None:
    inv = clean_invoice()
    inv.lines.append(LineItem(
        product_code="WIDGET-Z", description="Widget Z (rogue)",
        quantity=Decimal("3"), unit_price=Decimal("50.00"), line_total=Decimal("150.00"),
    ))
    inv.total = Decimal("1650.00")
    inv.untaxed_total = Decimal("1650.00")
    result = three_way_match(clean_po(), clean_gr(), inv)
    assert result.recommended_action == "block"
    assert any(d.code == "INVOICED_NOT_ORDERED" for d in result.discrepancies)


def test_vendor_mismatch_blocks() -> None:
    inv = clean_invoice()
    inv.vendor_id = 99  # different vendor
    inv.vendor_name = "Totally Different Vendor LLC"
    result = three_way_match(clean_po(), clean_gr(), inv)
    assert result.recommended_action == "block"
    assert any(d.code == "VENDOR_MISMATCH" for d in result.discrepancies)


def test_duplicate_invoice_blocks() -> None:
    dups = [{
        "id": 999, "name": "BILL/2026/0001-DUP",
        "invoice_date": "2026-03-01", "amount_total": 1500.00, "state": "posted",
    }]
    result = three_way_match(clean_po(), clean_gr(), clean_invoice(), duplicate_candidates=dups)
    assert result.recommended_action == "block"
    assert any(d.code == "DUPLICATE_INVOICE" for d in result.discrepancies)


def test_invoice_header_vs_lines_routes() -> None:
    inv = clean_invoice()
    inv.untaxed_total = Decimal("1600.00")  # pre-tax header says 1600, lines sum to 1500
    result = three_way_match(clean_po(), clean_gr(), inv)
    assert result.recommended_action in {"route_for_review", "block"}
    assert any(d.code == "INVOICE_TOTAL_MISMATCH" for d in result.discrepancies)


def test_audit_trail_is_populated() -> None:
    result = three_way_match(clean_po(), clean_gr(), clean_invoice())
    assert result.audit_trail, "audit trail must never be empty"
    assert any("Final action" in line for line in result.audit_trail)
