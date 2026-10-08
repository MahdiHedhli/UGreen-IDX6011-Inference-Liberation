# Operations and troubleshooting

Commands here run as root on the NAS. Examples assume the default container `tailscale`, proxy port `18080`, and HTTPS port `8443`. Substitute the values you actually installed. Keep an ordinary LAN SSH recovery session available.

## Status without printing secrets

```bash
systemctl is-active ugreen-inference-proxy.service
systemctl is-enabled ugreen-inference-proxy.service
ss -lnt '( sport = :18080 )'
docker exec tailscale tailscale serve status
docker exec tailscale tailscale status
grep -E '^UGREEN_(BASE_URL|MODEL|GATEWAY_PORT|PROXY_PORT|HTTPS_PORT|TS_CONTAINER)=' \
  /etc/ugreen-inference/client.env
```

The custom proxy should bind **only** `127.0.0.1:18080`. Serve is implemented by Tailscale, so do not use a normal host `ss` listing as the sole test of the HTTPS endpoint. Verify Serve status and call it from a permitted tailnet client.

For an internal authenticated catalog check without putting the key in process arguments:

```bash
curl -q --noproxy '*' -fsS --connect-timeout 3 --max-time 15 \
  -H @/etc/ugreen-inference/client.header \
  http://127.0.0.1:18080/v1/models
```

Inspect `journalctl -u ugreen-inference-proxy.service -n 50 --no-pager` locally for errors. Redact request URLs, identities, and other private fields before sharing. Do not run `nginx -T`: it prints included authentication configuration.

## Common failures

| Symptom | Check |
|---|---|
| SSH works on LAN but not Tailscale | These are distinct network paths. Keep using LAN SSH; check tailnet rules for SSH only if you need it. Inference clients do not require SSH access. |
| Timeout before an HTTPS response | Client Tailscale connectivity, device approval/key expiry, DNS, policy permission for TCP 8443, Serve status, and firewall conflicts. No HTTP response is not an API-key error. |
| TLS certificate error | Use the full printed `*.ts.net` hostname, not an IP address. Check clock, HTTPS enablement, and certificate provisioning. Do not solve this by disabling verification. |
| HTTP 401 | The request reached a listener requiring authentication. Use the generated key exactly. Arbitrary local-LLM placeholder keys do not work here. |
| HTTP 404 | Only two routes are exposed. Check a single `/v1` prefix, no trailing slash on `/models`, and chat-completions mode rather than Responses API. `/health` is intentionally not provided. |
| HTTP 405 | Use GET for models and POST for chat. HEAD and browser CORS OPTIONS are intentionally not enabled. |
| HTTP 413 | The request exceeds the 8 MiB body limit. Large base64 image requests can hit it; vision remains unverified. |
| HTTP 429 | The proxy's global concurrency limit of two requests is exceeded. Reduce agent concurrency. This is not a per-user rate limit. |
| HTTP 502/504 | Check the vendor model service, gateway port, upstream response, and timeouts. Do not repoint to another listener without verifying its identity/API. |
| HTTP 200 but no final text | Inspect finish reason, reasoning output, and generation limits. Catalog success or an empty completion is not an end-to-end pass. |
| Client container cannot connect | Check its DNS and actual route to the tailnet. A host Tailscale installation alone is not proof of container reachability. |
| Installer refuses an existing path/account/Serve config | It is deliberately not an updater. Preserve the installation and review; do not remove guards or reset unrelated Serve services. |

## Firmware updates and restart checks

There is no promise that custom systemd units or port choices survive a UGREEN update. Before an update, save reviewed project files and access-restricted backups of the proxy settings and Tailscale state. Those backups contain secrets.

After updating, rediscover the vendor gateway. Test direct model discovery and one direct completion, then the local authenticated proxy, and finally a remote authenticated completion. Confirm wrong/no-key requests are still rejected and no listener moved to `0.0.0.0`.

For a changed gateway port, disable Serve first, stop the proxy, and edit only `/etc/ugreen-inference/nginx.conf` to replace the old loopback upstream port in the Host header and both `proxy_pass` targets. Update the non-secret `UGREEN_GATEWAY_PORT` record in `client.env`. Validate as the service user and restart only the custom proxy. Republish only after local tests pass.

