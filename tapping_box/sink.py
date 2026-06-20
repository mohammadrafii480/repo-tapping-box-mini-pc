"""Pengirim ke pusat: buka SSH tunnel (key auth) lalu INSERT ke FileTransferStage2.

Tunnel dibuka sekali per batch (bukan per baris). FileTime & InsertTimeStamp
diisi NOW() di sisi MySQL pusat agar otoritatif (hindari clock-skew board).
"""
from __future__ import annotations

import logging
from typing import List, Set

import pymysql
from sshtunnel import SSHTunnelForwarder

from .config import Config
from .models import OutboxRecord

log = logging.getLogger(__name__)

_INSERT = (
    "INSERT INTO `FileTransferStage2` "
    "(`DeviceId`,`FileIdentifier`,`FileSize`,`FileName`,`FileData`,`FileTime`,`InsertTimeStamp`) "
    "VALUES (%s,%s,%s,%s,%s,NOW(),NOW())"
)
_EXISTS = (
    "SELECT 1 FROM `FileTransferStage2` "
    "WHERE `DeviceId`=%s AND `FileIdentifier`=%s LIMIT 1"
)


def push(cfg: Config, records: List[OutboxRecord]) -> Set[str]:
    """Kirim batch. Kembalikan set pos_txn_id yang sukses (atau sudah ada di pusat)."""
    if not records:
        return set()

    sent: Set[str] = set()
    with SSHTunnelForwarder(
        (cfg.ssh.host, cfg.ssh.port),
        ssh_username=cfg.ssh.user,
        ssh_pkey=cfg.ssh.key_path,
        remote_bind_address=(cfg.ssh.remote_bind_host, cfg.ssh.remote_bind_port),
        local_bind_address=("127.0.0.1", 0),
    ) as tunnel:
        conn = pymysql.connect(
            host="127.0.0.1", port=tunnel.local_bind_port,
            user=cfg.central.user, password=cfg.central.password,
            database=cfg.central.database, charset="utf8mb4",
            connect_timeout=15, write_timeout=30, autocommit=False,
        )
        try:
            with conn.cursor() as cur:
                for r in records:
                    if cfg.runtime.remote_dedup_guard:
                        cur.execute(_EXISTS, (r.device_id, r.file_identifier))
                        if cur.fetchone():
                            sent.add(r.pos_txn_id)  # sudah ada -> anggap terkirim
                            continue
                    cur.execute(_INSERT, (
                        r.device_id, r.file_identifier, r.file_size, r.file_name, r.file_data,
                    ))
                    conn.commit()
                    sent.add(r.pos_txn_id)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return sent
