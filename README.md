# UGREEN iDX6011 Inference Liberation

Use the local model already running on your UGREEN AI NAS from other devices and agents, through an authenticated, OpenAI-compatible chat endpoint on your Tailscale network.

**No second model download. No replacement inference engine. No public internet endpoint.** This project puts a small, separate proxy in front of the existing vendor gateway. The original llama.cpp SYCL worker and UGREEN's existing Nginx configuration are left alone.

> **Community project, not a UGREEN-supported API integration.** The working path was reported on an **iDX6011 Pro** with the bundled Qwen3.5-35B-A3B model. Firmware layouts can change. Do not assume that another model, NAS, or firmware version has the same port or services. Review the scripts before running anything as root.

## What has actually been verified?

The maintainer reported successful authenticated requests through the protected endpoint: `GET /v1/models` returned HTTP 200 with the configured model, and `POST /v1/chat/completions` returned HTTP 200 with non-empty final text. The gateway also answered a direct loopback completion during discovery.

| Item | Observed on the original NAS |
|---|---|
| Hardware | UGREEN iDX6011 Pro |
| Worker | Vendor `.llama-server` in a SYCL runtime directory |
| Service | `llama_serv_sycl@aiconsole.service` |
| Gateway | `infer_gateway_s`, listening on loopback |
| Discovered gateway port | `62891`, **an observation, not a guaranteed default** |
| Working request model ID | `Qwen3.5-35B-A3B-GGUF/Qwen3.5-35B-A3B-GGUF` |
| Advertised context | 51,200 tokens; not a long-context load test |
| Returned worker fingerprint | `b8416-51897dd49`; not a support requirement |
| Firmware version | Not recorded in the shared evidence |

The public installer generalizes that working configuration. Its local proxy tests use a mock backend, not NAS hardware. **The new-user Tailscale bootstrap, generalized installer, reboot persistence, vision, tool calling, and actual model streaming still need independent hardware validation.** A six-token completion reported about 15.85 generated tokens/second; that tiny sample is not a sustained benchmark or a promise of 20 tokens/second.

## Architecture

```text
Mac / Linux / Windows client / agent
  connected to the same tailnet
           |
           | HTTPS + bearer API key, permitted by tailnet policy
           v
Tailscale Serve :8443
           |
           v
Separate Nginx proxy, 127.0.0.1:18080
  GET  /v1/models
  POST /v1/chat/completions
           |
           v
Existing UGREEN gateway, 127.0.0.1:<discovered port>
           |
           v
Existing llama.cpp SYCL worker over its Unix socket
```

The proxy listens only on loopback. Tailscale Serve provides private tailnet ingress, not an ordinary LAN listener. Home devices also use Tailscale for this configuration. See the [security boundaries](docs/SECURITY.md) before deploying.

## Prerequisites

| Requirement | Before you begin |
|---|---|
| Working local inference | Download/select the local model in UGREEN's AI application and confirm it answers locally. OpenClaw and Ollama are **not** required. |
| Administrative access | Enable ordinary SSH in the NAS settings, use your own NAS admin account, and obtain a root shell with `sudo -i`. The example uses SSH port 22. |
| NAS tools | Bash, Python 3, curl, Docker, systemd, `ss`, `getent`, `useradd`, `runuser`, and `/usr/sbin/nginx`. The installer checks these. Do not replace firmware packages casually to satisfy a missing dependency. |
| Tailscale | A tailnet you administer, permission to approve devices and HTTPS, and Tailscale installed on each intended client. Install the NAS component below **before** publishing inference. |
| Persistent storage | A private directory on a mounted NAS volume for Tailscale state. `/volume1/docker/tailscale-inference` is an example; adjust it to your actual storage layout. |
| Network and trust | Working DNS/time/outbound connectivity for enrollment and certificates. Review tailnet access rules before enrolling a host-networked NAS. Keep a LAN SSH recovery connection. |
| Recovery | Backups of important NAS configuration/data and an understanding of the [disable/removal instructions](docs/OPERATIONS.md). No firmware-survival guarantee is made. |

**Host-networking warning:** joining the NAS to Tailscale can also make existing services bound to all interfaces reachable under your tailnet policy. The inference API key does not protect SMB, SSH, or NAS administration. A narrow allow rule does not override an existing broad allow rule.

## 1. Get the project and open a NAS admin session

On your computer, connect using **your** account and LAN IP:

```bash
ssh -p 22 YOUR_NAS_ADMIN@YOUR_NAS_LAN_IP
sudo -i
```

Confirm the prompt belongs to the NAS and `id -u` prints `0`. Use a LAN connection for installation so changes to Tailscale cannot remove your only management path. Do not enable Tailscale SSH for this guide; ordinary SSH is sufficient.

On the NAS, clone the repository into a new directory if Git is already available:

