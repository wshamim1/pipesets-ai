# Edge proxy: TLS termination and per-hostname path rules (see nginx.conf.template).
FROM nginx:1.27-alpine

RUN apk add --no-cache openssl
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY snippets/ /etc/nginx/snippets/
COPY ui-allow.conf /etc/nginx/ui-allow.conf
COPY certs.sh /docker-entrypoint.d/40-certs.sh
RUN chmod +x /docker-entrypoint.d/40-certs.sh && mkdir -p /var/www/certbot /etc/letsencrypt

# Service names in compose; override for other layouts
ENV BACKEND_ADDR=backend:8000 \
    FRONTEND_ADDR=frontend:8080

EXPOSE 80 443
