"""Verifikasi renderer struk persis sesuai contoh FileData di spesifikasi."""
from datetime import datetime

from tapping_box.models import LineItem, Transaction
from tapping_box.receipt import render

EXPECTED = """========== STRUK PEMBAYARAN ==========
tes
jln jln
50
Tanggal       : 18-07-2025 09:18
No Transaksi  : 1
Meja          : 10
Kasir         : User #1
-- Item Detail --
3x Produk ID 1 @ 20000 = 60000
Subtotal      : Rp 60000
Service       : Rp 3000
Pajak         : Rp 6000
------------------------------
TOTAL         : Rp 69000
Pembayaran    : Cash
Dibayar       : Rp 70000
Kembalian     : Rp 1000
Terima kasih!
======================================"""


def test_render_matches_spec():
    txn = Transaction(
        txn_id="1", txn_no="1", time=datetime(2025, 7, 18, 9, 18),
        table_no="10", cashier="User #1",
        subtotal=60000, service=3000, tax=6000, total=69000,
        pay_method="Cash", paid=70000, change=1000,
        items=[LineItem(qty=3, name="Produk ID 1", unit_price=20000, line_total=60000)],
    )
    assert render(txn, ["tes", "jln jln", "50"]) == EXPECTED
