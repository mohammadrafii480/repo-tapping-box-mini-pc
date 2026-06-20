"""Orkestrasi daemon: pull -> enqueue -> push -> mark -> vacuum -> sleep.

CLI:
  python -m tapping_box run      # daemon loop (dipakai systemd)
  python -m tapping_box once     # satu siklus lalu keluar
  python -m tapping_box dry-run  # tarik + render, cetak, TANPA kirim
  python -m tapping_box doctor   # cek konektivitas sumber/tunnel/pusat
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime

import pymysql
from sshtunnel import SSHTunnelForwarder

from . import receipt, sink, source
from .config import Config, load_config
from .models import OutboxRecord, Transaction
from .store import Store

log = logging.getLogger("tapping_box")
_running = True


def _build_record(cfg: Config, txn: Transaction) -> OutboxRecord:
    text = receipt.render(txn, cfg.device.struk_header)
    data = text.encode("utf-8")
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    name = f"{cfg.device.nama_wp}_{ts}"[:45]  # FileName varchar(45)
    return OutboxRecord(
        pos_txn_id=txn.txn_id,
        device_id=cfg.device.npwp,
        file_identifier=txn.txn_id.encode("utf-8"),
        file_name=name,
        file_data=data,
        file_size=len(data),
    )


def pull(cfg: Config, store: Store) -> int:
    wm = store.get_watermark()
    after = max(0, wm - cfg.runtime.rescan_window)
    txns = source.fetch_since(cfg.source, cfg.schema, after, cfg.runtime.batch_size)
    new = 0
    max_id = wm
    for txn in txns:
        if store.enqueue(_build_record(cfg, txn)):
            new += 1
        max_id = max(max_id, int(txn.txn_id))
    if max_id > wm:
        store.set_watermark(max_id)
    if new:
        log.info("pull: %d transaksi baru (watermark=%d)", new, max_id)
    return new


def push(cfg: Config, store: Store) -> int:
    pending = store.pending(cfg.runtime.batch_size)
    if not pending:
        return 0
    try:
        ok = sink.push(cfg, pending)
    except Exception as exc:  # koneksi/tunnel gagal -> retry siklus berikutnya
        for r in pending:
            store.bump_attempt(r.pos_txn_id)
        log.warning("push gagal (%s); %d tertahan di outbox", exc, len(pending))
        return 0
    for pid in ok:
        store.mark_sent(pid)
    log.info("push: %d terkirim, %d tersisa", len(ok), store.pending_count())
    return len(ok)


def cycle(cfg: Config, store: Store) -> None:
    pull(cfg, store)
    push(cfg, store)
    removed = store.vacuum_old(cfg.runtime.retention_days)
    if removed:
        log.info("retensi: %d baris lama dibersihkan", removed)


def run_loop(cfg: Config, store: Store) -> None:
    log.info("daemon mulai (interval=%ds)", cfg.runtime.poll_interval_sec)
    while _running:
        try:
            cycle(cfg, store)
        except Exception:
            log.exception("siklus error; lanjut siklus berikutnya")
        for _ in range(cfg.runtime.poll_interval_sec):
            if not _running:
                break
            time.sleep(1)
    log.info("daemon berhenti")


def dry_run(cfg: Config) -> None:
    txns = source.fetch_since(cfg.source, cfg.schema, 0, cfg.runtime.batch_size)
    print(f"# {len(txns)} transaksi diambil (TANPA kirim)\n")
    for t in txns:
        print(receipt.render(t, cfg.device.struk_header))
        print()


def doctor(cfg: Config) -> int:
    rc = 0

    def ok(label: str) -> None:
        print(f"  [OK]   {label}")

    def fail(label: str, exc: Exception) -> None:
        nonlocal rc
        rc = 1
        print(f"  [FAIL] {label}: {exc}")

    print("Sumber (Quinos MySQL):")
    try:
        c = pymysql.connect(host=cfg.source.host, port=cfg.source.port, user=cfg.source.user,
                            password=cfg.source.password, database=cfg.source.database,
                            connect_timeout=8)
        with c.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM `{cfg.schema.txn_table}`")
            n = cur.fetchone()[0]
        c.close()
        ok(f"{cfg.source.host}:{cfg.source.port} ({n} baris di {cfg.schema.txn_table})")
    except Exception as e:
        fail("koneksi sumber", e)

    print("Pusat (SSH tunnel + MySQL trumon):")
    try:
        with SSHTunnelForwarder(
            (cfg.ssh.host, cfg.ssh.port), ssh_username=cfg.ssh.user, ssh_pkey=cfg.ssh.key_path,
            remote_bind_address=(cfg.ssh.remote_bind_host, cfg.ssh.remote_bind_port),
            local_bind_address=("127.0.0.1", 0),
        ) as t:
            c = pymysql.connect(host="127.0.0.1", port=t.local_bind_port, user=cfg.central.user,
                                password=cfg.central.password, database=cfg.central.database,
                                connect_timeout=10)
            with c.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM `FileTransferStage2`")
                n = cur.fetchone()[0]
            c.close()
        ok(f"tunnel {cfg.ssh.host} -> trumon ({n} baris di FileTransferStage2)")
    except Exception as e:
        fail("tunnel/pusat", e)

    return rc


def _stop(_sig: int, _frm: object) -> None:
    global _running
    _running = False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tapping_box")
    p.add_argument("cmd", choices=["run", "once", "dry-run", "doctor"])
    p.add_argument("-c", "--config", default="/opt/tapping-box/config.toml")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config(args.config)

    if args.cmd == "doctor":
        return doctor(cfg)
    if args.cmd == "dry-run":
        dry_run(cfg)
        return 0

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    store = Store(cfg.runtime.sqlite_path)
    try:
        if args.cmd == "once":
            cycle(cfg, store)
        else:
            run_loop(cfg, store)
    finally:
        store.close()
    return 0
