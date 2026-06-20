"""Orkestrasi daemon: pull -> enqueue -> push -> mark -> vacuum -> sleep.

CLI:
  python3 -m tapping_box run      # daemon loop (dipakai systemd)
  python3 -m tapping_box once     # satu siklus lalu keluar
  python3 -m tapping_box dry-run  # tarik + render, cetak, TANPA kirim
  python3 -m tapping_box doctor   # cek konektivitas sumber/tunnel/pusat

Kompatibel Python 3.5 (tanpa f-string).
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime

import pymysql

from . import receipt, sink, source
from .config import load_config
from .models import OutboxRecord
from .store import Store

log = logging.getLogger("tapping_box")
_running = [True]  # list = mutable cell, lebih aman lintas-scope drpd 'global' di handler


def _build_record(cfg, txn):
    text = receipt.render(txn, cfg.device.struk_header)
    data = text.encode("utf-8")
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    name = (cfg.device.nama_wp + "_" + ts)[:45]  # FileName varchar(45)
    return OutboxRecord(
        pos_txn_id=txn.txn_id,
        device_id=cfg.device.npwp,
        file_identifier=txn.txn_id.encode("utf-8"),
        file_name=name,
        file_data=data,
        file_size=len(data),
    )


def pull(cfg, store):
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


def push(cfg, store):
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


def cycle(cfg, store):
    pull(cfg, store)
    push(cfg, store)
    removed = store.vacuum_old(cfg.runtime.retention_days)
    if removed:
        log.info("retensi: %d baris lama dibersihkan", removed)


def run_loop(cfg, store):
    log.info("daemon mulai (interval=%ds)", cfg.runtime.poll_interval_sec)
    while _running[0]:
        try:
            cycle(cfg, store)
        except Exception:
            log.exception("siklus error; lanjut siklus berikutnya")
        for _ in range(cfg.runtime.poll_interval_sec):
            if not _running[0]:
                break
            time.sleep(1)
    log.info("daemon berhenti")


def dry_run(cfg):
    txns = source.fetch_since(cfg.source, cfg.schema, 0, cfg.runtime.batch_size)
    print("# {} transaksi diambil (TANPA kirim)\n".format(len(txns)))
    for t in txns:
        print(receipt.render(t, cfg.device.struk_header))
        print("")


def doctor(cfg):
    state = {"rc": 0}

    def ok(label):
        print("  [OK]   {}".format(label))

    def fail(label, exc):
        state["rc"] = 1
        print("  [FAIL] {}: {}".format(label, exc))

    print("Sumber (Quinos MySQL):")
    try:
        c = pymysql.connect(host=cfg.source.host, port=cfg.source.port, user=cfg.source.user,
                            password=cfg.source.password, database=cfg.source.database,
                            connect_timeout=8)
        with c.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM `{}`".format(cfg.schema.txn_table))
            n = cur.fetchone()[0]
        c.close()
        ok("{}:{} ({} baris di {})".format(cfg.source.host, cfg.source.port, n, cfg.schema.txn_table))
    except Exception as e:
        fail("koneksi sumber", e)

    print("Pusat (SSH tunnel + MySQL trumon):")
    try:
        with sink.SshTunnel(cfg) as tunnel:
            c = pymysql.connect(host="127.0.0.1", port=tunnel.local_port, user=cfg.central.user,
                                password=cfg.central.password, database=cfg.central.database,
                                connect_timeout=10)
            with c.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM `FileTransferStage2`")
                n = cur.fetchone()[0]
            c.close()
        ok("tunnel {} -> trumon ({} baris di FileTransferStage2)".format(cfg.ssh.host, n))
    except Exception as e:
        fail("tunnel/pusat", e)

    return state["rc"]


def _stop(_sig, _frm):
    _running[0] = False


def main(argv=None):
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
