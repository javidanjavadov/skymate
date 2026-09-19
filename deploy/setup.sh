#!/usr/bin/env bash
# SkyMate server setup for a fresh Ubuntu 22.04 / 24.04 machine (Oracle Cloud, Google Cloud, any VPS).
#
#   curl -fsSL https://raw.githubusercontent.com/<you>/skymate/main/deploy/setup.sh | bash
#   # or, from a cloned repo:  bash deploy/setup.sh
#
# Optional: DOMAIN=api.example.com bash deploy/setup.sh   -> automatic HTTPS via Caddy
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/javidanjavadov/skymate.git}"
APP_DIR="${APP_DIR:-/opt/skymate}"
DOMAIN="${DOMAIN:-}"
RUN_USER="$(id -un)"

echo "==> Installing system packages"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip git libeccodes0 curl

if [ "$(free -m | awk '/^Mem:/{print $2}')" -lt 2000 ] && ! swapon --show | grep -q .; then
  echo "==> Low memory machine: adding 2 GB swap"
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "==> Fetching code into $APP_DIR"
if [ -f "$(pwd)/run.py" ] && [ "$(pwd)" != "$APP_DIR" ] && [ ! -d "$APP_DIR" ]; then
  sudo mkdir -p "$APP_DIR" && sudo cp -r "$(pwd)/." "$APP_DIR/"
elif [ ! -d "$APP_DIR/.git" ]; then
  sudo git clone "$REPO_URL" "$APP_DIR"
else
  sudo git -C "$APP_DIR" pull --ff-only
fi
sudo chown -R "$RUN_USER":"$RUN_USER" "$APP_DIR"
cd "$APP_DIR"

echo "==> Python environment"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

echo "==> Secrets (.env)"
touch .env && chmod 600 .env
ask() {  # ask KEY "prompt"
  if ! grep -q "^$1=" .env; then
    read -r -p "$2: " val < /dev/tty
    [ -n "$val" ] && echo "$1=$val" >> .env
  fi
}
ask TELEGRAM_BOT_TOKEN "Telegram bot token (from @BotFather)"
ask WEATHER_TOKEN "OpenWeather key for last-resort fallback (Enter to skip)"
if [ -z "$DOMAIN" ]; then
  grep -q '^SKYMATE_API_HOST=' .env || echo "SKYMATE_API_HOST=0.0.0.0" >> .env
fi

echo "==> systemd service"
sudo tee /etc/systemd/system/skymate.service >/dev/null <<EOF
[Unit]
Description=SkyMate weather API, ingest and Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python run.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now skymate

open_port() {
  if command -v ufw >/dev/null && sudo ufw status | grep -q active; then sudo ufw allow "$1"/tcp; fi
  # Oracle Ubuntu images ship iptables rules that block everything except SSH.
  if sudo iptables -S INPUT 2>/dev/null | grep -q "REJECT"; then
    sudo iptables -I INPUT 5 -p tcp --dport "$1" -j ACCEPT
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent >/dev/null
    sudo netfilter-persistent save >/dev/null
  fi
}

if [ -n "$DOMAIN" ]; then
  echo "==> HTTPS for $DOMAIN via Caddy"
  sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -y && sudo apt-get install -y caddy
  echo "$DOMAIN {
    reverse_proxy 127.0.0.1:8000
}" | sudo tee /etc/caddy/Caddyfile >/dev/null
  sudo systemctl restart caddy
  open_port 80; open_port 443
  URL="https://$DOMAIN"
else
  open_port 8000
  URL="http://$(curl -s https://api.ipify.org || hostname -I | awk '{print $1}'):8000"
fi

sleep 5
echo
echo "SkyMate is running."
echo "  API:      $URL/docs"
echo "  Status:   sudo systemctl status skymate"
echo "  Logs:     tail -f $APP_DIR/logs/api.log $APP_DIR/logs/bot.log"
echo "  New key:  cd $APP_DIR && .venv/bin/python -m skymate_api.admin create-key \"Customer\" --plan pro"
echo
echo "The first forecast download takes 20-40 minutes; until then answers come from the live fallback."
