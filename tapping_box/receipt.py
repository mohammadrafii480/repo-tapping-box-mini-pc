"""Render teks struk persis sesuai format FileData yang ditentukan.

Fungsi murni (tanpa I/O) supaya mudah diuji.
"""
from __future__ import annotations

from .models import Transaction

_TOP = "========== STRUK PEMBAYARAN =========="
_ITEM_HDR = "-- Item Detail --"
_SEP = "------------------------------"
_BOTTOM = "======================================"
_LABEL_W = 14  # lebar kolom label sebelum ": "


def _row(label: str, value: str) -> str:
    return f"{label:<{_LABEL_W}}: {value}"


def _rp(amount: int) -> str:
    return f"Rp {int(amount)}"


def render(txn: Transaction, header_lines: list[str]) -> str:
    """Hasilkan teks struk untuk satu transaksi."""
    lines: list[str] = [_TOP, *header_lines]
    lines.append(_row("Tanggal", txn.time.strftime("%d-%m-%Y %H:%M")))
    lines.append(_row("No Transaksi", txn.txn_no))
    lines.append(_row("Meja", txn.table_no))
    lines.append(_row("Kasir", txn.cashier))
    lines.append(_ITEM_HDR)
    for it in txn.items:
        lines.append(f"{it.qty}x {it.name} @ {it.unit_price} = {it.line_total}")
    lines.append(_row("Subtotal", _rp(txn.subtotal)))
    lines.append(_row("Service", _rp(txn.service)))
    lines.append(_row("Pajak", _rp(txn.tax)))
    lines.append(_SEP)
    lines.append(_row("TOTAL", _rp(txn.total)))
    lines.append(_row("Pembayaran", txn.pay_method))
    lines.append(_row("Dibayar", _rp(txn.paid)))
    lines.append(_row("Kembalian", _rp(txn.change)))
    lines.append("Terima kasih!")
    lines.append(_BOTTOM)
    return "\n".join(lines)
