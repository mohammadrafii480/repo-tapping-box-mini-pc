#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install.sh — pasang Tapping Box di MYIR MYD-C8MMX-V2 (Yocto sumo, aarch64).
# Tidak ada apt/gcc/pip bawaan -> pip dipasang via get-pip.py, lalu cek wheel
# cryptography (kanari): kalau pip mencoba compile (tak ada gcc), instalasi
# berhenti SEBELUM merusak state, dengan pesan jelas.
# Idempotent: aman dijalankan ulang. Wajib root: sudo ./install.sh
# ---------------------------------------------------------------------------
set -euo pipefail

APP_DIR=/opt/tapping-box
KEY_PATH="$APP_DIR/ssh_key"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
ZT_NETWORK_ID="${ZT_NETWORK_ID:-}"
PIP_BIN="python3 -m pip"

[[ $EUID -eq 0 ]] || { echo "Jalankan sebagai root."; exit 1; }

echo "==> [1/8] Cek prasyarat dasar"
command -v python3 >/dev/null || { echo "python3 tidak ditemukan."; exit 1; }
command -v curl >/dev/null || command -v wget >/dev/null || { echo "curl/wget tidak ada."; exit 1; }
ARCH="$(uname -m)"
[[ "$ARCH" == "aarch64" ]] || echo "PERINGATAN: arch=$ARCH, skrip ini ditarget aarch64."

echo "==> [2/8] Pasang pip (get-pip.py) bila belum ada"
if ! python3 -m pip --version >/dev/null 2>&1; then
  curl -sSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py \
    || wget -qO /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py
  python3 /tmp/get-pip.py --no-cache-dir
  rm -f /tmp/get-pip.py
fi
python3 -m pip install --upgrade pip --no-cache-dir
echo "    pip: $(python3 -m pip --version)"

echo "==> [3/8] Kanari: pastikan 'cryptography' tersedia sbg wheel (tanpa compile)"
# --only-binary memaksa pip GAGAL (bukan fallback compile) kalau tak ada wheel cocok.
# Ini sengaja: lebih baik gagal cepat & jelas drpd macet compile tanpa gcc.
if ! python3 -m pip install --only-binary=:all: --no-cache-dir "cryptography" 2>/tmp/crypto_err.log; then
  echo ""
  echo "GAGAL: tidak ada wheel binary 'cryptography' yang cocok untuk platform ini."
  echo "Tidak ada gcc/Rust di board -> install dari source tidak mungkin tanpa toolchain."
  echo "Detail error:"
  cat /tmp/crypto_err.log
  echo ""
  echo "Opsi: (a) pasang gcc+rust dulu (butuh banyak ruang & waktu di board lemah),"
  echo "      (b) cross-compile wheel di mesin lain lalu salin ke board,"
  echo "      (c) ganti sink.py ke metode tunnel tanpa paramiko (mis. shell out ke /usr/bin/ssh)."
  exit 1
fi
echo "    OK: wheel cryptography terpasang tanpa compiler."

echo "==> [4/8] Pasang dependency aplikasi"
python3 -m pip install --no-cache-dir -r "$SRC_DIR/requirements.txt"

echo "==> [5/8] Zona waktu (WITA)"
timedatectl set-timezone Asia/Makassar 2>/dev/null \
  || ln -sf /usr/share/zoneinfo/Asia/Makassar /etc/localtime

echo "==> [6/8] ZeroTier (binary static, tanpa apt)"
if ! command -v zerotier-one >/dev/null 2>&1 && ! command -v zerotier-cli >/dev/null 2>&1; then
  curl -s https://install.zerotier.com | bash || {
    echo "PERINGATAN: installer resmi ZeroTier gagal (kemungkinan butuh apt/dnf/yum)."
    echo "Pasang manual: unduh tarball aarch64 dari https://www.zerotier.com/download/ ke board."
  }
fi
if command -v zerotier-one >/dev/null 2>&1; then
  systemctl enable --now zerotier-one
  [[ -n "$ZT_NETWORK_ID" ]] && { zerotier-cli join "$ZT_NETWORK_ID" || true; }
fi

echo "==> [7/8] Salin aplikasi ke $APP_DIR"
mkdir -p "$APP_DIR/data"
cp -r "$SRC_DIR/tapping_box" "$APP_DIR/"
[[ -f "$APP_DIR/config.toml" ]] || cp "$SRC_DIR/config.toml.example" "$APP_DIR/config.toml"
if [[ ! -f "$KEY_PATH" ]]; then
  ssh-keygen -t ed25519 -N "" -C "tapping-box@$(hostname)" -f "$KEY_PATH"
fi
chmod 600 "$KEY_PATH" "$APP_DIR/config.toml"

echo "==> [8/8] systemd service"
cp "$SRC_DIR/tapping-box.service" /etc/systemd/system/
sed -i "s#/opt/tapping-box/venv/bin/python#/usr/bin/python3#" /etc/systemd/system/tapping-box.service
systemctl daemon-reload
systemctl enable tapping-box.service

cat <<MSG

============================ SELESAI ============================
Catatan platform: Yocto sumo (bukan Ubuntu) - tanpa venv, paket Python
terpasang global via pip langsung (tidak ada apt/venv module di image ini).

LANGKAH MANUAL WAJIB:
  1. Edit konfigurasi:        nano $APP_DIR/config.toml
  2. Daftarkan public key ini ke server pusat (dev@109.111.52.86):
--------------------------------------------------------------
$(cat "$KEY_PATH.pub" 2>/dev/null || echo "(key belum dibuat)")
--------------------------------------------------------------
  3. Uji koneksi:   python3 -m tapping_box doctor -c $APP_DIR/config.toml
  4. Uji tarik saja: python3 -m tapping_box dry-run -c $APP_DIR/config.toml
  5. Jalankan:       systemctl start tapping-box && journalctl -u tapping-box -f
================================================================
MSG
