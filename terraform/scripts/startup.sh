#!/bin/bash
set -e

# ── Variables injected by Terraform ──────────────────────────────────────────
CLOUD_SQL_CONNECTION_NAME="${cloud_sql_connection_name}"
APP_PORT="${app_port}"

# ── System setup ──────────────────────────────────────────────────────────────
apt-get update -y
apt-get install -y python3 python3-pip python3-venv git nginx

# ── Install Cloud SQL Auth Proxy (replaces socket-based connection on App Engine)
curl -o /usr/local/bin/cloud-sql-proxy \
  https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.6.0/cloud-sql-proxy.linux.amd64
chmod +x /usr/local/bin/cloud-sql-proxy

# ── Clone your Gallery application ───────────────────────────────────────────
# TODO: Replace with your actual repo URL
APP_DIR="/opt/gallery"
git clone https://github.com/nazarit19/se422tp4.git "$APP_DIR"
cd "$APP_DIR"

# ── Create virtual environment and install dependencies ───────────────────────
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# ── Write environment config (mirrors app.yaml env_variables) ─────────────────
cat > "$APP_DIR/.env" <<EOF
SESSION_COOKIE_SECURE=false
USE_SECRET_MANAGER=true
CLOUD_SQL_CONNECTION_NAME=$CLOUD_SQL_CONNECTION_NAME
PORT=$APP_PORT
FLASK_ENV=production
EOF

# ── Systemd: Cloud SQL Auth Proxy ─────────────────────────────────────────────
# Connects to Cloud SQL via TCP on localhost:3306
cat > /etc/systemd/system/cloud-sql-proxy.service <<EOF
[Unit]
Description=Cloud SQL Auth Proxy
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/cloud-sql-proxy --port 3306 $CLOUD_SQL_CONNECTION_NAME
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ── Systemd: Gunicorn (Flask app) ─────────────────────────────────────────────
cat > /etc/systemd/system/gallery.service <<EOF
[Unit]
Description=Gallery Flask Application
After=network.target cloud-sql-proxy.service
Requires=cloud-sql-proxy.service

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/gunicorn --bind 127.0.0.1:$APP_PORT --workers 2 photogallery.app:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# ── Nginx: reverse proxy + static file serving ────────────────────────────────
cat > /etc/nginx/sites-available/gallery <<EOF
server {
    listen 80;

    # Serve static files directly (bypasses gunicorn)
    location /static {
        alias $APP_DIR/photogallery/static;
    }

    # Health check endpoint
    location /health {
        proxy_pass http://127.0.0.1:$APP_PORT/health;
        proxy_set_header Host \$host;
    }

    # Everything else goes to Flask
    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
EOF

ln -sf /etc/nginx/sites-available/gallery /etc/nginx/sites-enabled/gallery
rm -f /etc/nginx/sites-enabled/default

# ── Start all services ────────────────────────────────────────────────────────
systemctl daemon-reload
systemctl enable cloud-sql-proxy gallery nginx
systemctl start cloud-sql-proxy
sleep 3  # give proxy a moment before starting app
systemctl start gallery
systemctl restart nginx

echo "Gallery Flask app running. Nginx on port 80 → gunicorn on $APP_PORT"