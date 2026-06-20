"""Penyimpanan lokal SQLite: cache transaksi (outbox) + watermark + retensi.

Pola outbox membuat pengiriman idempotent & tahan koneksi seluler putus.
Kompatibel Python 3.5 (tanpa f-string).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime

from .models import OutboxRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox(
  pos_txn_id      TEXT PRIMARY KEY,
  device_id       TEXT NOT NULL,
  file_identifier BLOB NOT NULL,
  file_name       TEXT NOT NULL,
  file_data       BLOB NOT NULL,
  file_size       INTEGER NOT NULL,
  status          TEXT NOT NULL DEFAULT 'pending',
  attempts        INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL,
  sent_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def _now():
    return datetime.utcnow().isoformat()


class Store(object):
    def __init__(self, path):
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        self._db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(_SCHEMA)

    def close(self):
        self._db.close()

    # --- watermark ---
    def get_watermark(self):
        row = self._db.execute("SELECT value FROM meta WHERE key='watermark'").fetchone()
        return int(row[0]) if row else 0

    def set_watermark(self, value):
        self._db.execute(
            "INSERT INTO meta(key,value) VALUES('watermark',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(value),),
        )

    # --- outbox ---
    def enqueue(self, rec):
        """INSERT OR IGNORE -> True jika baru, False jika sudah ada (dedup)."""
        cur = self._db.execute(
            "INSERT OR IGNORE INTO outbox"
            "(pos_txn_id,device_id,file_identifier,file_name,file_data,file_size,created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (rec.pos_txn_id, rec.device_id, rec.file_identifier, rec.file_name,
             rec.file_data, rec.file_size, _now()),
        )
        return cur.rowcount > 0

    def pending(self, limit):
        rows = self._db.execute(
            "SELECT pos_txn_id,device_id,file_identifier,file_name,file_data,file_size"
            " FROM outbox WHERE status='pending' ORDER BY pos_txn_id ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [OutboxRecord(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows]

    def mark_sent(self, pos_txn_id):
        self._db.execute(
            "UPDATE outbox SET status='sent', sent_at=? WHERE pos_txn_id=?",
            (_now(), pos_txn_id),
        )

    def bump_attempt(self, pos_txn_id):
        self._db.execute("UPDATE outbox SET attempts=attempts+1 WHERE pos_txn_id=?", (pos_txn_id,))

    def pending_count(self):
        return self._db.execute("SELECT COUNT(*) FROM outbox WHERE status='pending'").fetchone()[0]

    def vacuum_old(self, retention_days):
        cur = self._db.execute(
            "DELETE FROM outbox WHERE status='sent' AND sent_at < datetime('now', ?)",
            ("-{} days".format(retention_days),),
        )
        return cur.rowcount
