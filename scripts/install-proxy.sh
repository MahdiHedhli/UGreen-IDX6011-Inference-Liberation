#!/usr/bin/env bash
# Installs only a loopback proxy. Publishing through Tailscale is a separate step.
set -Eeuo pipefail
set +x
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
CFG=/etc/ugreen-inference
RUN=/run/ugreen-inference
UNIT=/etc/systemd/system/ugreen-inference-proxy.service
SERVICE=ugreen-inference-proxy.service
GATEWAY_PORT=${GATEWAY_PORT:-}
PROXY_PORT=${PROXY_PORT:-18080}
HTTPS_PORT=${HTTPS_PORT:-8443}
TS_CONTAINER=${TS_CONTAINER:-tailscale}
MODEL_ID=${MODEL_ID:-Qwen3.5-35B-A3B-GGUF/Qwen3.5-35B-A3B-GGUF}

[[ $(id -u) == 0 ]] || fail 'Run as root on the NAS, after reviewing the files.'
[[ -n $GATEWAY_PORT ]] || fail 'Set GATEWAY_PORT to the discovered loopback gateway port.'
for value in "$GATEWAY_PORT" "$PROXY_PORT" "$HTTPS_PORT"; do
    [[ $value =~ ^[1-9][0-9]{0,4}$ ]] || fail 'Ports must be decimal integers without leading zeroes.'
    (( value > 1023 && value < 65536 )) || fail 'This installer requires unprivileged ports 1024..65535.'