```bash
runuser -u ug-inference -- /usr/sbin/nginx -t -e stderr \
  -p /run/ugreen-inference/ -c /etc/ugreen-inference/nginx.conf
```

Note: stopping the systemd service normally removes its RuntimeDirectory. Before the manual validation above, recreate it if needed with `install -d -o ug-inference -g ug-inference -m 0700 /run/ugreen-inference`. Starting the service normally creates it automatically.

Tailscale's `--bg` Serve configuration is designed to persist, and the state directory preserves node identity. Test restart behavior during a maintenance window rather than promising it from a successful first request. Do not restart a shared Tailscale container casually: it can interrupt unrelated services. Review image updates manually; the example pins a digest and does not auto-upgrade.

## Disable immediately

With the installed default settings:

```bash
docker exec tailscale tailscale serve --bg --https=8443 off
systemctl disable --now ugreen-inference-proxy.service
```

Check Serve status and test that remote inference is unavailable. The original NAS model remains available locally. Do not use `serve reset` unless you intend to remove all that node's Serve configuration. Do not delete the Tailscale container/state simply to disable inference.

## Full removal

First complete and verify the disable step. The paths below are exclusively the files created by this project. Do not run this against an unrelated installation that happens to reuse the same name.

```bash
rm -f /etc/systemd/system/ugreen-inference-proxy.service
systemctl daemon-reload
systemctl reset-failed ugreen-inference-proxy.service 2>/dev/null || true

rm -f /etc/ugreen-inference/nginx.conf \
      /etc/ugreen-inference/auth.conf \
      /etc/ugreen-inference/client.header \
      /etc/ugreen-inference/client.env
rmdir /etc/ugreen-inference

userdel ug-inference
if getent group ug-inference >/dev/null; then groupdel ug-inference; fi
```

A non-empty directory or an account still owning running processes is a reason to stop and inspect, not add a force flag. Systemd normally removes `/run/ugreen-inference` when stopping the service; inspect any leftover temporary subdirectories before removing them. Remove old API-key copies from clients and secure backups according to your retention needs. Tailscale and all vendor services are deliberately retained.

## Key rotation

This initial guide uses a controlled disable/remove/reinstall workflow rather than editing live authentication files. Disable remote access, stop the proxy, follow full removal, then run the reviewed installer to generate a new key. Repeat the local and remote tests and update authorized clients. No model reinstall or restart is needed.

Do not keep publishing with a compromised key while preparing a replacement. Existing installations created by an earlier manual guide may also have a client file under the NAS admin user's home directory. Locate and retire that specific old copy; this installer stores client settings under `/etc/ugreen-inference` instead and does not search user homes.

## Partial installation

The installer makes no Serve changes. If it fails after creating the service, its error handler attempts to stop and disable that custom service. Some earlier failures can leave a dedicated account, directory, or generated key behind. Review the exact state before retrying:

```bash
systemctl is-active ugreen-inference-proxy.service || true
docker exec tailscale tailscale serve status
getent passwd ug-inference || true
ls -ld /etc/ugreen-inference /run/ugreen-inference \
  /etc/systemd/system/ugreen-inference-proxy.service 2>/dev/null || true
```

Do not delete a pre-existing resource just because the installer refused it. If the failed attempt created the files/account, remove only those project-owned resources using the removal procedure, accounting for absent items. Inspect/remove empty leftover runtime directories as necessary. Correct the original prerequisite/configuration error, then retry. Never expose the unauthenticated gateway as a shortcut.

## Verification scope

The repository's automated tests exercise a mock backend through the actual Nginx template. They cover authentication, case sensitivity, method/path restrictions, credential/cookie stripping, request-size rejection, JSON forwarding, and event-stream transport. They do not establish actual NAS streaming correctness or flush latency, Tailscale policy correctness, performance, vision/tools support, installer compatibility with every firmware, or reboot survival.

Sources: [Serve CLI](https://tailscale.com/docs/reference/tailscale-cli/serve), [Tailscale container state](https://tailscale.com/docs/features/containers/docker/docker-params), [Nginx proxy behavior](https://nginx.org/en/docs/http/ngx_http_proxy_module.html), and [systemd RuntimeDirectory](https://man7.org/linux/man-pages/man5/systemd.exec.5.html).
