"""Struktur data transaksi (kompatibel Python 3.5 — tanpa dataclasses/f-string)."""
from __future__ import annotations


class LineItem(object):
    __slots__ = ("qty", "name", "unit_price", "line_total")

    def __init__(self, qty, name, unit_price, line_total):
        self.qty = qty
        self.name = name
        self.unit_price = unit_price
        self.line_total = line_total


class Transaction(object):
    __slots__ = (
        "txn_id", "txn_no", "time", "table_no", "cashier",
        "subtotal", "service", "tax", "total",
        "pay_method", "paid", "change", "items",
    )

    def __init__(self, txn_id, txn_no, time, table_no, cashier,
                 subtotal, service, tax, total,
                 pay_method, paid, change, items=None):
        self.txn_id = txn_id          # PK Quinos -> FileIdentifier & watermark
        self.txn_no = txn_no          # "No Transaksi" di struk
        self.time = time
        self.table_no = table_no      # "Meja"
        self.cashier = cashier        # "Kasir"
        self.subtotal = subtotal
        self.service = service
        self.tax = tax
        self.total = total
        self.pay_method = pay_method  # mis. "Cash"
        self.paid = paid
        self.change = change
        self.items = items if items is not None else []


class OutboxRecord(object):
    """Baris siap-kirim ke FileTransferStage2 (di-cache di SQLite lokal)."""
    __slots__ = (
        "pos_txn_id", "device_id", "file_identifier",
        "file_name", "file_data", "file_size",
    )

    def __init__(self, pos_txn_id, device_id, file_identifier, file_name, file_data, file_size):
        self.pos_txn_id = pos_txn_id
        self.device_id = device_id            # DeviceId = NPWP
        self.file_identifier = file_identifier  # FileIdentifier (blob) = txn_id
        self.file_name = file_name            # "{nama_wp}_{timestamp}"
        self.file_data = file_data            # FileData (mediumblob) = teks struk utf-8
        self.file_size = file_size            # FileSize = len(file_data)
