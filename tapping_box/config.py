"""Pemuat & validasi konfigurasi dari config.toml."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


@dataclass(frozen=True)
class SourceSchema:
    """Pemetaan nama tabel/kolom DB Quinos. WAJIB diverifikasi via DESCRIBE."""
    txn_table: str
    txn_id: str
    txn_no: str
    txn_time: str
    table_no: str
    cashier: str
    subtotal: str
    service: str
    tax: str
    total: str
    pay_method: str
    paid: str
    change: str
    item_table: str
    item_fk: str
    item_qty: str
    item_name: str
    item_price: str
    item_total: str  # boleh "" -> dihitung qty*price


@dataclass(frozen=True)
class DbConn:
    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass(frozen=True)
class SshTunnel:
    host: str
    port: int
    user: str
    key_path: str
    remote_bind_host: str
    remote_bind_port: int


@dataclass(frozen=True)
class Device:
    npwp: str               # DeviceId
    nama_wp: str            # untuk FileName
    struk_header: List[str] # 3 baris header struk (nama/alamat/dll)


@dataclass(frozen=True)
class Runtime:
    poll_interval_sec: int
    batch_size: int
    retention_days: int
    remote_dedup_guard: bool
    sqlite_path: str
    rescan_window: int      # mundur N id dari watermark sbg jaring pengaman


@dataclass(frozen=True)
class Config:
    source: DbConn
    schema: SourceSchema
    central: DbConn
    ssh: SshTunnel
    device: Device
    runtime: Runtime


def _req(d: Dict[str, Any], key: str, ctx: str) -> Any:
    if key not in d:
        raise ValueError(f"[{ctx}] kunci wajib hilang: '{key}'")
    return d[key]


def load_config(path: str | Path) -> Config:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))

    src = _req(raw, "source", "config")
    sch = _req(src, "schema", "source")
    ctr = _req(raw, "central", "config")
    ssh = _req(raw, "ssh", "config")
    dev = _req(raw, "device", "config")
    rt = _req(raw, "runtime", "config")

    cfg = Config(
        source=DbConn(src["host"], int(src["port"]), src["user"], src["password"], src["database"]),
        schema=SourceSchema(**{k: sch.get(k, "") for k in SourceSchema.__annotations__}),
        central=DbConn(ctr["host"], int(ctr["port"]), ctr["user"], ctr["password"], ctr["database"]),
        ssh=SshTunnel(ssh["host"], int(ssh["port"]), ssh["user"], ssh["key_path"],
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
