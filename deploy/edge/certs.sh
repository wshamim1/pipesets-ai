#!/bin/sh
# Runs from /docker-entrypoint.d before nginx starts (after the templates are rendered).
#
# Links /etc/nginx/certs/<host>/ to the Let's Encrypt certificate when certbot has issued one,
# else to a self-signed stand-in so nginx can start and answer the first ACME challenge. A
# background loop re-checks every 6 hours and reloads nginx, which picks up both the first
# certificate and every renewal.
set -eu

link_certs() {
    for host in "$PUBLIC_HOST" "$UI_HOST"; do
        live="/etc/letsencrypt/live/$host"
        dir="/etc/nginx/certs/$host"
        mkdir -p "$dir"
        if [ -s "$live/fullchain.pem" ] && [ -s "$live/privkey.pem" ]; then
            src="$live"
        else
            src="/etc/nginx/selfsigned/$host"
            if [ ! -s "$src/fullchain.pem" ]; then
                mkdir -p "$src"
                openssl req -x509 -nodes -newkey rsa:2048 -days 30 -subj "/CN=$host" \
                    -addext "subjectAltName=DNS:$host" \
                    -keyout "$src/privkey.pem" -out "$src/fullchain.pem" 2>/dev/null
                echo "certs.sh: no Let's Encrypt certificate for $host yet; using a self-signed one"
            fi
        fi
        ln -sf "$src/fullchain.pem" "$dir/fullchain.pem"
        ln -sf "$src/privkey.pem" "$dir/privkey.pem"
    done
}

link_certs

(
    while :; do
        sleep "${CERT_RELOAD_INTERVAL:-6h}"
        link_certs && nginx -s reload
    done
) &