```bash
git clone https://github.com/MahdiHedhli/UGreen-IDX6011-Inference-Liberation.git \
  /root/UGreen-IDX6011-Inference-Liberation
cd /root/UGreen-IDX6011-Inference-Liberation
git log -1 --oneline
```

Alternatively, download the repository ZIP on your computer, inspect it, and transfer/extract it on the NAS. Change later example paths accordingly. Review `scripts/install-proxy.sh` and `config/` before executing them. Record the commit you reviewed; do not pipe a live remote script directly into a root shell.

**Run the following sections in order and stop on errors.** Commands run on the NAS unless marked **client**.

## 2. Install Tailscale first

### A. Already have Tailscale on the NAS?

**Reuse it. Do not run a second host-networked Tailscale daemon.** Inspect existing processes and containers:

```bash
pgrep -x tailscaled || true
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

For an existing container named `tailscale`:

```bash
docker inspect -f 'NetworkMode={{.HostConfig.NetworkMode}}' tailscale
docker inspect -f '{{range .Mounts}}{{println .Destination .Type .Source}}{{end}}' tailscale
docker exec tailscale tailscale status
docker exec tailscale tailscale serve status
```

This guide requires `NetworkMode=host`, persistent state at the configured `TS_STATE_DIR` (normally `/var/lib/tailscale`), and a running/authenticated node. An ordinary bridge container has a different localhost from the NAS. Do not switch its network mode or recreate an existing deployment without preserving its state and reviewing other uses.

For a different container name, use that name in commands and set `TS_CONTAINER` for the installer. Native Tailscale installations need equivalent host CLI commands and a reviewed installer adaptation; they are not handled by this Docker-specific installer. Existing Serve configuration causes the installer to stop rather than reset or overwrite it.

### B. New installation: Docker on the NAS

Skip this entire subsection when reusing an existing installation. Install the official Tailscale application on your **client devices** from [Tailscale's download page](https://tailscale.com/download), and sign into the intended tailnet.

The block below creates only a new Tailscale container. Adjust `TS_DIR` to a private, persistent directory on your actual NAS volume. It refuses existing state/container paths, requests no subnet routes or exit-node role, and does not mount the Docker socket. `NET_ADMIN` and `NET_RAW` are network capabilities, not Docker `--privileged` mode.

The image is pulled once and its resolved digest is recorded and used for the container. `latest` selects an image at installation time; it is **not** a reproducible release identifier or an automatic update policy. Review the [official release notes](https://tailscale.com/changelog) and substitute a chosen release tag before pulling when appropriate.

```bash
bash <<'TAILSCALE'
set -euo pipefail
umask 077
TS_DIR=/volume1/docker/tailscale-inference
IMAGE=tailscale/tailscale:latest

[ "$(id -u)" = 0 ] || { echo 'Run on the NAS as root.' >&2; exit 1; }
[ -c /dev/net/tun ] || { echo '/dev/net/tun is missing; stop and investigate.' >&2; exit 1; }
if pgrep -x tailscaled >/dev/null || docker inspect tailscale >/dev/null 2>&1; then
  echo 'Tailscale already exists. Reuse/review it instead.' >&2
  exit 1
fi
[ ! -e "$TS_DIR" ] || { echo 'State directory already exists; do not overwrite it.' >&2; exit 1; }
install -d -m 0700 "$TS_DIR" "$TS_DIR/state"
docker pull "$IMAGE"
PINNED=$(docker image inspect "$IMAGE" --format '{{index .RepoDigests 0}}')
case "$PINNED" in *@sha256:*) ;; *) echo 'Could not resolve image digest.' >&2; exit 1;; esac
printf '%s\n' "$PINNED" > "$TS_DIR/image-digest.txt"

docker run -d --name tailscale --hostname ugreen-inference \
  --network host --restart unless-stopped \
  --cap-add NET_ADMIN --cap-add NET_RAW \
  --device /dev/net/tun:/dev/net/tun \
  --mount "type=bind,src=$TS_DIR/state,dst=/var/lib/tailscale" \
  -e TS_HOSTNAME=ugreen-inference \
  -e TS_STATE_DIR=/var/lib/tailscale \
  -e TS_AUTH_ONCE=true \
  -e TS_USERSPACE=false \
  -e TS_ACCEPT_DNS=false \
  "$PINNED"
