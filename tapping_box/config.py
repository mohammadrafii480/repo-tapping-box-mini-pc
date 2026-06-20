"""Pemuat & validasi konfigurasi dari config.toml (kompatibel Python 3.5).

Catatan: tomllib (stdlib) butuh Python 3.11+, tidak tersedia di 3.5.
Pakai 'toml' package (pure-Python, pip install toml) sbg gantinya.
"""
from __future__ import annotations

import toml


class SourceSchema(object):
    """Pemetaan nama tabel/kolom DB Quinos. WAJIB diverifikasi via DESCRIBE."""
    FIELDS = (
        "txn_table", "txn_id", "txn_no", "txn_time", "table_no", "cashier",
        "subtotal", "service", "tax", "total", "pay_method", "paid", "change",
        "item_table", "item_fk", "item_qty", "item_name", "item_price", "item_total",
    )

    def __init__(self, **kw):
        for f in self.FIELDS:
            setattr(self, f, kw.get(f, ""))


class DbConn(object):
    def __init__(self, host, port, user, password, database):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database


class SshTunnelCfg(object):
    def __init__(self, host, port, user, key_path, remote_bind_host, remote_bind_port):
        self.host = host
        self.port = port
        self.user = user
        self.key_path = key_path
        self.remote_bind_host = remote_bind_host
        self.remote_bind_port = remote_bind_port


class Device(object):
    def __init__(self, npwp, nama_wp, struk_header):
        self.npwp = npwp                  # DeviceId
        self.nama_wp = nama_wp            # untuk FileName
        self.struk_header = struk_header  # 3 baris header struk


class Runtime(object):
    def __init__(self, poll_interval_sec, batch_size, retention_days,
                 remote_dedup_guard, sqlite_path, rescan_window):
        self.poll_interval_sec = poll_interval_sec
        self.batch_size = batch_size
        self.retention_days = retention_days
        self.remote_dedup_guard = remote_dedup_guard
        self.sqlite_path = sqlite_path
        self.rescan_window = rescan_window  # mundur N id dari watermark sbg jaring pengaman


class Config(object):
    def __init__(self, source, schema, central, ssh, device, runtime):
        self.source = source
        self.schema = schema
        self.central = central
        self.ssh = ssh
        self.device = device
        self.runtime = runtime


def _req(d, key, ctx):
    if key not in d:
        raise ValueError("[{}] kunci wajib hilang: '{}'".format(ctx, key))
    return d[key]


def load_config(path):
    with open(str(path), "r") as fh:
        raw = toml.load(fh)

    src = _req(raw, "source", "config")
    sch = _req(src, "schema", "source")
    ctr = _req(raw, "central", "config")
    ssh = _req(raw, "ssh", "config")
    dev = _req(raw, "device", "config")
    rt = _req(raw, "runtime", "config")

    cfg = Config(
        source=DbConn(src["host"], int(src["port"]), src["user"], src["password"], src["database"]),
        schema=SourceSchema(**sch),
        central=DbConn(ctr["host"], int(ctr["port"]), ctr["user"], ctr["password"], ctr["database"]),
        ssh=SshTunnelCfg(ssh["host"], int(ssh["port"]), ssh["user"], ssh["key_path"],
                         ssh["remote_bind_host"], int(ssh["remote_bind_port"])),
        device=Device(dev["npwp"], dev["nama_wp"], list(dev["struk_header"])),
        runtime=Runtime(
            int(rt["poll_interval_sec"]), int(rt["batch_size"]), int(rt["retention_days"]),
            bool(rt["remote_dedup_guard"]), rt["sqlite_path"], int(rt.get("rescan_window", 0)),
        ),
    )

    if len(cfg.device.struk_header) != 3:
        raise ValueError("[device] struk_header harus tepat 3 baris")
    if len(cfg.device.npwp) > 45:
        raise ValueError("[device] npwp melebihi 45 char (DeviceId varchar(45))")
    return cfg
