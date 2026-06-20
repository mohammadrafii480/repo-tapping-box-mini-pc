"""Struktur data transaksi yang sudah dinormalisasi (lepas dari skema sumber)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass(frozen=True)
class LineItem:
    qty: int
    name: str
    unit_price: int
    line_total: int


@dataclass(frozen=True)
class Transaction:
    txn_id: str          # PK Quinos -> dipakai sbg FileIdentifier + watermark
    txn_no: str          # "No Transaksi" di struk
    time: datetime
    table_no: str
    cashier: str
    subtotal: int
    service: int
    tax: int
    total: int
    pay_method: str
    paid: int
    change: int
    items: List[LineItem] = field(default_factory=list)


@dataclass(frozen=True)
class OutboxRecord:
    """Baris siap-kirim ke FileTransferStage2 (di-cache di SQLite lokal)."""
    pos_txn_id: str
    device_id: str          # DeviceId = NPWP
    file_identifier: bytes  # FileIdentifier (blob) = txn_id
    file_name: str          # "{nama_wp}_{timestamp}"
    file_data: bytes        # FileData (mediumblob) = teks struk utf-8
    file_size: int          # FileSize = len(file_data)
