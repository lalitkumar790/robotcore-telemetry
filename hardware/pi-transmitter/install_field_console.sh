#!/usr/bin/env bash
set -euo pipefail

PI_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
VENV_PYTHON="$PI_DIR/.venv/bin/python"
ENV_FILE="/etc/robotcore-field-console.env"
UNIT_FILE="/etc/systemd/system/robotcore-field-console.service"
OLD_UNIT="robotcore-transmitter.service"
PAIRING_KEY_FILE="/etc/robotcore-pairing.key"
DEVICE_ID_FILE="/etc/robotcore-device-id"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Missing $VENV_PYTHON. Create the project venv and install hardware/pi-transmitter/requirements.txt first." >&2
  exit 1
fi

if [[ "$EUID" -ne 0 ]]; then
  if ! command -v sudo >/dev/null 2>&1; then
    echo "Run this installer with sudo/root privileges." >&2
    exit 1
  fi
  exec sudo --preserve-env bash "$0" "$@"
fi

SERVICE_USER="$(printenv SUDO_USER 2>/dev/null || true)"
if [[ -z "$SERVICE_USER" || "$SERVICE_USER" == "root" ]]; then
  SERVICE_USER="$(stat -c '%U' "$PI_DIR")"
fi
if [[ -z "$SERVICE_USER" || "$SERVICE_USER" == "root" ]]; then
  echo "Could not determine the non-root project owner. Run this from your normal Pi account." >&2
  exit 1
fi
SERVICE_GROUP="$(id -gn "$SERVICE_USER")"

echo "[SETUP] Installing field-console Python dependencies..."
"$VENV_PYTHON" -m pip install -r "$PI_DIR/requirements.txt"

if getent group dialout >/dev/null 2>&1 && ! id -nG "$SERVICE_USER" | tr ' ' '\n' | grep -qx dialout; then
  usermod -aG dialout "$SERVICE_USER"
  echo "[SETUP] Added $SERVICE_USER to dialout."
fi
if getent group bluetooth >/dev/null 2>&1 && ! id -nG "$SERVICE_USER" | tr ' ' '\n' | grep -qx bluetooth; then
  usermod -aG bluetooth "$SERVICE_USER"
  echo "[SETUP] Added $SERVICE_USER to bluetooth."
fi

# A shared 256-bit key encrypts the Pi's tunnel URL and bearer token before either is sent over LoRa.
if [[ ! -f "$PAIRING_KEY_FILE" ]]; then
  "$VENV_PYTHON" -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="))' > "$PAIRING_KEY_FILE"
  echo "[SETUP] Created a new encrypted LoRa pairing key."
fi
chmod 0600 "$PAIRING_KEY_FILE"
chown "$SERVICE_USER:$SERVICE_GROUP" "$PAIRING_KEY_FILE"

if [[ ! -f "$DEVICE_ID_FILE" ]]; then
  "$VENV_PYTHON" -c 'import secrets; print("pi-" + secrets.token_hex(6))' > "$DEVICE_ID_FILE"
fi
DEVICE_ID="$(tr -d '\r\n' < "$DEVICE_ID_FILE")"

# Install the official Cloudflare connector on supported Linux architectures when possible.
if ! command -v cloudflared >/dev/null 2>&1; then
  ARCH="$(dpkg --print-architecture 2>/dev/null || true)"
  case "$ARCH" in
    arm64) CLOUDFLARED_DEB="cloudflared-linux-arm64.deb" ;;
    armhf) CLOUDFLARED_DEB="cloudflared-linux-armhf.deb" ;;
    amd64) CLOUDFLARED_DEB="cloudflared-linux-amd64.deb" ;;
    *) CLOUDFLARED_DEB="" ;;
  esac
  if [[ -n "$CLOUDFLARED_DEB" ]] && command -v curl >/dev/null 2>&1; then
    echo "[SETUP] Downloading cloudflared for $ARCH..."
    if curl -fL --retry 2 --connect-timeout 10 "https://github.com/cloudflare/cloudflared/releases/latest/download/$CLOUDFLARED_DEB" -o /tmp/cloudflared-robotcore.deb; then
      dpkg -i /tmp/cloudflared-robotcore.deb || apt-get install -f -y
      rm -f /tmp/cloudflared-robotcore.deb
    else
      echo "[WARN] cloudflared could not be downloaded now. The Pi will keep checking, but remote tunnel pairing needs cloudflared installed."
    fi
  else
    echo "[WARN] Unsupported architecture or curl unavailable; install cloudflared to enable remote LoRa pairing."
  fi
fi