done
[[ $GATEWAY_PORT != "$PROXY_PORT" && $GATEWAY_PORT != "$HTTPS_PORT" && $PROXY_PORT != "$HTTPS_PORT" ]] || fail 'Use three distinct ports.'
[[ $TS_CONTAINER =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || fail 'Invalid container name.'
[[ $MODEL_ID =~ ^[a-zA-Z0-9_./:-]+$ ]] || fail 'Unexpected model ID characters. Review before adapting.'
for cmd in python3 curl docker systemctl ss getent useradd runuser install grep; do
    command -v "$cmd" >/dev/null || fail "Missing prerequisite: $cmd"
done
[[ -x /usr/sbin/nginx && -x /usr/sbin/nologin ]] || fail 'Required NAS nginx or nologin binary is missing.'
[[ -d /run/systemd/system ]] || fail 'A running systemd host is required.'
for path in "$CFG" "$RUN" "$UNIT"; do
    [[ ! -e $path && ! -L $path ]] || fail "Already exists: $path. Refusing overwrite; see docs/OPERATIONS.md."
done
if getent passwd ug-inference >/dev/null || getent group ug-inference >/dev/null; then
    fail 'Service account/group already exists. Refusing to reuse it.'
fi
[[ $(docker inspect -f '{{.HostConfig.NetworkMode}}' "$TS_CONTAINER") == host ]] || fail 'Tailscale must use host networking for this guide.'

TMP=$(mktemp -d)
UNIT_CREATED=0
cleanup() { rm -rf -- "$TMP"; }
on_error() {
    local rc=$?
    trap - ERR
    if [[ $UNIT_CREATED == 1 ]]; then
        systemctl disable --now "$SERVICE" >/dev/null 2>&1 || true
    fi
    printf '\nINSTALL INCOMPLETE. No Serve command was run. Review the error and docs/OPERATIONS.md; do not publish.\n' >&2
    exit "$rc"
}
trap cleanup EXIT
trap on_error ERR

docker exec "$TS_CONTAINER" tailscale serve status --json > "$TMP/serve.json"
python3 - "$TMP/serve.json" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    config = json.load(f)
if config:
    raise SystemExit('Existing Serve configuration: stop and review; do not reset it.')
PY
if [[ -n $(ss -H -lnt "( sport = :$PROXY_PORT or sport = :$HTTPS_PORT )") ]]; then
    fail 'A proxy or HTTPS port is already in use.'
fi
# Verify the actual model catalog, not just an HTTP status code.
curl -q --noproxy '*' -fsS --connect-timeout 3 --max-time 15 \
    "http://127.0.0.1:$GATEWAY_PORT/v1/models" > "$TMP/models.json"
python3 - "$TMP/models.json" "$MODEL_ID" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    catalog = json.load(f)
if not any(m.get('id') == sys.argv[2] for m in catalog.get('data', []) if isinstance(m, dict)):
    raise SystemExit('Configured model ID is absent from the gateway catalog.')
PY
DNS_NAME=$(docker exec "$TS_CONTAINER" tailscale status --json | python3 -c '
import json,re,sys
d=json.load(sys.stdin)
name=d.get("Self",{}).get("DNSName","").rstrip(".")
if d.get("BackendState")!="Running" or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+\.ts\.net",name):
    sys.exit("Tailscale must be Running with a valid ts.net DNS name.")
print(name)
')

# Mutations start here. Existing vendor configs and model services stay untouched.
useradd --system --user-group --no-create-home \
    --home-dir /nonexistent --shell /usr/sbin/nologin ug-inference
install -d -o root -g ug-inference -m 0750 "$CFG"
install -d -o ug-inference -g ug-inference -m 0700 "$RUN"
python3 - "$ROOT" "$CFG" "$RUN" "$GATEWAY_PORT" "$PROXY_PORT" "$HTTPS_PORT" "$DNS_NAME" "$MODEL_ID" "$TS_CONTAINER" <<'PY'
from pathlib import Path
import secrets, shlex, sys
root, cfg, run, gateway, proxy, https, dns, model, container = sys.argv[1:]
key = secrets.token_hex(32)
config = Path(root, 'config/nginx.conf.in').read_text()
for name, value in {'CFG_DIR': cfg, 'RUN_DIR': run, 'GATEWAY_PORT': gateway, 'PROXY_PORT': proxy}.items():
    config = config.replace('@@' + name + '@@', value)
if '@@' in config:
    raise SystemExit('Unresolved template variable.')
# Regex is case-sensitive for the credential; the HTTP auth scheme is not.
auth = ('map $http_authorization $inference_authorized {\n'
        '    default 0;\n'
        f'    "~^(?i:Bearer) {key}$" 1;\n'
        '}\n')
settings = {'UGREEN_BASE_URL': f'https://{dns}:{https}/v1', 'UGREEN_MODEL': model,
            'UGREEN_API_KEY': key, 'UGREEN_GATEWAY_PORT': gateway,
            'UGREEN_PROXY_PORT': proxy, 'UGREEN_HTTPS_PORT': https,
            'UGREEN_TS_CONTAINER': container}
for name, data in {
    'nginx.conf': config, 'auth.conf': auth,
    'client.header': f'Authorization: Bearer {key}\n',
    'client.env': ''.join(f'{k}={shlex.quote(v)}\n' for k,v in settings.items()),
}.items():
    with Path(cfg, name).open('x') as f:
        f.write(data)
PY
chown root:ug-inference "$CFG/nginx.conf" "$CFG/auth.conf"
chmod 0640 "$CFG/nginx.conf" "$CFG/auth.conf"
chmod 0600 "$CFG/client.env" "$CFG/client.header"
install -m 0644 "$ROOT/config/ugreen-inference-proxy.service" "$UNIT"
UNIT_CREATED=1
runuser -u ug-inference -- /usr/sbin/nginx -t -e stderr -p "$RUN/" -c "$CFG/nginx.conf"
systemctl daemon-reload
systemctl start "$SERVICE"
for attempt in {1..40}; do
    if [[ -n $(ss -H -lnt "( sport = :$PROXY_PORT )") ]]; then break; fi
    sleep 0.25
done
check_status() {
    local expected=$1 actual
    shift
    actual=$(curl -q --noproxy '*' -sS -o "$TMP/check.json" -w '%{http_code}' \
        --connect-timeout 3 --max-time 20 "$@")
    if [[ $actual != "$expected" ]]; then
        printf 'Expected HTTP %s, got %s.\n' "$expected" "$actual" >&2
        return 1
    fi
    printf 'HTTP %s check: PASS\n' "$expected"
}
URL=http://127.0.0.1:$PROXY_PORT
check_status 401 "$URL/v1/models"
check_status 401 -H 'Authorization: Bearer deliberately-wrong' "$URL/v1/models"
check_status 200 -H "@$CFG/client.header" "$URL/v1/models"
check_status 404 -H "@$CFG/client.header" "$URL/not-an-inference-route"
check_status 405 -H "@$CFG/client.header" -X POST "$URL/v1/models"
check_status 405 -H "@$CFG/client.header" "$URL/v1/chat/completions"
systemctl enable "$SERVICE"
printf '\nLOCAL CHECKS PASSED. Not published through Tailscale yet.\n'
printf 'Base URL: https://%s:%s/v1\nRoot-only client settings: %s/client.env\n' "$DNS_NAME" "$HTTPS_PORT" "$CFG"
printf 'Follow the README to publish, then run the client inference test.\n'
