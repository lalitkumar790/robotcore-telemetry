#!/usr/bin/env bash
set -euo pipefail

PI_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$PI_DIR/.venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Missing $VENV_PYTHON" >&2
  echo "Create the project virtual environment and install hardware/pi-transmitter/requirements.txt first." >&2
  exit 1
fi

if [[ "$EUID" -ne 0 ]]; then
  if ! command -v sudo >/dev/null 2>&1; then
    echo "Run this installer with sudo/root privileges (sudo is not installed)." >&2
    exit 1
  fi
  exec sudo --preserve-env bash "$0" "$@"
fi

SERVICE_USER="${SUDO_USER:-}"
if [[ -z "$SERVICE_USER" || "$SERVICE_USER" == "root" ]]; then
  SERVICE_USER="$(stat -c '%U' "$PI_DIR")"
fi
if [[ -z "$SERVICE_USER" || "$SERVICE_USER" == "root" ]]; then
  echo "Could not safely determine the non-root account that owns the project at $PI_DIR." >&2
  echo "Run this script as your normal Pi user, not from a root shell." >&2
  exit 1
fi

SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
ENV_FILE="/etc/robotcore-transmitter.env"
UNIT_FILE="/etc/systemd/system/robotcore-transmitter.service"

# Serial ports are normally owned by root:dialout. Add the service user to
# dialout if needed; this is additive and does not replace existing groups.
if getent group dialout >/dev/null 2>&1; then
  if ! id -nG "$SERVICE_USER" | tr ' ' '\n' | grep -qx dialout; then
    usermod -aG dialout "$SERVICE_USER"
    echo "Added $SERVICE_USER to dialout for USB serial access."
  fi
fi

mkdir -p "$PI_DIR/missions"
chown "$SERVICE_USER:$SERVICE_GROUP" "$PI_DIR/missions"

# Preserve an existing file so custom experiment IDs/configuration survive
# reinstalling the service. No /dev/ttyUSB* names are pinned here.
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<EOF
# RobotCore autonomous transmitter settings.
# Do NOT set ROBOTCORE_GPS_PORT or ROBOTCORE_LORA_PORT to ttyUSB numbers:
# the service discovers each adapter from its USB VID:PID after boot.
ROBOTCORE_EXPERIMENT_ID=MANIT-AUTO
ROBOTCORE_IMU_ADDRESS=D7:D5:A2:97:34:24
ROBOTCORE_MISSIONS_DIR=$PI_DIR/missions
ROBOTCORE_TX_INTERVAL=2.0
EOF
  chmod 0600 "$ENV_FILE"
  chown root:root "$ENV_FILE"
  echo "Created $ENV_FILE with default experiment ID MANIT-AUTO."
else
  echo "Preserved existing $ENV_FILE."
fi

cat > "$UNIT_FILE" <<EOF
[Unit]
Description=RobotCore autonomous GPS, IMU and LoRa field transmitter
Wants=bluetooth.service
After=bluetooth.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PI_DIR
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1
ExecStartPre=/usr/bin/udevadm settle --timeout=20
ExecStart=$VENV_PYTHON $PI_DIR/runner.py --require-lora --imu-startup-timeout 120
Restart=on-failure
RestartSec=10
KillSignal=SIGINT
TimeoutStopSec=40
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
systemctl enable robotcore-transmitter.service

echo
echo "Installed and enabled robotcore-transmitter.service."
echo "It will start automatically on boot, discover GPS/LoRa ports by USB ID,"
echo "wait for a fresh IMU reading, and write mission files under:"
echo "  $PI_DIR/missions"
echo
echo "It has NOT been started immediately, to avoid transmitting unexpectedly."
echo "Review/edit the experiment ID first:"
echo "  sudo nano $ENV_FILE"
echo
echo "Then test now with:"
echo "  sudo systemctl start robotcore-transmitter.service"
echo "  journalctl -u robotcore-transmitter.service -f"
echo
echo "Stop intentional recording with:"
echo "  sudo systemctl stop robotcore-transmitter.service"
