"""Pengirim ke pusat: buka SSH tunnel via binary `ssh` (subprocess) lalu
INSERT ke FileTransferStage2.

Kenapa bukan paramiko/sshtunnel: board target Python 3.5 (EOL), paramiko
modern butuh 3.6+ dan tidak ada wheel `cryptography` yang aman utk
kombinasi glibc/Python setua ini tanpa compiler. `ssh` OpenSSH sudah
terpasang di board (/usr/bin/ssh) dan lepas total dari masalah itu.
"""
from __future__ import annotations

import logging
import socket
import subprocess
import time
from typing import List, Optional, Set

import pymysql

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

_TUNNEL_READY_TIMEOUT_SEC = 15
_TUNNEL_POLL_INTERVAL_SEC = 0.3


def _free_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


class SshTunnel(object):
    """Context manager: buka `ssh -L local_port:remote_host:remote_port` sbg subprocess."""

    def __init__(self, cfg):
        self._cfg = cfg
        self.local_port = _free_local_port()
        self._proc = None  # type: Optional[subprocess.Popen]

    def __enter__(self):
        ssh = self._cfg.ssh
        cmd = [
            "/usr/bin/ssh",
            "-i", ssh.key_path,
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "BatchMode=yes",          # gagal cepat kalau key tidak diterima, bukan prompt password
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=10",
            "-o", "ServerAliveCountMax=3",
            "-N",                            # tanpa remote command, hanya forward
            "-L", "127.0.0.1:{}:{}:{}".format(self.local_port, ssh.remote_bind_host, ssh.remote_bind_port),
            "-p", str(ssh.port),
            "{}@{}".format(ssh.user, ssh.host),
        ]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + _TUNNEL_READY_TIMEOUT_SEC
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                _out, err = self._proc.communicate()
                raise RuntimeError("ssh tunnel mati saat start: {}".format(err.decode("utf-8", errors="replace")))
            if _port_open(self.local_port):
                return self
            time.sleep(_TUNNEL_POLL_INTERVAL_SEC)
        self._kill()
        raise TimeoutError("ssh tunnel tidak siap dalam {}s".format(_TUNNEL_READY_TIMEOUT_SEC))

    def __exit__(self, *exc):
        self._kill()

    def _kill(self):
        if self._proc is None or self._proc.poll() is not None:
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=5)


def push(cfg, records):
    """Kirim batch. Kembalikan set pos_txn_id yang sukses (atau sudah ada di pusat)."""
    if not records:
        return set()

    sent = set()
    with SshTunnel(cfg) as tunnel:
        conn = pymysql.connect(
            host="127.0.0.1", port=tunnel.local_port,
            user=cfg.central.user, password=cfg.central.password,
            database=cfg.central.database, charset="utf8mb4",
            connect_timeout=15, autocommit=False,
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
