#!/usr/bin/env bash
# Deploiement de Talent Engine sur Ubuntu 24.04 : skullvicv.evaristekouame.com
# A lancer en root sur le VPS, depuis le dossier qui contient les fichiers :
#     bash deploy.sh
set -euo pipefail

DOMAIN="skullvicv.evaristekouame.com"
APP_DIR="/opt/talent-engine"
PORT=8123   # port interne (127.0.0.1 uniquement), pas expose a internet

echo "==> Verification du DNS"
IP_PUBLIQUE=$(curl -s4 ifconfig.me || true)
IP_DNS=$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1 || true)
echo "    VPS : ${IP_PUBLIQUE:-?}   DNS $DOMAIN : ${IP_DNS:-introuvable}"
if [ "$IP_PUBLIQUE" != "$IP_DNS" ]; then
  echo "!! Le DNS ne pointe pas encore vers ce VPS. Attendez quelques minutes puis relancez."
  exit 1
fi

echo "==> Verification : le port 80 est-il deja utilise par autre chose que nginx ?"
if ss -tlnp | grep -E ':80\s' | grep -qv nginx && ss -tlnp | grep -qE ':80\s'; then
  echo "!! Un autre service ecoute sur le port 80 (voir 'ss -tlnp | grep :80'). Arret pour ne rien casser."
  exit 1
fi

echo "==> Installation des paquets"
apt-get update -y
apt-get install -y nginx certbot python3-certbot-nginx python3 python3-pypdf

echo "==> Utilisateur et dossier applicatif"
id talent >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin talent
mkdir -p "$APP_DIR"
for f in talent_engine.py cv_parser.py web_app.py test_talent_engine.py test_cv_parser.py candidatures_exemple.csv README.md; do
  [ -f "$f" ] && cp "$f" "$APP_DIR/"
done
[ -f "$APP_DIR/candidatures.csv" ] || cp "$APP_DIR/candidatures_exemple.csv" "$APP_DIR/candidatures.csv"
chown -R talent:talent "$APP_DIR"

echo "==> Tests"
(cd "$APP_DIR" && sudo -u talent python3 -m unittest 2>&1 | tail -3)

echo "==> Service systemd"
cat > /etc/systemd/system/talent-engine.service <<EOF
[Unit]
Description=Talent Engine (SKULLVI mini-challenge)
After=network.target

[Service]
User=talent
WorkingDirectory=$APP_DIR
Environment=PORT=$PORT HOST=127.0.0.1 DATA_FILE=$APP_DIR/candidatures.csv
ExecStart=/usr/bin/python3 $APP_DIR/web_app.py
Restart=always
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$APP_DIR
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now talent-engine
sleep 1
curl -fs "http://127.0.0.1:$PORT/health" && echo " <- l'app repond"

echo "==> Nginx"
cat > /etc/nginx/sites-available/$DOMAIN <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    client_max_body_size 50k;
    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/$DOMAIN
nginx -t
systemctl reload nginx

echo "==> HTTPS (Let's Encrypt)"
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect

echo
echo "Termine : https://$DOMAIN"
