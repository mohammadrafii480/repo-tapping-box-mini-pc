"""Adapter sumber: tarik transaksi baru dari DB Quinos (MySQL) via LAN.

Query dibangun dari pemetaan kolom di config (SourceSchema) sehingga
beda skema cukup diubah di config.toml, bukan di kode.
Kompatibel Python 3.5 (tanpa f-string).
"""
from __future__ import annotations

import logging
from datetime import datetime

import pymysql

from .models import LineItem, Transaction

log = logging.getLogger(__name__)


def _connect(c):
    return pymysql.connect(
        host=c.host, port=c.port, user=c.user, password=c.password,
        database=c.database, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=10, read_timeout=30,
    )


def _to_int(v):
    return int(v) if v is not None else 0


def fetch_since(conn_cfg, s, after_id, limit):
    """Ambil transaksi dengan txn_id > after_id (urut naik), beserta itemnya."""
    conn = _connect(conn_cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM `{}` WHERE `{}` > %s ORDER BY `{}` ASC LIMIT %s".format(
                    s.txn_table, s.txn_id, s.txn_id
                ),
                (after_id, limit),
            )
            heads = cur.fetchall()
            if not heads:
                return []

            ids = [h[s.txn_id] for h in heads]
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                "SELECT * FROM `{}` WHERE `{}` IN ({})".format(s.item_table, s.item_fk, placeholders),
                ids,
            )
            items_by_txn = {}
            for r in cur.fetchall():
                qty = _to_int(r[s.item_qty])
                price = _to_int(r[s.item_price])
                total = _to_int(r[s.item_total]) if s.item_total else qty * price
                key = r[s.item_fk]
                items_by_txn.setdefault(key, []).append(
                    LineItem(qty=qty, name=str(r[s.item_name]), unit_price=price, line_total=total)
                )

        return [_build(h, s, items_by_txn.get(h[s.txn_id], [])) for h in heads]
    finally:
        conn.close()


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    s = str(value).replace("T", " ")
    if "." in s:
        s = s.split(".", 1)[0]  # buang microsecond, format tidak konsisten antar driver
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.strptime(s, "%Y-%m-%d")


def _build(h, s, items):
    t = _parse_dt(h[s.txn_time])
    return Transaction(
        txn_id=str(h[s.txn_id]),
        txn_no=str(h[s.txn_no]),
        time=t,
        table_no=str(h[s.table_no]),
        cashier=str(h[s.cashier]),
        subtotal=_to_int(h[s.subtotal]),
        service=_to_int(h[s.service]),
        tax=_to_int(h[s.tax]),
        total=_to_int(h[s.total]),
        pay_method=str(h[s.pay_method]),
        paid=_to_int(h[s.paid]),
        change=_to_int(h[s.change]),
        items=items,
    )