mkdir -p "$PI_DIR/missions"
chown "$SERVICE_USER:$SERVICE_GROUP" "$PI_DIR/missions"

if [[ ! -f "$ENV_FILE" ]]; then
  CONTROL_TOKEN="$("$VENV_PYTHON" -c 'import secrets; print(secrets.token_urlsafe(32))')"
  IMU_ADDRESS="D7:D5:A2:97:34:24"
  MISSIONS_DIR="$PI_DIR/missions"
  if [[ -f /etc/robotcore-transmitter.env ]]; then
    EXISTING_IMU="$(sed -n 's/^ROBOTCORE_IMU_ADDRESS=//p' /etc/robotcore-transmitter.env | tail -n 1)"
    EXISTING_MISSIONS="$(sed -n 's/^ROBOTCORE_MISSIONS_DIR=//p' /etc/robotcore-transmitter.env | tail -n 1)"
    [[ -n "$EXISTING_IMU" ]] && IMU_ADDRESS="$EXISTING_IMU"
    [[ -n "$EXISTING_MISSIONS" ]] && MISSIONS_DIR="$EXISTING_MISSIONS"
  fi
  cat > "$ENV_FILE" <<EOF
ROBOTCORE_FIELD_CONTROL_TOKEN=$CONTROL_TOKEN
ROBOTCORE_IMU_ADDRESS=$IMU_ADDRESS
ROBOTCORE_MISSIONS_DIR=$MISSIONS_DIR
ROBOTCORE_TX_INTERVAL=2.0
ROBOTCORE_PAIRING_KEY_FILE=$PAIRING_KEY_FILE
ROBOTCORE_DEVICE_ID=$DEVICE_ID
EOF
  chmod 0600 "$ENV_FILE"
  chown root:root "$ENV_FILE"
  echo "[SETUP] Created a new local control token."
else
  if ! grep -q '^ROBOTCORE_FIELD_CONTROL_TOKEN=' "$ENV_FILE"; then
    CONTROL_TOKEN="$("$VENV_PYTHON" -c 'import secrets; print(secrets.token_urlsafe(32))')"
    printf '\nROBOTCORE_FIELD_CONTROL_TOKEN=%s\n' "$CONTROL_TOKEN" >> "$ENV_FILE"
  fi
  if ! grep -q '^ROBOTCORE_PAIRING_KEY_FILE=' "$ENV_FILE"; then
    printf '\nROBOTCORE_PAIRING_KEY_FILE=%s\n' "$PAIRING_KEY_FILE" >> "$ENV_FILE"
  fi
  if ! grep -q '^ROBOTCORE_DEVICE_ID=' "$ENV_FILE"; then
    printf '\nROBOTCORE_DEVICE_ID=%s\n' "$DEVICE_ID" >> "$ENV_FILE"
  fi
  chmod 0600 "$ENV_FILE"
  chown root:root "$ENV_FILE"
  echo "[SETUP] Preserved the existing field-console environment/token."
fi

# Avoid running two processes against the same USB serial devices.
systemctl stop "$OLD_UNIT" 2>/dev/null || true
systemctl disable "$OLD_UNIT" 2>/dev/null || true

cat > "$UNIT_FILE" <<EOF
[Unit]
Description=RobotCore local field session console
After=bluetooth.service
Wants=bluetooth.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PI_DIR
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1
ExecStartPre=/usr/bin/udevadm settle --timeout=20
ExecStart=$VENV_PYTHON $PI_DIR/field_agent.py --host 0.0.0.0 --port 8766
Restart=on-failure
RestartSec=3
KillSignal=SIGTERM
KillMode=mixed
TimeoutStopSec=50
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

chmod 0644 "$UNIT_FILE"
systemctl daemon-reload
systemctl enable --now robotcore-field-console.service

PI_IPS="$(hostname -I 2>/dev/null || true)"
TOKEN="$(sed -n 's/^ROBOTCORE_FIELD_CONTROL_TOKEN=//p' "$ENV_FILE" | tail -n 1)"
PAIRING_KEY="$(tr -d '\r\n' < "$PAIRING_KEY_FILE")"

echo
echo "RobotCore Field Console installed and started."
echo "Pi addresses: $PI_IPS"
echo "Open from a phone on a network that can reach this Pi:"
echo "  http://<PI-IP>:8766/field-console"
echo
echo "Pi field-console token (paste in the local page; keep private):"
echo "  $TOKEN"
echo
echo "The old auto-record service has been disabled so boots/restarts do not create missions automatically."
echo "Use the local console to check devices and start/stop a paired session."
echo "The console is LAN-only. Do not forward port 8766 to the public internet."
