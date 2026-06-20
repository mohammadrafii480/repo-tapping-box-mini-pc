# Tapping Box — Decision Log & Asumsi

## Arsitektur final
POS Quinos MySQL (LAN, TCP 3306) → tarik transaksi baru (watermark) → render struk →
SQLite **outbox** di board → SSH tunnel (key auth) → INSERT `trumon.FileTransferStage2` →
mark sent. ZeroTier hanya untuk SSH admin. Daemon dikelola **systemd**. OS board **Ubuntu**.

## Decision Log
| Keputusan | Alternatif | Alasan |
|---|---|---|
| SQLite lokal | MySQL/MariaDB lokal | Board 2GB RAM / 8GB eMMC; daemon MySQL boros & aus eMMC. SQLite zero-config, cocok pola outbox. |
| Pola outbox + watermark | Query dedup ke pusat tiap siklus | `FileIdentifier` blob (susah jadi kunci); mahal via seluler. Outbox idempotent & tahan putus. |
| systemd daemon | cron | Auto-restart, start-on-boot, log journald — lebih tahan koneksi seluler intermittent. |
| sshtunnel per-batch | autossh persistent | Self-healing, tidak ada socket basi; tunnel sekali per batch (bukan per baris). |
| SSH key auth | password | Plaintext password di field device berisiko. |
| PyMySQL (pure-python) | mysqlclient (C) | Tanpa kompilasi native di arm64. |
| `FileTime`/`InsertTimeStamp` = `NOW()` pusat | jam board | Hindari clock-skew board embedded. |
| Skema sumber via config | hardcode | Skema Quinos belum pasti; remap di config tanpa ubah kode (OCP). |
| Ubuntu | Yocto | Yocto sering tanpa pip & ZeroTier tak punya paket siap-pasang. |

## Update: kembali ke Yocto (bukan Ubuntu)
Keputusan "pindah ke Ubuntu" di atas **dibatalkan** setelah ditemukan fakta lapangan:
- Tidak ada image Ubuntu siap-pakai resmi dari MYIR untuk board ini — yang tersedia
  hanya *porting manual* (build rootfs dari base Canonical, tetap pakai kernel/U-Boot MYIR).
- Flash butuh salah satu dari: USB+UUU tool (Windows/Linux x86, perlu set board ke
  Download mode) atau SD card bootable — keduanya tidak tersedia di lingkungan kerja
  (hanya MacBook, tanpa microSD reader).
- Keputusan: **tetap di Yocto sumo (4.14)** yang sudah terpasang di eMMC, sesuaikan
  instalasi paket Python (pip via get-pip.py, tanpa apt/venv/gcc).

| Keputusan (revisi) | Alternatif | Alasan |
|---|---|---|
| Tetap Yocto sumo | Ubuntu (dibatalkan) | Tidak ada image resmi + alat flash (UUU/SD reader) tidak tersedia. |
| pip via get-pip.py, install global | venv | Image ini tidak punya modul `venv`/`ensurepip`; instalasi global cukup utk single-purpose daemon device. |
| Kanari wheel `cryptography --only-binary` di installer | Asumsi langsung berhasil | glibc 2.27 di board secara teori lolos baseline manylinux2014, tapi tidak diverifikasi vendor; gagal cepat dgn pesan jelas lebih aman drpd macet compile tanpa gcc/Rust. |


## Asumsi (verifikasi sebelum produksi)
1. **Skema Quinos di `config.toml` masih default tebakan** — wajib disamakan via `DESCRIBE`. Ini satu-satunya bagian yang belum terkunci pasti.
2. `txn_id` Quinos numerik & monotonik (dipakai watermark). Jika UUID/string → ganti strategi watermark ke kolom waktu.
3. PC kasir punya IP statis di LAN & MySQL mengizinkan koneksi remote (`bind-address` + grant user).
4. Mapping field struk: 3 baris header dari config; angka tanpa pemisah ribuan (sesuai contoh).
5. Volume kecil (resto) → interval 60s, retensi lokal 90 hari.

## Risiko diketahui
- Sumber tak terjangkau / skema salah → `doctor` & `dry-run` untuk validasi awal.
- Kehilangan SQLite (reflash eMMC) → `remote_dedup_guard=true` mencegah duplikat di pusat.
- Sinyal seluler putus → outbox menahan, retry otomatis siklus berikutnya.
