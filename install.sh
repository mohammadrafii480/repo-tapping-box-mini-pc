#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install.sh — pasang Tapping Box di MYIR MYD-C8MMX-V2 (Yocto sumo, aarch64,
# Python 3.5.5 — interpreter EOL, banyak tooling modern tidak kompatibel).
# Idempotent: aman dijalankan ulang. Wajib root: sudo ./install.sh
# Set ZT_NETWORK_ID untuk auto-join ZeroTier, mis:
#   sudo ZT_NETWORK_ID=8056c2e21c000001 ./install.sh
# ---------------------------------------------------------------------------
set -euo pipefail

APP_DIR=/opt/tapping-box
KEY_PATH="$APP_DIR/ssh_key"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
ZT_NETWORK_ID="${ZT_NETWORK_ID:-}"
PY_BIN=python3

[[ $EUID -eq 0 ]] || { echo "Jalankan sebagai root."; exit 1; }

echo "==> [1/8] Cek prasyarat dasar"
command -v "$PY_BIN" >/dev/null || { echo "python3 tidak ditemukan."; exit 1; }
PY_VER="$("$PY_BIN" -c 'import sys; print("%d.%d"%sys.version_info[:2])')"
echo "    python3 = $PY_VER"
command -v curl >/dev/null || { echo "curl tidak ada."; exit 1; }
ARCH="$(uname -m)"
[[ "$ARCH" == "aarch64" ]] || echo "PERINGATAN: arch=$ARCH, skrip ini ditarget aarch64."
command -v ssh >/dev/null || { echo "ssh (OpenSSH client) tidak ada — wajib utk tunnel."; exit 1; }

echo "==> [2/8] Pasang pip (get-pip.py terkunci ke versi Python ini) bila belum ada"
if ! "$PY_BIN" -m pip --version >/dev/null 2>&1; then
  GETPIP_URL="https://bootstrap.pypa.io/pip/${PY_VER}/get-pip.py"
  if ! curl -sSLf "$GETPIP_URL" -o /tmp/get-pip.py; then
    echo "    URL terkunci versi ($GETPIP_URL) tidak ada, coba get-pip.py generik..."
    curl -sSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
  fi
  "$PY_BIN" /tmp/get-pip.py --no-cache-dir "pip<21.0"
  rm -f /tmp/get-pip.py
fi
echo "    pip: $("$PY_BIN" -m pip --version)"

echo "==> [3/8] Pasang dependency aplikasi (versi terkunci, pure-Python — cek requirements.txt)"
# Semua package di requirements.txt sudah dikunci ke versi yg masih pure-Python
# & support Python 3.5 (tidak ada native extension -> tidak butuh gcc).
"$PY_BIN" -m pip install --no-cache-dir -r "$SRC_DIR/requirements.txt"

echo "==> [4/8] Zona waktu (WITA)"
timedatectl set-timezone Asia/Makassar 2>/dev/null \
  || ln -sf /usr/share/zoneinfo/Asia/Makassar /etc/localtime

echo "==> [5/8] ZeroTier (binary static, tanpa apt)"
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

echo "==> [6/8] Salin aplikasi ke $APP_DIR"
mkdir -p "$APP_DIR/data"
cp -r "$SRC_DIR/tapping_box" "$APP_DIR/"
[[ -f "$APP_DIR/config.toml" ]] || cp "$SRC_DIR/config.toml.example" "$APP_DIR/config.toml"

echo "==> [7/8] Kunci SSH untuk tunnel"
if [[ ! -f "$KEY_PATH" ]]; then
  if command -v ssh-keygen >/dev/null 2>&1; then
    ssh-keygen -t ed25519 -N "" -C "tapping-box@$(hostname)" -f "$KEY_PATH"
  else
    echo ""
    echo "GAGAL: ssh-keygen tidak ada di board (image Yocto ini minimal)."
    echo "Generate key pair di mesin LAIN yang punya ssh-keygen, lalu salin:"
    echo "  ssh-keygen -t ed25519 -N \"\" -f ssh_key"
    echo "Lalu taruh isi file 'ssh_key' (private) di: $KEY_PATH"
    echo "dan isi file 'ssh_key.pub' (public) di:      $KEY_PATH.pub"
    echo "Setelah itu jalankan ulang: chmod 600 $KEY_PATH && $0"
    exit 1
  fi
fi
chmod 600 "$KEY_PATH" "$APP_DIR/config.toml"

echo "==> [8/8] systemd service"
cp "$SRC_DIR/tapping-box.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable tapping-box.service

cat <<MSG

============================ SELESAI ============================
Catatan platform: Yocto sumo, Python ${PY_VER} (EOL). Dependency dikunci
ke versi pure-Python lama yang masih kompatibel (lihat requirements.txt).
SSH tunnel pakai binary /usr/bin/ssh langsung (bukan paramiko).

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