TAILSCALE
```

Now follow the container's enrollment output:

```bash
docker logs --tail 80 -f tailscale
```

Open the current login URL in your browser, authenticate to the correct tailnet, and approve the device if required by your policy. Treat enrollment links/logs as private. Once enrolled, Ctrl+C stops following logs, not the container. If enrollment timed out, inspect the latest log and use the current URL, not an old copied one.

```bash
docker exec tailscale tailscale status
docker exec tailscale tailscale ip -4
docker exec tailscale tailscale version
```

Wait until the device is online in the admin console. Resolve `NeedsLogin`, device approval, key expiry, or Tailnet Lock approval before continuing. `TS_STATE_DIR` preserves identity; `TS_AUTH_ONCE=true` avoids unnecessary login attempts on restart. State contains credentials and must not be shared or committed.

A matching [Compose example](config/compose.yaml) is provided for users who prefer Compose. Use it **instead of**, not in addition to, `docker run`. Put it in a private persistent directory, create `state/`, and set `TAILSCALE_IMAGE` to the reviewed digest in a root-readable `.env`. Docker Compose is only needed for this optional alternative.

### C. Set access rules and HTTPS

Before publishing, review the [tailnet policy example](docs/SECURITY.md#tailnet-policy-example). Permit the intended users/devices to reach the NAS on **TCP 8443**, without unintentionally allowing access to administration or file shares. Test that unauthorized tailnet devices cannot reach that port. Policy rules are additive; keeping a broad allow-all rule defeats the restriction.

In the Tailscale admin console, enable MagicDNS and HTTPS certificates under DNS, or complete the consent flow printed by `tailscale serve` later. Certificate issuance publishes the device's certificate name to public certificate-transparency logs; choose a non-sensitive hostname. It does **not** publish your inference service to the internet. See [Tailscale's HTTPS documentation](https://tailscale.com/docs/how-to/set-up-https-certificates).

No router port-forwarding, subnet router, exit node, or Tailscale SSH is required.

## 3. Discover and verify the existing inference gateway

Open UGREEN's AI application, select the local model, and send a prompt. Then on the NAS:

```bash
ps -eo pid,ppid,user,comm | grep -Ei 'llama|infer_gateway|aiconsole'
systemctl show llama_serv_sycl@aiconsole.service -p MainPID -p ActiveState
ss -lntp | grep -E 'infer_gateway|llama'
ss -xlpn | grep -E 'infer_gateway|llama'
```

In the original deployment, the gateway listened on `127.0.0.1:62891` and its child `.llama-server` listened on a Unix socket. A worker absent from TCP listeners does not mean the model lacks an HTTP interface. [Discovery notes](docs/DISCOVERY.md) show how to trace it without dumping credentials.

**Replace `62891` with the actual loopback gateway port you discovered:**

```bash
GATEWAY_PORT=62891
curl -q --noproxy '*' -fsS --connect-timeout 3 --max-time 15 \
  "http://127.0.0.1:${GATEWAY_PORT}/v1/models"
```

Confirm JSON contains the intended model ID. Copy the exact request ID from the catalog. A `mmproj-BF16` entry is not evidence of a second standalone chat model; do not select it as the chat model. The gateway can legitimately return 404 for `/health` while chat works.

Before installing the proxy, test one direct completion:

```bash
curl -q --noproxy '*' -fsS --connect-timeout 3 --max-time 180 \
  -H 'Content-Type: application/json' \
  --data '{"model":"Qwen3.5-35B-A3B-GGUF/Qwen3.5-35B-A3B-GGUF","messages":[{"role":"user","content":"Reply with exactly: NAS inference is working."}],"max_tokens":512,"stream":false}' \
  "http://127.0.0.1:${GATEWAY_PORT}/v1/chat/completions"
```

Change the model ID as needed. Require a non-empty `choices[0].message.content`, not merely HTTP 200. A reasoning-only answer cut off at the token limit is a different problem from a missing endpoint. **Stop if the direct test fails.** The proxy will not fix a broken or unauthenticated upstream API.

## 4. Install the API-key-protected proxy

In the reviewed repository directory, as root:

```bash
GATEWAY_PORT=62891 \
MODEL_ID='Qwen3.5-35B-A3B-GGUF/Qwen3.5-35B-A3B-GGUF' \
bash scripts/install-proxy.sh
```

Again, use your discovered port/model. Optional environment overrides are `PROXY_PORT=18080`, `HTTPS_PORT=8443`, and `TS_CONTAINER=tailscale`. All three ports must be distinct. Change subsequent commands to match any overrides.

The script refuses existing installation files/accounts, occupied proxy ports, and existing Serve configuration. It creates a non-login service account, a separate systemd service, and a random 256-bit API key. It validates Nginx and checks missing/wrong keys, model access, rejected routes, and rejected methods before enabling the service. It does **not** invoke Serve or modify the vendor gateway.

Continue only after **`LOCAL CHECKS PASSED`**. On errors, do not rerun blindly or disable safeguards. See [partial-install recovery](docs/OPERATIONS.md#partial-installation).

Files created:

```text
/etc/ugreen-inference/nginx.conf
/etc/ugreen-inference/auth.conf        # secret, readable by root and proxy group
/etc/ugreen-inference/client.header    # secret, root-only
/etc/ugreen-inference/client.env       # secret, root-only
/etc/systemd/system/ugreen-inference-proxy.service
/run/ugreen-inference/                # runtime files managed by systemd
```

**Never publish `client.env`, `client.header`, `auth.conf`, or Tailscale state.** Displaying `nginx -T` can also reveal the key. The repository's ignore rules are only a backstop, not secret protection.

## 5. Publish through Tailscale Serve

Verify that TCP 8443 is allowed only for intended clients and no existing Serve/Funnel listener occupies it. With the default ports/container name:

```bash
docker exec -it tailscale \
  tailscale serve --bg --https=8443 http://127.0.0.1:18080
