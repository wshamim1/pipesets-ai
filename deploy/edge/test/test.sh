#!/usr/bin/env bash
# Checks the edge's path rules against stand-in upstreams (stub.py), no real backend needed:
#   deploy/edge/test/test.sh            (ENGINE=podman to use podman; CI runs it with docker)
# Builds the edge image, starts it on a private network next to two stubs and probes it with curl.
set -euo pipefail
cd "$(dirname "$0")"
ENGINE=${ENGINE:-docker}
NET=pipesets-edge-test
PORT=${EDGE_TEST_PORT:-18443}
WORK=$(mktemp -d)

cleanup() {
    $ENGINE rm -f edge-test-proxy edge-test-denied edge-test-backend edge-test-frontend >/dev/null 2>&1 || true
    $ENGINE network rm $NET >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT
cleanup; WORK=$(mktemp -d)

$ENGINE build -q -t pipesets-ai-edge:test .. >/dev/null
$ENGINE network create $NET >/dev/null
for name in backend frontend; do
    port=$([ $name = backend ] && echo 8000 || echo 8080)
    $ENGINE run -d --name edge-test-$name --network $NET --network-alias $name -e NAME=$name \
        -v "$PWD/stub.py:/stub.py:ro" docker.io/library/python:3.12-alpine python /stub.py $port >/dev/null
done
run_edge() {  # name, host port, [ui-allow.conf]
    local extra=()
    [ -n "${3:-}" ] && extra=(-v "$3:/etc/nginx/ui-allow.conf:ro")
    $ENGINE run -d --name "$1" --network $NET -p "$2:443" -e PUBLIC_HOST=api.test -e UI_HOST=app.test \
        ${extra[@]+"${extra[@]}"} pipesets-ai-edge:test >/dev/null
}
run_edge edge-test-proxy $PORT
printf 'allow 10.255.0.0/16;\ndeny all;\n' > "$WORK/deny.conf"
run_edge edge-test-denied $((PORT + 1)) "$WORK/deny.conf"
for _ in $(seq 30); do curl -sk -o /dev/null --resolve "api.test:$PORT:127.0.0.1" "https://api.test:$PORT/" && break; sleep 1; done

fails=0
# expect <status> <body substring or -> <host> <port> <path> [curl args...]
expect() {
    local want=$1 body=$2 host=$3 port=$4 path=$5; shift 5
    local got out
    out=$(curl -sk --path-as-is -o "$WORK/body" -w '%{http_code}' --resolve "$host:$port:127.0.0.1" "$@" "https://$host:$port$path" || true)
    got=$(cat "$WORK/body" 2>/dev/null || true)
    if [ "$out" = "$want" ] && { [ "$body" = - ] || [[ "$got" == *"$body"* ]]; }; then
        echo "ok   $out $host$path"
    else
        echo "FAIL $host$path: want $want ${body/#-/}, got $out ${got:0:80}"; fails=$((fails + 1))
    fi
}
P=$PORT
expect 200 "backend GET /v1/apps"          api.test $P /v1/apps
expect 200 "backend POST /v1/hooks/t"      api.test $P /v1/hooks/t -X POST
expect 200 "proto=https"                   api.test $P /v1/apps
expect 200 "backend POST /v1/chat/pc_t/message" api.test $P /v1/chat/pc_t/message -X POST
expect 200 "frontend GET /c/pc_t"          api.test $P /c/pc_t
expect 200 "frontend GET /assets/chat.js"  api.test $P /assets/chat.js
expect 403 -                               api.test $P /c/pc_t -X POST
for path in /api/apps /api/auth/login /docs /openapi.json /health / /v1/../api/apps /v1/%2e%2e/api/apps \
            /v1/..%2fapi/apps /v1%2f../api/apps //api/apps /V1/apps \
            /c/ /c/a/b /c/../api/apps /index.html /assets/../api/apps; do
    expect 404 - api.test $P "$path"
done
expect 200 "frontend GET /"                app.test $P /
expect 200 "frontend GET /api/api/apps"    app.test $P /api/api/apps
expect 000 - other.test $P /v1/apps         # unknown hostname: no TLS handshake
expect 403 - app.test $((P + 1)) /         # ui-allow.conf denies
expect 200 "backend GET /v1/apps"          api.test $((P + 1)) /v1/apps

# A spoofed X-Forwarded-For is replaced, not passed on
spoof=$(curl -sk --resolve "api.test:$P:127.0.0.1" -H "X-Forwarded-For: 6.6.6.6" "https://api.test:$P/v1/apps")
[[ "$spoof" == *6.6.6.6* ]] && { echo "FAIL spoofed X-Forwarded-For reached the backend"; fails=$((fails + 1)); } || echo "ok   spoofed X-Forwarded-For replaced"
curl -skI --resolve "api.test:$P:127.0.0.1" "https://api.test:$P/v1/apps" | grep -qi '^strict-transport-security' \
    && echo "ok   HSTS" || { echo "FAIL no HSTS header"; fails=$((fails + 1)); }

[ $fails = 0 ] && echo "edge: all checks passed" || { echo "edge: $fails check(s) failed"; exit 1; }
