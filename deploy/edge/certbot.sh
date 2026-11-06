#!/bin/sh
# Entry point of the certbot container (compose.edge.yaml): issue a certificate for each host
# once, then renew twice a day. Challenges are answered by the edge from the shared webroot.
# LETSENCRYPT_STAGING=1 uses Let's Encrypt's staging CA (untrusted certs, no rate limits).
set -eu

: "${LETSENCRYPT_EMAIL:?set LETSENCRYPT_EMAIL in .env}"
staging=""
[ "${LETSENCRYPT_STAGING:-0}" = "1" ] && staging="--staging"

# Give the edge a moment to come up with its stand-in certificates
sleep 10

for host in $PUBLIC_HOST $UI_HOST; do
    if [ ! -f "/etc/letsencrypt/renewal/$host.conf" ]; then
        certbot certonly --webroot -w /var/www/certbot -d "$host" $staging \
            --email "$LETSENCRYPT_EMAIL" --agree-tos --non-interactive --keep-until-expiring \
            || echo "certbot.sh: could not get a certificate for $host (DNS pointing here? port 80 open?)"
    fi
done

while :; do
    certbot renew --webroot -w /var/www/certbot --quiet || true
    sleep 12h
done