docker exec tailscale tailscale serve status
```

Complete any HTTPS consent URL. **Use Serve, never Funnel.** The destination must be the protected proxy (`18080`), not the unauthenticated vendor gateway (`62891`). Do not use `serve reset`, which can remove unrelated services.

Record the actual printed hostname. The API base URL is:

```text
https://YOUR-NAS.YOUR-TAILNET.ts.net:8443/v1
```

The script records that base URL and the generated key in `/etc/ugreen-inference/client.env`. Read it privately as root to copy the key into your password manager or client secret store. Do not paste it into an issue, screenshot, or chat. You do not need to create an SSH login or give sudo to inference clients.

## 6. Test from another device

On a **client computer** with Tailscale connected and Python 3 installed, obtain this repository and run:

```bash
python3 scripts/test-client.py \
  --base-url 'https://YOUR-NAS.YOUR-TAILNET.ts.net:8443/v1' \
  --model 'Qwen3.5-35B-A3B-GGUF/Qwen3.5-35B-A3B-GGUF'
```

The script prompts for the key without echoing it. It uses HTTPS certificate verification, disables environment HTTP proxies for the test, refuses redirects, verifies unauthenticated and incorrect-key requests fail, checks the model catalog, and requests a synthetic completion. It does not put the key in process arguments.

Success includes:

```text
PASS: /v1/models (HTTP 200, ... configured model present)
PASS: /v1/chat/completions (HTTP 200, non-empty final text)
Authenticated inference test succeeded.
```

Client settings for software that supports a custom chat-completions provider:

| Field | Value |
|---|---|
| Base URL | The printed HTTPS URL, ending in `/v1` |
| API key | The generated key, not an arbitrary placeholder |
| Model | The exact working catalog ID |
| API mode | Chat Completions |

This is a subset of an OpenAI-compatible API, not an OpenAI service or a claim of complete protocol compatibility. `/v1/responses`, embeddings, model management, and browser CORS preflight are intentionally not exposed. Tools, vision, and streamed model responses need separate compatibility tests. A containerized client also needs actual tailnet connectivity/DNS; the host having Tailscale does not prove the container is configured correctly.

## Maintenance, rollback, and contributions

Read [operations and troubleshooting](docs/OPERATIONS.md) for key rotation, updates, port changes, failures, and removal. Read [security](docs/SECURITY.md) for the limits of this setup.

Quick disable with the default ports:

```bash
docker exec tailscale tailscale serve --bg --https=8443 off
systemctl disable --now ugreen-inference-proxy.service
```

This does not stop the local model or remove Tailscale. Substitute your configured port/container if different.

For contributions, report NAS model, firmware version, model ID, runtime fingerprint, Tailscale version, HTTP statuses, and whether tests were LAN-local, tailnet, or mock-only. Redact credentials, enrollment URLs, personal hostnames, and private addresses. See [CONTRIBUTING.md](CONTRIBUTING.md). No model weights or vendor binaries are redistributed here; their original terms remain applicable.

## Primary references

- [Tailscale Docker overview](https://tailscale.com/docs/features/containers/docker), [configuration parameters](https://tailscale.com/docs/features/containers/docker/docker-params), and [container startup implementation](https://github.com/tailscale/tailscale/blob/main/cmd/containerboot/main.go).
- [Docker host networking](https://docs.docker.com/engine/network/drivers/host/).
- [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve) and [Serve CLI](https://tailscale.com/docs/reference/tailscale-cli/serve).
- [HTTPS certificates](https://tailscale.com/docs/how-to/set-up-https-certificates) and [grants syntax](https://tailscale.com/docs/reference/syntax/grants).
- [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
- [Nginx map](https://nginx.org/en/docs/http/ngx_http_map_module.html), [proxy](https://nginx.org/en/docs/http/ngx_http_proxy_module.html), and [connection limits](https://nginx.org/en/docs/http/ngx_http_limit_conn_module.html).
- [systemd service sandboxing](https://man7.org/linux/man-pages/man5/systemd.exec.5.html).

These references document the underlying tools. They are not evidence that UGREEN supports this community configuration.
